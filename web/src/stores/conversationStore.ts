/**
 * useConversationStore — persistence layer for the voice transcript.
 *
 * Owns:
 *   - The list of conversations for the currently-selected agent.
 *   - The id of the "active" conversation — the one new messages get
 *     appended to. Null until a session starts (or a previous
 *     conversation is reopened).
 *
 * Does NOT own the transcript UI state itself — VoiceConversation keeps
 * its in-memory TranscriptEntry[] for low-latency streaming, and calls
 * `appendMessage` whenever an entry finalizes. The store is the
 * persistence side; the component is the rendering side.
 *
 * Pattern follows voiceStore / agentStore: plain zustand create, no
 * persist middleware (the backend is the source of truth — we re-fetch
 * on agent select instead of caching in localStorage).
 */

import { create } from 'zustand'

import type { Conversation, Message } from '../types'
import { api } from '../api/client'

interface ConversationState {
  // Per-agent conversation list — most recent first (server-ordered).
  conversations: Conversation[]
  // Active conversation id — null when no session is open or when the
  // user is mid-selection. VoiceConversation reads this to know which
  // id to append new transcript entries to.
  currentConversationId: string | null
  // Cached messages for the active conversation — used to restore the
  // transcript when the user reopens a conversation. Loaded once per
  // openConversation() call.
  messages: Message[]
  // Loading / error flags — surfaced for the UI to show a spinner
  // when a list / open call is in flight.
  isLoading: boolean
  error: string | null
  // Actions
  loadConversations: (agentId: string) => Promise<void>
  openLastConversation: (agentId: string) => Promise<Conversation | null>
  startNewConversation: (agentId: string, title?: string) => Promise<Conversation | null>
  appendMessage: (
    role: 'user' | 'assistant' | 'system',
    content: string,
    extras?: { audio_url?: string | null; metadata_?: Record<string, unknown> },
  ) => Promise<void>
  clearCurrent: () => void
  deleteConversation: (id: string) => Promise<void>
  clearError: () => void
}

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  messages: [],
  isLoading: false,
  error: null,

  loadConversations: async (agentId) => {
    set({ isLoading: true, error: null })
    try {
      const conversations = await api.listConversations(agentId)
      set({ conversations, isLoading: false })
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message })
    }
  },

  openLastConversation: async (agentId) => {
    // Reuse the already-loaded list when possible — loadConversations
    // is idempotent so a stale cache just costs one extra GET.
    if (get().conversations.length === 0) {
      await get().loadConversations(agentId)
    }
    const list = get().conversations
    if (list.length === 0) {
      // No prior conversation — caller can decide to start a new one.
      set({ currentConversationId: null, messages: [] })
      return null
    }
    // The server returns newest-first, so list[0] is the most recent.
    const conv = list[0]
    set({ currentConversationId: conv.id, messages: [], isLoading: true })
    try {
      const messages = await api.listMessages(conv.id)
      set({ messages, isLoading: false })
      return conv
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message })
      return null
    }
  },

  startNewConversation: async (agentId, title) => {
    try {
      const conv = await api.createConversation({ agent_id: agentId, title })
      // Prepend to the list so the picker shows it immediately.
      set({
        currentConversationId: conv.id,
        messages: [],
        conversations: [conv, ...get().conversations],
      })
      return conv
    } catch (e) {
      set({ error: (e as Error).message })
      return null
    }
  },

  appendMessage: async (role, content, extras) => {
    const conversationId = get().currentConversationId
    if (!conversationId) {
      // No active conversation — nothing to persist. The transcript
      // UI still receives the entry in-memory; we just don't store it.
      return
    }
    if (!content.trim()) return
    try {
      await api.appendMessage(conversationId, {
        role,
        content,
        audio_url: extras?.audio_url ?? null,
        metadata_: extras?.metadata_ ?? {},
      })
    } catch {
      // Persistence failure must not break the live conversation.
      // The store keeps the in-memory id; a later retry could be added
      // if we wanted to queue missed writes (out of scope for now).
    }
  },

  clearCurrent: () => set({ currentConversationId: null, messages: [] }),

  deleteConversation: async (id) => {
    await api.deleteConversation(id)
    const conversations = get().conversations.filter((c) => c.id !== id)
    // If the deleted one was active, drop the active pointer so the
    // next session starts fresh.
    const currentConversationId =
      get().currentConversationId === id ? null : get().currentConversationId
    set({
      conversations,
      currentConversationId,
      messages: currentConversationId === null ? [] : get().messages,
    })
  },

  clearError: () => set({ error: null }),
}))

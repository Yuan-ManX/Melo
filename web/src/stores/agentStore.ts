import { create } from 'zustand'
import type { Agent } from '../types'
import { api } from '../api/client'

interface AgentState {
  // Data
  agents: Agent[]
  currentAgentId: string | null
  // Loading / error
  isLoading: boolean
  error: string | null
  // Actions
  fetchAgents: () => Promise<void>
  selectAgent: (id: string | null) => void
  createAgent: (data: {
    name: string
    persona?: string | null
    system_prompt?: string | null
    voice_id?: string | null
    llm_config?: Record<string, unknown>
  }) => Promise<Agent | null>
  updateAgent: (
    id: string,
    data: Partial<{
      name: string
      persona: string | null
      system_prompt: string | null
      voice_id: string | null
      llm_config: Record<string, unknown>
    }>,
  ) => Promise<void>
  deleteAgent: (id: string) => Promise<void>
  clearError: () => void
}

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  currentAgentId: null,
  isLoading: false,
  error: null,

  fetchAgents: async () => {
    set({ isLoading: true, error: null })
    try {
      const agents = await api.listAgents()
      // If no agent is currently selected, default to the first in the list.
      const currentAgentId =
        get().currentAgentId === null && agents.length > 0
          ? agents[0].id
          : get().currentAgentId
      set({ agents, currentAgentId, isLoading: false })
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message })
    }
  },

  selectAgent: (id) => set({ currentAgentId: id }),

  createAgent: async (data) => {
    try {
      const agent = await api.createAgent(data)
      set({ agents: [agent, ...get().agents] })
      return agent
    } catch (e) {
      set({ error: (e as Error).message })
      return null
    }
  },

  updateAgent: async (id, data) => {
    const agent = await api.updateAgent(id, data)
    set({
      agents: get().agents.map((a) => (a.id === id ? { ...a, ...agent } : a)),
    })
  },

  deleteAgent: async (id) => {
    await api.deleteAgent(id)
    const agents = get().agents.filter((a) => a.id !== id)
    // If the deleted agent was selected, fall back to the first remaining
    // agent (or null if the list is now empty).
    const currentAgentId =
      get().currentAgentId === id
        ? agents.length > 0
          ? agents[0].id
          : null
        : get().currentAgentId
    set({ agents, currentAgentId })
  },

  clearError: () => set({ error: null }),
}))

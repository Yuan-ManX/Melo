import { create } from 'zustand'
import type { Voice } from '../types'
import { api } from '../api/client'

interface VoiceState {
  // Data
  voices: Voice[]
  // Preview state (which voice is currently being previewed, if any)
  previewingVoiceId: string | null
  // Clone progress (very lightweight — just a flag + optional error)
  cloning: boolean
  cloneError: string | null
  // Loading / error
  isLoading: boolean
  error: string | null
  // Actions
  fetchVoices: () => Promise<void>
  createVoice: (data: {
    name: string
    provider?: string
    sample_url?: string | null
    metadata?: Record<string, unknown>
  }) => Promise<Voice | null>
  deleteVoice: (id: string) => Promise<void>
  startPreview: (id: string) => void
  stopPreview: () => void
  setCloning: (inProgress: boolean) => void
  setCloneError: (err: string | null) => void
  clearError: () => void
}

export const useVoiceStore = create<VoiceState>((set, get) => ({
  voices: [],
  previewingVoiceId: null,
  cloning: false,
  cloneError: null,
  isLoading: false,
  error: null,

  fetchVoices: async () => {
    set({ isLoading: true, error: null })
    try {
      const voices = await api.listVoices()
      set({ voices, isLoading: false })
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message })
    }
  },

  createVoice: async (data) => {
    try {
      const voice = await api.createVoice(data)
      set({ voices: [voice, ...get().voices] })
      return voice
    } catch (e) {
      set({ error: (e as Error).message })
      return null
    }
  },

  deleteVoice: async (id) => {
    await api.deleteVoice(id)
    set({ voices: get().voices.filter((v) => v.id !== id) })
  },

  startPreview: (id) => set({ previewingVoiceId: id }),
  stopPreview: () => set({ previewingVoiceId: null }),

  setCloning: (inProgress) => set({ cloning: inProgress }),
  setCloneError: (err) => set({ cloneError: err }),

  clearError: () => set({ error: null }),
}))

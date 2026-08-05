import { create } from 'zustand'
import type { ServerSettings } from '../types'
import { api } from '../api/client'

interface SettingsState {
  settings: ServerSettings | null
  isLoading: boolean
  error: string | null
  fetchSettings: () => Promise<void>
  clearError: () => void
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  isLoading: false,
  error: null,

  fetchSettings: async () => {
    set({ isLoading: true, error: null })
    try {
      const settings = await api.getSettings()
      set({ settings, isLoading: false })
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message })
    }
  },

  clearError: () => set({ error: null }),
}))

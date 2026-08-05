import { create } from 'zustand'
import type { Clip, ClipVersion, Project, ProjectTree, Track, TrackWithClips } from '../types'
import { api, type EditResult } from '../api/client'

interface StudioState {
  // Data
  projects: Project[]
  currentProject: ProjectTree | null
  selectedClipId: string | null
  // Versions for the currently selected clip (right-pane editor).
  versions: ClipVersion[]
  // Transport
  isPlaying: boolean
  playheadTime: number
  // Loading flags
  isLoadingProjects: boolean
  isLoadingProject: boolean
  isGenerating: boolean
  isEditing: boolean
  isReverting: boolean
  // Last error (for surfacing in UI)
  error: string | null

  // Actions — projects
  fetchProjects: () => Promise<void>
  openProject: (id: string) => Promise<void>
  createProject: (name: string, description?: string) => Promise<Project>
  closeProject: () => void
  deleteProject: (id: string) => Promise<void>

  // Actions — tracks
  addTrack: (name: string, voiceId?: string) => Promise<Track | null>
  updateTrack: (id: string, data: Partial<{ name: string; voice_id: string | null; order: number }>) => Promise<void>
  deleteTrack: (id: string) => Promise<void>
  reorderTracks: (trackIds: string[]) => Promise<void>

  // Actions — clips
  addClip: (trackId: string, text: string, startTime?: number) => Promise<Clip | null>
  updateClip: (id: string, data: Partial<{ text: string; start_time: number; duration: number; track_id: string }>) => Promise<void>
  deleteClip: (id: string) => Promise<void>
  selectClip: (id: string | null) => void
  generateClipAudio: (clipId: string, opts?: { voice_id?: string; speed?: number }) => Promise<Clip | null>
  editClip: (clipId: string, instruction: string) => Promise<EditResult | null>

  // Actions — versions
  fetchClipVersions: (clipId: string) => Promise<void>
  revertClipVersion: (clipId: string, versionIndex: number) => Promise<void>

  // Transport
  play: () => void
  pause: () => void
  stop: () => void
  seek: (time: number) => void

  // Misc
  clearError: () => void
}

export const useStudioStore = create<StudioState>((set, get) => ({
  projects: [],
  currentProject: null,
  selectedClipId: null,
  versions: [],
  isPlaying: false,
  playheadTime: 0,
  isLoadingProjects: false,
  isLoadingProject: false,
  isGenerating: false,
  isEditing: false,
  isReverting: false,
  error: null,

  // -- Projects -----------------------------------------------------------

  fetchProjects: async () => {
    set({ isLoadingProjects: true, error: null })
    try {
      const projects = await api.listProjects()
      set({ projects, isLoadingProjects: false })
    } catch (e) {
      set({ isLoadingProjects: false, error: (e as Error).message })
    }
  },

  openProject: async (id) => {
    set({ isLoadingProject: true, error: null, currentProject: null, selectedClipId: null })
    try {
      const tree = await api.getProject(id)
      set({ currentProject: tree, isLoadingProject: false })
    } catch (e) {
      set({ isLoadingProject: false, error: (e as Error).message })
    }
  },

  createProject: async (name, description) => {
    const project = await api.createProject({ name, description })
    set({ projects: [project, ...get().projects] })
    return project
  },

  closeProject: () => {
    set({ currentProject: null, selectedClipId: null, isPlaying: false, playheadTime: 0 })
  },

  deleteProject: async (id) => {
    await api.deleteProject(id)
    const projects = get().projects.filter((p) => p.id !== id)
    if (get().currentProject?.id === id) {
      set({ currentProject: null, selectedClipId: null })
    }
    set({ projects })
  },

  // -- Tracks -------------------------------------------------------------

  addTrack: async (name, voiceId) => {
    const { currentProject } = get()
    if (!currentProject) return null
    try {
      const track = await api.createTrack(currentProject.id, {
        name,
        voice_id: voiceId,
        order: currentProject.tracks.length,
      })
      const newTrack: TrackWithClips = { ...track, clips: [] }
      set({
        currentProject: {
          ...currentProject,
          tracks: [...currentProject.tracks, newTrack],
        },
      })
      return track
    } catch (e) {
      set({ error: (e as Error).message })
      return null
    }
  },

  updateTrack: async (id, data) => {
    const { currentProject } = get()
    if (!currentProject) return
    const track = await api.updateTrack(id, data)
    set({
      currentProject: {
        ...currentProject,
        tracks: currentProject.tracks.map((t) => (t.id === id ? { ...t, ...track, clips: t.clips } : t)),
      },
    })
  },

  deleteTrack: async (id) => {
    const { currentProject } = get()
    if (!currentProject) return
    await api.deleteTrack(id)
    set({
      currentProject: {
        ...currentProject,
        tracks: currentProject.tracks.filter((t) => t.id !== id),
      },
    })
  },

  reorderTracks: async (trackIds) => {
    const { currentProject } = get()
    if (!currentProject) return
    // Optimistic update: reorder locally, then persist.
    const map = new Map(currentProject.tracks.map((t) => [t.id, t]))
    const reordered = trackIds.map((id, i) => ({ ...(map.get(id) as TrackWithClips), order: i }))
    set({ currentProject: { ...currentProject, tracks: reordered } })
    try {
      await api.reorderTracks(currentProject.id, trackIds)
    } catch (e) {
      set({ error: (e as Error).message })
      // Revert on failure.
      await get().openProject(currentProject.id)
    }
  },

  // -- Clips --------------------------------------------------------------

  addClip: async (trackId, text, startTime = 0) => {
    try {
      const clip = await api.createClip(trackId, { text, start_time: startTime })
      const { currentProject } = get()
      if (currentProject) {
        set({
          currentProject: {
            ...currentProject,
            tracks: currentProject.tracks.map((t) =>
              t.id === trackId ? { ...t, clips: [...t.clips, clip] } : t,
            ),
          },
        })
      }
      return clip
    } catch (e) {
      set({ error: (e as Error).message })
      return null
    }
  },

  updateClip: async (id, data) => {
    const { currentProject } = get()
    if (!currentProject) return

    // Locate the clip's current track so we can detect a cross-track
    // move (drag-and-drop between lanes) and keep the optimistic update
    // consistent: lift the clip out of the source lane, drop it into
    // the target lane with the new start_time.
    const sourceTrack = currentProject.tracks.find((t) =>
      t.clips.some((c) => c.id === id),
    )
    if (!sourceTrack) return
    const existingClip = sourceTrack.clips.find((c) => c.id === id)
    if (!existingClip) return

    const isMove = data.track_id != null && data.track_id !== sourceTrack.id

    if (isMove) {
      const targetTrackId = data.track_id as string
      set({
        currentProject: {
          ...currentProject,
          tracks: currentProject.tracks.map((t) => {
            if (t.id === sourceTrack.id) {
              return { ...t, clips: t.clips.filter((c) => c.id !== id) }
            }
            if (t.id === targetTrackId) {
              return { ...t, clips: [...t.clips, { ...existingClip, ...data }] }
            }
            return t
          }),
        },
      })
    } else {
      set({
        currentProject: {
          ...currentProject,
          tracks: currentProject.tracks.map((t) =>
            t.id === sourceTrack.id
              ? {
                  ...t,
                  clips: t.clips.map((c) => (c.id === id ? { ...c, ...data } : c)),
                }
              : t,
          ),
        },
      })
    }

    try {
      await api.updateClip(id, data)
    } catch (e) {
      set({ error: (e as Error).message })
      await get().openProject(currentProject.id)
    }
  },

  deleteClip: async (id) => {
    const { currentProject } = get()
    if (!currentProject) return
    await api.deleteClip(id)
    set({
      currentProject: {
        ...currentProject,
        tracks: currentProject.tracks.map((t) => ({
          ...t,
          clips: t.clips.filter((c) => c.id !== id),
        })),
      },
      selectedClipId: get().selectedClipId === id ? null : get().selectedClipId,
    })
  },

  selectClip: (id) => set({ selectedClipId: id, versions: [] }),

  generateClipAudio: async (clipId, opts) => {
    set({ isGenerating: true, error: null })
    try {
      const clip = await api.generateClipAudio(clipId, opts ?? {})
      _replaceClip(set, get, clip)
      set({ isGenerating: false })
      // A new version was appended server-side — refresh the list so
      // the right pane shows it immediately. Only when the generated
      // clip is the one currently selected (otherwise the list will
      // be loaded on next selection).
      if (get().selectedClipId === clipId) {
        await get().fetchClipVersions(clipId)
      }
      return clip
    } catch (e) {
      set({ isGenerating: false, error: (e as Error).message })
      return null
    }
  },

  editClip: async (clipId, instruction) => {
    set({ isEditing: true, error: null })
    try {
      const result = await api.editClip(clipId, instruction)
      // If the edit triggered a regeneration, refresh the clip from the response.
      if (result.clip) {
        _replaceClipFields(set, get, clipId, {
          audio_url: result.clip.audio_url,
          status: result.clip.status,
          duration: result.clip.duration,
        })
      }
      // If the edit deleted the clip, remove it from the store.
      if (result.status === 'deleted') {
        const { currentProject } = get()
        if (currentProject) {
          set({
            currentProject: {
              ...currentProject,
              tracks: currentProject.tracks.map((t) => ({
                ...t,
                clips: t.clips.filter((c) => c.id !== clipId),
              })),
            },
            selectedClipId: get().selectedClipId === clipId ? null : get().selectedClipId,
          })
        }
      } else {
        // Refresh from server to pick up text/metadata changes.
        const { currentProject } = get()
        if (currentProject) {
          await get().openProject(currentProject.id)
        }
        // A regeneration appends a new version server-side — refresh
        // the right-pane list so it shows up immediately. Non-regen
        // edits (trim_silence / noop) don't touch versions, but the
        // refresh is cheap and keeps the list honest either way.
        if (result.status === 'regenerated' && get().selectedClipId === clipId) {
          await get().fetchClipVersions(clipId)
        }
      }
      set({ isEditing: false })
      return result
    } catch (e) {
      set({ isEditing: false, error: (e as Error).message })
      return null
    }
  },

  // -- Versions -----------------------------------------------------------

  fetchClipVersions: async (clipId) => {
    try {
      const versions = await api.listClipVersions(clipId)
      set({ versions })
    } catch (e) {
      set({ error: (e as Error).message, versions: [] })
    }
  },

  revertClipVersion: async (clipId, versionIndex) => {
    set({ isReverting: true, error: null })
    try {
      const clip = await api.revertClipVersion(clipId, versionIndex)
      _replaceClip(set, get, clip)
      // The versions list itself doesn't change (revert doesn't append),
      // but the "current" marker moves — refresh to keep the UI honest.
      await get().fetchClipVersions(clipId)
      set({ isReverting: false })
    } catch (e) {
      set({ isReverting: false, error: (e as Error).message })
    }
  },

  // -- Transport ----------------------------------------------------------

  play: () => set({ isPlaying: true }),
  pause: () => set({ isPlaying: false }),
  stop: () => set({ isPlaying: false, playheadTime: 0 }),
  seek: (time) => set({ playheadTime: time }),

  // -- Misc ---------------------------------------------------------------

  clearError: () => set({ error: null }),
}))

// ---------------------------------------------------------------------------
// Internal helpers — mutate a clip in the tree without a full refetch.
// ---------------------------------------------------------------------------

function _replaceClip(
  set: (partial: Partial<StudioState>) => void,
  get: () => StudioState,
  clip: Clip,
) {
  const { currentProject } = get()
  if (!currentProject) return
  set({
    currentProject: {
      ...currentProject,
      tracks: currentProject.tracks.map((t) =>
        t.id === clip.track_id
          ? { ...t, clips: t.clips.map((c) => (c.id === clip.id ? clip : c)) }
          : t,
      ),
    },
  })
}

function _replaceClipFields(
  set: (partial: Partial<StudioState>) => void,
  get: () => StudioState,
  clipId: string,
  fields: Partial<Clip>,
) {
  const { currentProject } = get()
  if (!currentProject) return
  set({
    currentProject: {
      ...currentProject,
      tracks: currentProject.tracks.map((t) => ({
        ...t,
        clips: t.clips.map((c) => (c.id === clipId ? { ...c, ...fields } : c)),
      })),
    },
  })
}

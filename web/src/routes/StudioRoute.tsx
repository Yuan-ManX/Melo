import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Voice } from '../types'
import { useStudioStore } from '../stores/studioStore'
import { ClipEditor } from '../components/studio/ClipEditor'
import { Timeline } from '../components/studio/Timeline'
import { TrackEditor } from '../components/studio/TrackEditor'
import { TransportBar } from '../components/studio/TransportBar'

export function StudioRoute() {
  const {
    projects,
    currentProject,
    selectedClipId,
    isLoadingProjects,
    isLoadingProject,
    error,
    fetchProjects,
    openProject,
    createProject,
    deleteProject,
    closeProject,
    clearError,
  } = useStudioStore()

  const [voices, setVoices] = useState<Voice[]>([])
  const [newProjectName, setNewProjectName] = useState('')

  // Load project list + voice list on mount.
  useEffect(() => {
    fetchProjects()
    api.listVoices().then(setVoices).catch(() => setVoices([]))
  }, [fetchProjects])

  const selectedClip = useMemo(() => {
    if (!currentProject || !selectedClipId) return null
    for (const track of currentProject.tracks) {
      const clip = track.clips.find((c) => c.id === selectedClipId)
      if (clip) return clip
    }
    return null
  }, [currentProject, selectedClipId])

  // Compute total timeline duration = max(end) across all clips.
  const timelineDuration = useMemo(() => {
    if (!currentProject) return 0
    let max = 0
    for (const track of currentProject.tracks) {
      for (const clip of track.clips) {
        const end = clip.start_time + clip.duration
        if (end > max) max = end
      }
    }
    return max
  }, [currentProject])

  const handleCreateProject = async () => {
    if (!newProjectName.trim()) return
    const project = await createProject(newProjectName.trim())
    setNewProjectName('')
    await openProject(project.id)
  }

  return (
    <div className="flex h-full">
      {/* Left pane — project list */}
      <aside className="flex w-64 flex-col border-r border-[var(--border)] bg-[var(--bg-soft)]/40">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-semibold text-[var(--fg)]">项目</h2>
        </div>
        <div className="flex gap-2 px-3 py-2">
          <input
            type="text"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateProject()}
            placeholder="新项目名称…"
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-[var(--fg)] placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
          />
          <button
            type="button"
            onClick={handleCreateProject}
            disabled={!newProjectName.trim()}
            className="rounded-lg px-3 py-1.5 text-xs font-bold text-white transition hover:scale-105 disabled:opacity-40 disabled:hover:scale-100"
            style={{ background: 'linear-gradient(135deg, var(--accent), var(--c-blue))' }}
          >
            +
          </button>
        </div>
        <div className="flex-1 overflow-auto px-2">
          {isLoadingProjects && projects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-[var(--muted)]">加载中…</div>
          ) : projects.length === 0 ? (
            <div className="px-3 py-3 text-xs text-[var(--muted)]">
              还没有项目，在上方新建一个开始吧 ♪
            </div>
          ) : (
            projects.map((project) => {
              const isActive = currentProject?.id === project.id
              return (
                <div
                  key={project.id}
                  className={`group flex items-center justify-between rounded-xl px-3 py-2 text-sm transition-all ${
                    isActive
                      ? 'bg-[var(--accent)]/15 text-[var(--accent-2)]'
                      : 'text-[var(--muted)] hover:bg-[var(--card)] hover:text-[var(--fg)]'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => openProject(project.id)}
                    className="flex-1 truncate text-left"
                    title={project.description ?? project.name}
                  >
                    {project.name}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm(`删除项目「${project.name}」吗？`)) {
                        deleteProject(project.id)
                      }
                    }}
                    className="ml-2 hidden rounded-full px-1.5 text-xs text-[var(--muted)] hover:bg-red-500/15 hover:text-red-400 group-hover:block"
                    title="删除项目"
                  >
                    ×
                  </button>
                </div>
              )
            })
          )}
        </div>
      </aside>

      {/* Center pane — timeline */}
      <main className="flex flex-1 flex-col">
        {error && (
          <div className="flex items-center justify-between border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-300">
            <span>{error}</span>
            <button type="button" onClick={clearError} className="rounded-full px-2 font-mono hover:bg-red-500/20">
              ×
            </button>
          </div>
        )}

        {!currentProject ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-[var(--muted)]">
            <div
              className="flex h-16 w-16 items-center justify-center rounded-2xl text-2xl font-bold text-white"
              style={{
                background: 'linear-gradient(135deg, var(--c-blue), var(--accent))',
                boxShadow: 'var(--shadow-glow)',
              }}
            >
              ♪
            </div>
            {isLoadingProject ? '加载中…' : '选择或新建一个项目开始吧'}
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <div className="min-w-0 flex-1">
                <h1 className="truncate text-base font-semibold text-[var(--fg)]">
                  {currentProject.name}
                </h1>
                {currentProject.description && (
                  <div className="truncate text-xs text-[var(--muted)]">
                    {currentProject.description}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={closeProject}
                className="ml-3 rounded-full border border-[var(--border)] px-3 py-1 text-xs text-[var(--muted)] transition hover:bg-[var(--card)] hover:text-[var(--fg)]"
              >
                关闭
              </button>
            </div>

            <TransportBar duration={timelineDuration} />

            <div className="flex-1 overflow-auto">
              <Timeline tracks={currentProject.tracks} duration={timelineDuration} />
            </div>

            {/* Bottom pane — track management */}
            <div className="border-t border-[var(--border)] px-4 py-3">
              <h3 className="mb-2 text-xs font-semibold tracking-wider text-[var(--muted)]">
                音轨
              </h3>
              <TrackEditor tracks={currentProject.tracks} voices={voices} />
            </div>
          </>
        )}
      </main>

      {/* Right pane — clip editor */}
      <aside className="flex w-80 flex-col border-l border-[var(--border)] bg-[var(--bg-soft)]/40">
        <div className="border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-sm font-semibold text-[var(--fg)]">片段</h2>
        </div>
        <div className="flex-1 overflow-auto px-4 py-3">
          <ClipEditor clip={selectedClip} />
        </div>
      </aside>
    </div>
  )
}

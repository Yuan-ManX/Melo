/**
 * summarizeToolResult — build a short human-readable summary from a tool
 * result payload. Falls back to an empty string when no recognizable
 * fields are present.
 */
export function summarizeToolResult(result: unknown): string {
  if (result == null || typeof result !== 'object') return ''
  const r = result as Record<string, unknown>
  const candidates = ['name', 'message', 'text', 'id', 'status', 'applied']
  for (const key of candidates) {
    const val = r[key]
    if (typeof val === 'string' && val) return val
  }
  return ''
}
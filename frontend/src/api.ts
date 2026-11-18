import type { ActionResult, BenchRow, GameState, Hint, PuzzleMeta, Verdict } from './types'

const BASE = (import.meta.env.VITE_API as string | undefined) ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export async function ping(): Promise<boolean> {
  try {
    return (await fetch(BASE + '/api/health')).ok
  } catch {
    return false
  }
}

export const puzzles = () => request<PuzzleMeta[]>('/api/puzzles')
export const loadPuzzle = (puzzle_id?: string, puzzle?: unknown) =>
  post<GameState>('/api/game/load', { puzzle_id, puzzle })
export const restart = () => post<GameState>('/api/game/restart')
export const verdict = (name: string, value: Verdict) =>
  post<ActionResult>('/api/game/verdict', { name, verdict: value })
export const hint = () => request<Hint>('/api/game/hint')
export const autoStep = () => post<ActionResult & { ok: boolean; status?: string }>('/api/game/step')
export const autoSolve = () => post<{ solved: boolean; status: string; steps: unknown[]; state: GameState }>('/api/game/auto')
export const uniqueness = (puzzle_id?: string) =>
  request<{ unique: boolean; reason?: string; forced_characters?: number; sat_calls: number; time_ms: number }>(
    `/api/uniqueness${puzzle_id ? `?puzzle_id=${encodeURIComponent(puzzle_id)}` : ''}`,
  )
export const benchmark = (ids: string[]) => post<{ results: BenchRow[] }>('/api/benchmark', { puzzle_ids: ids })

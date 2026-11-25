export type Verdict = 'CRIMINAL' | 'INNOCENT'
export type Status = Verdict | null

export interface PuzzleMeta {
  id: string
  name: string
  group: string
  size: number
  desc: string
  characters: number
  clues: number
}

export interface CharacterView {
  cell: string
  name: string
  job: string
  status: Status
  revealed: boolean
}

export interface ClueView {
  id: string
  owner: string
  type: string
  text: string
  cells: string[]
}

export interface Analysis {
  kb: { primary_variables: number; auxiliary_variables: number; variables: number; clauses: number }
  sat_calls: number
  decisions: number
  propagations: number
  backtracks: number
  runtime_ms: number
  revealed_clues: number
  proved: number
  last_queries: { assumption: number[]; sat: boolean; decisions: number; propagations: number; backtracks: number; time_ms: number; clue_ids: string[]; timeout?: boolean }[]
  timeouts?: number
}

export interface TraceEntry {
  action: string
  step?: number
  character?: string
  verdict?: string
  result?: string
  classification?: string
  clue_id?: string
  revealed_clue?: string
  active_clues?: string[]
  sat_queries?: number
  queries?: { assumption: number[]; sat: boolean; clue_ids: string[]; timeout?: boolean }[]
  timeout?: boolean
}

export interface GameState {
  puzzle: { id: string; name: string; group: string; size: number; desc: string }
  characters: CharacterView[]
  clues: ClueView[]
  steps: number
  solved: boolean
  history: { step: number; name: string; verdict: string; clue_id: string }[]
  total: number
  analysis: Analysis
  trace: TraceEntry[]
}

export interface ActionResult {
  result: string
  classification?: string
  clue_id?: string
  status?: string
  state: GameState
}

export interface Hint {
  available: boolean
  status?: string
  name?: string
  verdict?: Verdict
  clue_id?: string
  cell?: string
  state: GameState
}

export interface BenchRow {
  puzzle_id: string
  size: number
  solved: boolean
  status: string
  steps: number
  primary_variables: number
  auxiliary_variables: number
  clauses: number
  sat_calls: number
  decisions: number
  propagations: number
  backtracks: number
  runtime_ms: number
  unique: boolean
  uniqueness_ms: number
  timeout_ms?: number | null
  timed_out?: boolean
  failure?: string | null
}

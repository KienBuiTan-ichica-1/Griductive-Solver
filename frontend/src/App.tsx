import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { BarChart } from './components/Charts'
import * as api from './api'
import type { ActionResult, BenchRow, GameState, PuzzleMeta, TraceEntry, Verdict } from './types'

const GROUPS: Record<string, string> = { '3x3': '3 × 3', '4x4': '4 × 4', '5x5': '5 × 5', custom: 'Tự nạp' }
const LABEL: Record<string, string> = {
  ACCEPTED: 'Đã chứng minh — thẻ lật, clue mới được thêm vào KB.',
  NOT_PROVABLE: 'NOT_PROVABLE — KB hiện tại chưa bắt buộc verdict này.',
  CONTRADICTED: 'CONTRADICTED — KB hiện tại bắt buộc verdict ngược lại.',
  ALREADY_KNOWN: 'Người này đã được xác định từ trước.',
  INCONSISTENT: 'INCONSISTENT — knowledge base mâu thuẫn.',
  INVALID: 'Yêu cầu không hợp lệ.',
  SOLVED: 'Đã giải xong — mọi verdict đều được chứng minh.',
  STUCK: 'STUCK — không còn character nào bị bắt buộc.',
}
const COLORS = { clauses: '#4fe3ff', calls: '#c084fc', steps: '#ffb54a', ms: '#37ffa0' }
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const letters = (n: number) => Array.from({ length: n }, (_, i) => String.fromCharCode(65 + i))

type Feedback = { text: string; kind: string } | null
type SuggestedHint = { name: string; verdict: Verdict } | null

export default function App() {
  const [puzzleList, setPuzzleList] = useState<PuzzleMeta[]>([])
  const [state, setState] = useState<GameState | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedClue, setSelectedClue] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [suggested, setSuggested] = useState<SuggestedHint>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [tab, setTab] = useState<'agent' | 'bench'>('agent')
  const [bench, setBench] = useState<BenchRow[]>([])
  const [benchBusy, setBenchBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [autoRunning, setAutoRunning] = useState(false)
  const [showPanels, setShowPanels] = useState(true)
  const [err, setErr] = useState('')
  const stopRef = useRef(false)

  const load = useCallback(async (id: string) => {
    setState(await api.loadPuzzle(id))
    setSelected(null); setSelectedClue(null); setSuggested(null)
    setFeedback(null); setBench([])
  }, [])

  useEffect(() => {
    let alive = true
    const boot = async () => {
      const ok = await api.ping()
      if (!alive) return
      setOnline(ok)
      const list = await api.puzzles()
      if (!alive) return
      setPuzzleList(list)
      if (list.length) await load(list[0].id)
    }
    void boot().catch((e: Error) => setErr(`Không nạp được puzzle: ${e.message}`))
    const timer = setInterval(() => void api.ping().then(setOnline), 8000)
    return () => { alive = false; clearInterval(timer) }
  }, [load])

  const applyResult = (result: string, next: GameState, extra?: string) => {
    setState(next)
    const text = LABEL[result] ?? result
    setFeedback({ text: extra ?? text, kind: result.toLowerCase() })
    if (next.solved && result !== 'STUCK') {
      setFeedback({ text: LABEL.SOLVED, kind: 'accepted' })
    }
  }

  const submitVerdict = async (value: Verdict, targetName = selected) => {
    if (!targetName || !state || busy || autoRunning || state.solved) return
    setBusy(true); setErr('')
    try {
      const r = await api.verdict(targetName, value)
      applyResult(r.result, r.state)
      if (r.result === 'ACCEPTED' && r.clue_id) setSelectedClue(r.clue_id)
      setSuggested(null)
    } catch (e) {
      setErr(`Lỗi backend: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const getHint = async () => {
    if (busy || autoRunning) return
    setBusy(true); setErr('')
    try {
      const h = await api.hint()
      setState(h.state)
      if (h.available && h.name && h.verdict) {
        setSelected(h.name)
        setSuggested({ name: h.name, verdict: h.verdict })
        setSelectedClue(h.clue_id ?? null)
        setFeedback({
          text: `Gợi ý: ${h.name} là ${h.verdict}${h.clue_id ? ` — clue ${h.clue_id} hỗ trợ suy luận này` : ''}.`,
          kind: 'hint',
        })
      } else {
        setSuggested(null)
        setFeedback({ text: LABEL[h.status ?? 'STUCK'] ?? 'Không có gợi ý.', kind: 'hint' })
      }
    } catch (e) {
      setErr(`Lỗi backend: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const restart = async () => {
    if (autoRunning) stopRef.current = true
    try {
      const next = await api.restart()
      setState(next); setSelected(null); setSelectedClue(null); setSuggested(null); setFeedback(null)
    } catch (e) {
      setErr(`Lỗi backend: ${(e as Error).message}`)
    }
  }

  const stepOnce = async () => {
    setSuggested(null)
    const r = await api.autoStep()
    applyResult(r.result ?? r.status ?? 'STUCK', r.state)
    if (r.state.solved) return false
    return r.ok
  }

  const runAutoSolve = async () => {
    if (autoRunning || !state || state.solved) return
    stopRef.current = false
    setSuggested(null)
    setAutoRunning(true); setErr('')
    try {
      while (!stopRef.current) {
        const keepGoing = await stepOnce()
        if (!keepGoing) break
        await sleep(320)
      }
    } catch (e) {
      setErr(`Lỗi backend: ${(e as Error).message}`)
    } finally {
      setAutoRunning(false)
    }
  }

  const importFile = async (file?: File) => {
    if (!file) return
    try {
      const data = JSON.parse(await file.text()) as Record<string, unknown>
      const next = await api.loadPuzzle(undefined, data)
      setState(next)
      setSelected(null); setSelectedClue(null); setSuggested(null); setFeedback(null)
      const meta: PuzzleMeta = {
        id: String(data.id ?? 'custom'), name: String(data.name ?? file.name),
        group: 'custom', size: Number(data.size ?? 3), desc: String(data.desc ?? ''),
        characters: Array.isArray(data.characters) ? data.characters.length : 0,
        clues: Array.isArray(data.clues) ? data.clues.length : 0,
      }
      setPuzzleList((p) => [...p.filter((x) => x.id !== meta.id), meta])
    } catch (e) {
      setErr(`File puzzle không hợp lệ: ${(e as Error).message}`)
    }
  }

  const runBench = async () => {
    setBenchBusy(true); setErr('')
    try {
      const out = await api.benchmark(puzzleList.map((p) => p.id))
      setBench(out.results)
    } catch (e) {
      setErr(`Không chạy được benchmark: ${(e as Error).message}`)
    } finally {
      setBenchBusy(false)
    }
  }

  const exportCsv = () => {
    const head = 'puzzle,size,solved,steps,primary,aux,clauses,sat_calls,decisions,propagations,backtracks,ms,unique'
    const rows = bench.map((r) => [r.puzzle_id, r.size, r.solved, r.steps, r.primary_variables,
      r.auxiliary_variables, r.clauses, r.sat_calls, r.decisions, r.propagations,
      r.backtracks, r.runtime_ms.toFixed(2), r.unique].join(','))
    const url = URL.createObjectURL(new Blob([[head, ...rows].join('\n')], { type: 'text/csv' }))
    const a = document.createElement('a'); a.href = url; a.download = 'benchmark.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  const size = state?.puzzle.size ?? 3
  const cols = letters(size)
  const rows = Array.from({ length: size }, (_, i) => i + 1)
  const byCell = new Map((state?.characters ?? []).map((c) => [c.cell, c]))
  const cluesByOwner = new Map((state?.clues ?? []).map((c) => [c.owner, c]))
  const highlighted = new Set(state?.clues.find((c) => c.id === selectedClue)?.cells ?? [])
  const selChar = state?.characters.find((c) => c.name === selected)
  const selClue = state?.clues.find((c) => c.id === selectedClue)
  const proved = state?.characters.filter((c) => c.status).length ?? 0
  const groups = [...new Set(puzzleList.map((p) => p.group))]
  const benchIds = [...new Set(bench.map((r) => r.puzzle_id))]
  const pick = (g: string, key: keyof BenchRow): number | null => {
    const value = bench.find((r) => r.puzzle_id === g)?.[key]
    return typeof value === 'number' ? value : null
  }
  const series = [
    { id: 'clauses', key: 'clauses' as const, label: 'Clauses', color: COLORS.clauses },
    { id: 'calls', key: 'sat_calls' as const, label: 'SAT calls', color: COLORS.calls },
    { id: 'steps', key: 'steps' as const, label: 'Steps', color: COLORS.steps },
    { id: 'ms', key: 'runtime_ms' as const, label: 'ms', color: COLORS.ms },
  ]
  const cardMin = size >= 5 ? 112 : size === 4 ? 128 : 150

  return (
    <div className={`app ${showPanels ? '' : 'nopanels'}`}>
      <header className="hud">
        <div className="brand">Grid<span>uctive</span></div>
        <div className="title">
          <h1>{state?.puzzle.name ?? 'Griductive Solver'}</h1>
          <span>{GROUPS[state?.puzzle.group ?? ''] ?? state?.puzzle.group ?? 'Đang nạp…'}</span>
        </div>
        <div className="stats">
          <div className="stat"><small>Bước</small><b>{state?.steps ?? 0}</b></div>
          <div className="stat"><small>Đã chứng minh</small><b>{proved}/{state?.total ?? 0}</b></div>
          <div className={`badge ${online ? 'on' : 'off'}`}>
            {online === null ? 'Đang kiểm tra' : online ? 'Backend đã kết nối' : 'Backend chưa chạy'}
          </div>
          <button className="btn hudbtn" onClick={() => setShowPanels((v) => !v)}>
            {showPanels ? 'Ẩn bảng' : 'Hiện bảng'}
          </button>
        </div>
      </header>

      <main className="board">
        {state && (
          <div className="grid" style={{
            gridTemplateColumns: `32px repeat(${size}, minmax(${cardMin}px, 1fr))`,
          }}>
            <div className="corner">⌗</div>
            {cols.map((c) => <div className="colhead" key={c}>{c}</div>)}
            {rows.map((r) => (
              <Fragment key={r}>
                <div className="rowhead">{r}</div>
                {cols.map((_, c) => {
                  const cell = `${cols[c]}${r}`
                  const ch = byCell.get(cell)
                  if (!ch) return <div className="empty" key={cell} />
                  const clue = cluesByOwner.get(ch.name)
                  return (
                    <button
                      key={cell}
                      className={`card ${ch.status ? ch.status.toLowerCase() : 'unknown'} ${ch.revealed ? 'up' : 'down'} ${selected === ch.name ? 'sel' : ''} ${highlighted.has(cell) ? 'hl' : ''}`}
                      onClick={() => { setSelected(ch.name); setSelectedClue(clue?.id ?? null); setSuggested(null) }}
                    >
                      <span className="card-head"><b>{cell}</b><span className={`pip ${ch.status ? ch.status.toLowerCase() : ''}`} /></span>
                      <span className="name">{ch.name}</span>
                      <span className="job">{ch.job}</span>
                      <span className="clue">{clue ? clue.text : '••• thẻ úp •••'}</span>
                      <span className="card-status">{ch.status ?? 'UNKNOWN'}</span>
                    </button>
                  )
                })}
              </Fragment>
            ))}
          </div>
        )}
        {feedback && <div className={`feedback ${feedback.kind}`}>{feedback.text}</div>}
        {suggested && !state?.solved && (
          <div className="suggest">
            Gợi ý đang chọn: <b>{suggested.name} = {suggested.verdict}</b>
            <button className="btn primary" disabled={busy || autoRunning} onClick={() => void submitVerdict(suggested.verdict, suggested.name)}>Áp dụng gợi ý</button>
          </div>
        )}
      </main>

      {showPanels && <aside className="panel left" aria-label="Điều khiển">
        <h2>Điều khiển</h2>
        <div className="row">
          <button className="btn primary" disabled={busy || autoRunning} onClick={() => void getHint()}>Hint</button>
          <button className="btn" disabled={busy || autoRunning || state?.solved} onClick={() => void stepOnce().catch((e: Error) => setErr(e.message))}>Auto Step</button>
          {autoRunning
            ? <button className="btn" onClick={() => { stopRef.current = true }}>Dừng</button>
            : <button className="btn" disabled={busy || state?.solved} onClick={() => void runAutoSolve()}>Auto Solve</button>}
        </div>
        <div className="row">
          <button className="btn" disabled={autoRunning} onClick={() => void restart()}>Restart</button>
          <button className="btn" disabled={autoRunning || !puzzleList.length} onClick={() => void load(puzzleList[Math.floor(Math.random() * puzzleList.length)].id)}>Puzzle khác</button>
        </div>

        <h2>Chọn verdict</h2>
        {selChar ? (
          <>
            <p className="desc"><b>{selChar.name}</b> · {selChar.cell} · {selChar.job}</p>
            <div className="row">
              <button className="btn crimson" disabled={!!selChar.status || busy || state?.solved} onClick={() => void submitVerdict('CRIMINAL')}>CRIMINAL</button>
              <button className="btn mint" disabled={!!selChar.status || busy || state?.solved} onClick={() => void submitVerdict('INNOCENT')}>INNOCENT</button>
            </div>
          </>
        ) : <p className="desc">Chọn một thẻ trên bàn để xét verdict.</p>}

        {groups.map((g) => (
          <section key={g}>
            <h2>{GROUPS[g] ?? g}</h2>
            {puzzleList.filter((p) => p.group === g).map((p) => (
              <button key={p.id} className={`lv ${p.id === state?.puzzle.id ? 'sel' : ''}`}
                disabled={autoRunning} onClick={() => void load(p.id)}>
                <b>{p.id} · {p.name}</b>
                <small>{p.characters} người · {p.clues} clue</small>
              </button>
            ))}
          </section>
        ))}

        <h2>Nạp puzzle từ file</h2>
        <input type="file" accept=".json" disabled={autoRunning} onChange={(e) => {
          const f = e.target.files?.[0]; e.target.value = ''
          void importFile(f)
        }} />
        <h2>Chú giải</h2>
        <div className="legend">
          <span><i className="sw crimson" /> Criminal</span>
          <span><i className="sw mint" /> Innocent</span>
          <span><i className="sw unknown" /> Chưa biết</span>
        </div>
        {state?.puzzle.desc && <p className="desc">{state.puzzle.desc}</p>}
      </aside>}

      {showPanels && <aside className="panel right" aria-label="Logic agent">
        <div className="tabs" role="tablist">
          <button role="tab" className={`tab ${tab === 'agent' ? 'sel' : ''}`} onClick={() => setTab('agent')}>Logic Agent</button>
          <button role="tab" className={`tab ${tab === 'bench' ? 'sel' : ''}`} onClick={() => setTab('bench')}>Thực nghiệm</button>
        </div>

        {tab === 'agent' && state && (
          <>
            <h2>Knowledge base KB_t</h2>
            <table>
              <tbody>
                <tr><td>Biến chính</td><td>{state.analysis.kb.primary_variables}</td></tr>
                <tr><td>Biến phụ</td><td>{state.analysis.kb.auxiliary_variables}</td></tr>
                <tr><td>Clause</td><td>{state.analysis.kb.clauses}</td></tr>
                <tr><td>SAT calls</td><td>{state.analysis.sat_calls}</td></tr>
                <tr><td>Decisions</td><td>{state.analysis.decisions}</td></tr>
                <tr><td>Propagations</td><td>{state.analysis.propagations}</td></tr>
                <tr><td>Backtracks</td><td>{state.analysis.backtracks}</td></tr>
                <tr><td>Runtime</td><td>{state.analysis.runtime_ms.toFixed(2)} ms</td></tr>
              </tbody>
            </table>

            <h2>Clue đã lật ({state.clues.length})</h2>
            <div className="clues">
              {state.clues.map((c) => (
                <button key={c.id} className={`clue ${selectedClue === c.id ? 'sel' : ''}`}
                  onClick={() => { setSelectedClue(c.id); setSelected(c.owner); setSuggested(null) }}>
                  <b>{c.id} · {c.owner}</b><span>{c.text}</span>
                </button>
              ))}
            </div>
            {selClue && <p className="desc">Ô được highlight: {selClue.cells.join(', ')}</p>}

            <h2>Vết suy luận</h2>
            <div className="trace">
              {state.trace.length === 0 && <p className="desc">Chưa có bước nào.</p>}
              {[...state.trace].reverse().map((t: TraceEntry, i) => (
                <div key={i} className={`trace-item ${String(t.result ?? '').toLowerCase()}`}>
                  <b>#{t.step ?? 0} {t.character ?? t.action}</b> · {t.verdict ?? ''} · {t.result ?? ''}
                  {t.revealed_clue ? ` · clue ${t.revealed_clue}` : ''}
                  <span className="muted"> · active: {(t.active_clues ?? []).join(',') || '—'} · SAT {t.sat_queries ?? 0}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'bench' && (
          <>
            <div className="row">
              <button className="btn primary" disabled={benchBusy || !puzzleList.length} onClick={() => void runBench()}>
                {benchBusy ? 'Đang chạy…' : 'Chạy trên mọi puzzle'}
              </button>
              <button className="btn" disabled={!bench.length} onClick={exportCsv}>Tải CSV</button>
            </div>
            {bench.length > 0 && (
              <>
                <div className="legend">{series.map((s) => <span key={s.id}><i className="dot" style={{ background: s.color }} />{s.label}</span>)}</div>
                <BarChart title="Số clause CNF" unit="clause" groups={benchIds} series={[series[0]]}
                  value={(g, s) => pick(g, series.find((x) => x.id === s)!.key)} />
                <BarChart title="Số SAT calls" unit="lần" groups={benchIds} series={[series[1]]}
                  value={(g, s) => pick(g, series.find((x) => x.id === s)!.key)} />
                <BarChart title="Số bước suy luận" unit="bước" groups={benchIds} series={[series[2]]}
                  value={(g, s) => pick(g, series.find((x) => x.id === s)!.key)} />
                <BarChart title="Thời gian" unit="ms" groups={benchIds} series={[series[3]]}
                  value={(g, s) => pick(g, series.find((x) => x.id === s)!.key)} />
                <table>
                  <thead><tr><th>Puzzle</th><th>Solved</th><th>Unique</th><th>Steps</th><th>ms</th></tr></thead>
                  <tbody>{bench.map((r) => <tr key={r.puzzle_id}>
                    <td>{r.puzzle_id}</td><td>{String(r.solved)}</td><td>{String(r.unique)}</td>
                    <td>{r.steps}</td><td>{r.runtime_ms.toFixed(2)}</td>
                  </tr>)}</tbody>
                </table>
              </>
            )}
          </>
        )}
        {err && <p className="err" role="alert">{err}</p>}
      </aside>}

      <footer className="hint">
        <span>Chọn thẻ → bấm <kbd>CRIMINAL</kbd> hoặc <kbd>INNOCENT</kbd></span>
        <span>Chỉ verdict được <b>bắt buộc logic</b> mới được chấp nhận</span>
        <span>Bấm clue đã lật để highlight các ô liên quan</span>
        <span><kbd>Hint</kbd> / <kbd>Auto Solve</kbd> dùng chung Logic Agent</span>
      </footer>

      {state?.solved && (
        <div className="overlay win"><div>
          <h2>Hoàn thành</h2>
          <p>{state.steps} bước · {state.total} verdict đều được chứng minh</p>
          <div className="row">
            <button className="btn" onClick={() => void restart()}>Chơi lại</button>
            <button className="btn primary" disabled={!puzzleList.length} onClick={() => void load(puzzleList[Math.floor(Math.random() * puzzleList.length)].id)}>Puzzle khác</button>
          </div>
        </div></div>
      )}
    </div>
  )
}

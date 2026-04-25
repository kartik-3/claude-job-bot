import { useState, useEffect } from 'react'

const STATUSES = [
  'new', 'evaluated', 'should_apply', 'should_not_apply',
  'tailored', 'applied', 'needs_manual', 'blocked', 'error',
]

export default function App() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ search: '', status: '', company: '', ats: '' })
  const [toast, setToast] = useState(null)

  useEffect(() => {
    fetch('/api/jobs/')
      .then(r => r.json())
      .then(data => { setJobs(data); setLoading(false) })
  }, [])

  const filtered = jobs.filter(j => {
    if (filters.status && j.status !== filters.status) return false
    if (filters.company && j.company !== filters.company) return false
    if (filters.ats && j.ats !== filters.ats) return false
    if (filters.search) {
      const q = filters.search.toLowerCase()
      if (!j.company.toLowerCase().includes(q) && !j.title.toLowerCase().includes(q)) return false
    }
    return true
  })

  const companies = [...new Set(jobs.map(j => j.company))].sort()
  const atsList = [...new Set(jobs.map(j => j.ats))].sort()
  const statusList = [...new Set(jobs.map(j => j.status))].sort()

  async function updateStatus(id, newStatus) {
    const prev = jobs.find(j => j.id === id)?.status
    setJobs(js => js.map(j => j.id === id ? { ...j, status: newStatus } : j))
    try {
      const res = await fetch(`/api/jobs/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (!res.ok) throw new Error()
      showToast(`Updated to ${newStatus}`)
    } catch {
      setJobs(js => js.map(j => j.id === id ? { ...j, status: prev } : j))
      showToast('Update failed', true)
    }
  }

  let toastTimer
  function showToast(msg, error = false) {
    setToast({ msg, error })
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => setToast(null), 2200)
  }

  const counts = {}
  filtered.forEach(j => { counts[j.status] = (counts[j.status] || 0) + 1 })

  return (
    <div className="app">
      <header>
        <h1>Job Bot</h1>
        <div className="stats">
          {['should_apply', 'tailored', 'applied', 'needs_manual'].map(s => (
            <div key={s} className="stat">
              {s.replace(/_/g, ' ')}: <strong>{counts[s] || 0}</strong>
            </div>
          ))}
          <div className="stat total">total: <strong>{filtered.length}</strong></div>
        </div>
      </header>

      <div className="filters">
        <input
          placeholder="Search company or title…"
          value={filters.search}
          onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
        />
        <select value={filters.status} onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}>
          <option value="">All statuses</option>
          {statusList.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filters.company} onChange={e => setFilters(f => ({ ...f, company: e.target.value }))}>
          <option value="">All companies</option>
          {companies.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filters.ats} onChange={e => setFilters(f => ({ ...f, ats: e.target.value }))}>
          <option value="">All ATS</option>
          {atsList.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <button className="clear-btn" onClick={() => setFilters({ search: '', status: '', company: '', ats: '' })}>
          Clear
        </button>
      </div>

      {loading ? (
        <div className="loading">Loading jobs…</div>
      ) : filtered.length === 0 ? (
        <div className="loading">No jobs match the current filters.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Score</th>
                <th>Status</th>
                <th>Company</th>
                <th>Title</th>
                <th>ATS</th>
                <th>Location</th>
                <th>Posted</th>
                <th>Links</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(job => (
                <tr key={job.id}>
                  <td><ScoreBadge score={job.fit_score} /></td>
                  <td>
                    <select
                      className={`status-sel s-${job.status}`}
                      value={job.status}
                      onChange={e => updateStatus(job.id, e.target.value)}
                    >
                      {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td className="col-company">{job.company}</td>
                  <td className="col-title">{job.title}</td>
                  <td>{job.ats}</td>
                  <td className="col-location">
                    {job.location || ''}
                    {job.remote ? <span className="remote-badge">Remote</span> : null}
                  </td>
                  <td className="col-date">{job.posted_at ? job.posted_at.slice(0, 10) : '—'}</td>
                  <td>
                    <div className="link-group">
                      {job.url && <a href={job.url} target="_blank" rel="noreferrer">View</a>}
                      {job.apply_url && <a href={job.apply_url} target="_blank" rel="noreferrer">Apply</a>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {toast && <div className={`toast${toast.error ? ' toast-error' : ''}`}>{toast.msg}</div>}
    </div>
  )
}

function ScoreBadge({ score }) {
  if (score == null) return <span className="score score-none">—</span>
  const cls = score >= 75 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low'
  return <span className={`score ${cls}`}>{score}</span>
}

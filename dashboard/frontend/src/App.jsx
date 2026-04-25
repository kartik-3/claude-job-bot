import { useState, useEffect, useMemo, useCallback } from 'react'
import logo from './../public/logo.png';

const STATUSES = [
  'new', 'evaluated', 'should_apply', 'should_not_apply',
  'tailored', 'applied', 'needs_manual', 'blocked', 'error',
]
const PAGE_SIZE = 50

export default function App() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [colFilters, setColFilters] = useState({ title: '', company: '', status: '', ats: '', location: '' })
  const [sort, setSort] = useState({ col: 'fit_score', dir: 'desc' })
  const [page, setPage] = useState(0)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    fetch('/api/jobs/')
      .then(r => r.json())
      .then(data => { setJobs(data); setLoading(false) })
  }, [])

  const companies = useMemo(() => [...new Set(jobs.map(j => j.company))].sort(), [jobs])
  const atsList   = useMemo(() => [...new Set(jobs.map(j => j.ats))].sort(), [jobs])
  const statusList = useMemo(() => [...new Set(jobs.map(j => j.status))].sort(), [jobs])

  const filtered = useMemo(() => {
    const { title, company, status, ats, location } = colFilters
    return jobs.filter(j => {
      if (status   && j.status  !== status)  return false
      if (company  && j.company !== company) return false
      if (ats      && j.ats     !== ats)     return false
      if (title    && !j.title.toLowerCase().includes(title.toLowerCase()))       return false
      if (location && !(j.location || '').toLowerCase().includes(location.toLowerCase())) return false
      return true
    })
  }, [jobs, colFilters])

  const sorted = useMemo(() => {
    const { col, dir } = sort
    return [...filtered].sort((a, b) => {
      let av = a[col], bv = b[col]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') { av = av.toLowerCase(); bv = bv.toLowerCase() }
      if (av < bv) return dir === 'asc' ? -1 : 1
      if (av > bv) return dir === 'asc' ? 1 : -1
      return 0
    })
  }, [filtered, sort])

  const pageCount   = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const paginated   = useMemo(
    () => sorted.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [sorted, currentPage],
  )

  // Reset to first page whenever filters or sort change
  useEffect(() => setPage(0), [colFilters, sort])

  const toggleSort = useCallback(col => {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'desc' })
  }, [])

  const setColFilter = useCallback((key, val) => {
    setColFilters(f => ({ ...f, [key]: val }))
  }, [])

  const clearFilters = useCallback(() => {
    setColFilters({ title: '', company: '', status: '', ats: '', location: '' })
  }, [])

  const updateStatus = useCallback(async (id, newStatus) => {
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
  }, [jobs])

  const counts = useMemo(() => {
    const c = {}
    filtered.forEach(j => { c[j.status] = (c[j.status] || 0) + 1 })
    return c
  }, [filtered])

  const hasFilters = Object.values(colFilters).some(Boolean)

  let toastTimer
  function showToast(msg, error = false) {
    setToast({ msg, error })
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => setToast(null), 2200)
  }

  return (
    <div className="app">
      <header>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <img src={logo} alt="Logo" style={{ width: '40px', marginRight: '10px' }} />
          <h1>Job Bot</h1>
        </div>
        <div className="stats">
          {['should_apply', 'tailored', 'applied', 'needs_manual'].map(s => (
            <div key={s} className="stat">{s.replace(/_/g, ' ')}: <strong>{counts[s] || 0}</strong></div>
          ))}
          <div className="stat total">showing: <strong>{filtered.length}</strong></div>
          {hasFilters && <button className="clear-btn" onClick={clearFilters}>✕ clear filters</button>}
        </div>
      </header>

      {loading ? (
        <div className="loading">Loading jobs…</div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <ColHeader label="Score"    col="fit_score" sort={sort} onSort={toggleSort} />
                  <ColHeader label="Status"   col="status"    sort={sort} onSort={toggleSort}
                    filterValue={colFilters.status}   onFilter={v => setColFilter('status', v)}
                    filterType="select" options={statusList} />
                  <ColHeader label="Company"  col="company"   sort={sort} onSort={toggleSort}
                    filterValue={colFilters.company}  onFilter={v => setColFilter('company', v)}
                    filterType="select" options={companies} />
                  <ColHeader label="Title"    col="title"     sort={sort} onSort={toggleSort}
                    filterValue={colFilters.title}    onFilter={v => setColFilter('title', v)}
                    filterType="text" />
                  <ColHeader label="ATS"      col="ats"       sort={sort} onSort={toggleSort}
                    filterValue={colFilters.ats}      onFilter={v => setColFilter('ats', v)}
                    filterType="select" options={atsList} />
                  <ColHeader label="Location" col="location"  sort={sort} onSort={toggleSort}
                    filterValue={colFilters.location} onFilter={v => setColFilter('location', v)}
                    filterType="text" />
                  <ColHeader label="Posted"   col="posted_at" sort={sort} onSort={toggleSort} />
                  <th className="th-plain">Links</th>
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr><td colSpan={8} className="empty">No jobs match the current filters.</td></tr>
                ) : paginated.map(job => (
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
                        {job.url      && <a href={job.url}      target="_blank" rel="noreferrer">View</a>}
                        {job.apply_url && <a href={job.apply_url} target="_blank" rel="noreferrer">Apply</a>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button onClick={() => setPage(0)}              disabled={currentPage === 0}>«</button>
            <button onClick={() => setPage(p => p - 1)}    disabled={currentPage === 0}>‹</button>
            <span>{currentPage + 1} / {pageCount} &nbsp;·&nbsp; {sorted.length} jobs</span>
            <button onClick={() => setPage(p => p + 1)}    disabled={currentPage >= pageCount - 1}>›</button>
            <button onClick={() => setPage(pageCount - 1)} disabled={currentPage >= pageCount - 1}>»</button>
          </div>
        </>
      )}

      {toast && <div className={`toast${toast.error ? ' toast-error' : ''}`}>{toast.msg}</div>}
    </div>
  )
}

function ColHeader({ label, col, sort, onSort, filterValue, onFilter, filterType, options }) {
  const isActive = sort.col === col
  const sortIcon = isActive ? (sort.dir === 'asc' ? '↑' : '↓') : '⇅'

  return (
    <th>
      <div className={`th-label${isActive ? ' th-active' : ''}`} onClick={() => onSort(col)}>
        <span>{label}</span>
        <span className="sort-icon">{sortIcon}</span>
      </div>
      {onFilter && filterType === 'select' && (
        <select className="col-filter" value={filterValue} onChange={e => onFilter(e.target.value)}>
          <option value="">All</option>
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      )}
      {onFilter && filterType === 'text' && (
        <input
          className="col-filter"
          placeholder="filter…"
          value={filterValue}
          onChange={e => onFilter(e.target.value)}
        />
      )}
    </th>
  )
}

function ScoreBadge({ score }) {
  if (score == null) return <span className="score score-none">—</span>
  const cls = score >= 75 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low'
  return <span className={`score ${cls}`}>{score}</span>
}

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import logo from './../public/logo.png';

const STATUSES = [
  'new', 'evaluated', 'should_apply', 'should_not_apply',
  'tailored', 'applied', 'needs_manual', 'blocked', 'error',
]
const PAGE_SIZE = 50

const MULTI = () => ({ values: [], mode: 'include' })

function applyMulti(val, filter) {
  if (!filter.values.length) return true
  const hit = filter.values.includes(val)
  return filter.mode === 'include' ? hit : !hit
}

const ALL_COLS = [
  { key: 'score',    label: 'Score' },
  { key: 'status',   label: 'Status' },
  { key: 'company',  label: 'Company' },
  { key: 'title',    label: 'Title' },
  { key: 'ats',      label: 'ATS' },
  { key: 'location', label: 'Location' },
  { key: 'posted',   label: 'Posted' },
  { key: 'added',    label: 'Added' },
  { key: 'links',    label: 'Links' },
  { key: 'id',       label: 'ID' },
]
const DEFAULT_VISIBLE = new Set(ALL_COLS.map(c => c.key))

export default function App() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [colFilters, setColFilters] = useState({
    title: '', company: MULTI(), status: MULTI(), ats: MULTI(), location: '', date_added: '',
  })
  const [sort, setSort] = useState({ col: 'fit_score', dir: 'desc' })
  const [page, setPage] = useState(0)
  const [toast, setToast] = useState(null)
  const [visibleCols, setVisibleCols] = useState(DEFAULT_VISIBLE)
  const [copiedId, setCopiedId] = useState(null)

  useEffect(() => {
    fetch('/api/jobs/')
      .then(r => r.json())
      .then(data => { setJobs(data); setLoading(false) })
  }, [])

  const companies  = useMemo(() => [...new Set(jobs.map(j => j.company))].sort(), [jobs])
  const atsList    = useMemo(() => [...new Set(jobs.map(j => j.ats))].sort(), [jobs])
  const statusList = useMemo(() => [...new Set(jobs.map(j => j.status))].sort(), [jobs])

  const filtered = useMemo(() => {
    const { title, company, status, ats, location, date_added } = colFilters
    return jobs.filter(j => {
      if (!applyMulti(j.status,  status))  return false
      if (!applyMulti(j.company, company)) return false
      if (!applyMulti(j.ats,     ats))     return false
      if (title      && !j.title.toLowerCase().includes(title.toLowerCase()))                   return false
      if (location   && !(j.location || '').toLowerCase().includes(location.toLowerCase()))     return false
      if (date_added && !(j.date_added || '').slice(0, 10).includes(date_added))                return false
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

  useEffect(() => setPage(0), [colFilters, sort])

  const toggleSort = useCallback(col => {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'desc' })
  }, [])

  const setColFilter = useCallback((key, val) => {
    setColFilters(f => ({ ...f, [key]: val }))
  }, [])

  const clearFilters = useCallback(() => {
    setColFilters({ title: '', company: MULTI(), status: MULTI(), ats: MULTI(), location: '', date_added: '' })
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

  const copyId = useCallback(id => {
    navigator.clipboard.writeText(id)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1500)
  }, [])

  const counts = useMemo(() => {
    const c = {}
    filtered.forEach(j => { c[j.status] = (c[j.status] || 0) + 1 })
    return c
  }, [filtered])

  const hasFilters = colFilters.title || colFilters.location || colFilters.date_added ||
    colFilters.company.values.length || colFilters.status.values.length || colFilters.ats.values.length

  let toastTimer
  function showToast(msg, error = false) {
    setToast({ msg, error })
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => setToast(null), 2200)
  }

  const vis = key => visibleCols.has(key)
  const colSpan = visibleCols.size

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
          <ColVisPanel cols={ALL_COLS} visible={visibleCols} onChange={setVisibleCols} />
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
                  {vis('score')    && <ColHeader label="Score"    col="fit_score"  sort={sort} onSort={toggleSort} />}
                  {vis('status')   && <ColHeader label="Status"   col="status"     sort={sort} onSort={toggleSort}
                    filterValue={colFilters.status}   onFilter={v => setColFilter('status', v)}
                    filterType="multi" options={statusList} />}
                  {vis('company')  && <ColHeader label="Company"  col="company"    sort={sort} onSort={toggleSort}
                    filterValue={colFilters.company}  onFilter={v => setColFilter('company', v)}
                    filterType="multi" options={companies} />}
                  {vis('title')    && <ColHeader label="Title"    col="title"      sort={sort} onSort={toggleSort}
                    filterValue={colFilters.title}    onFilter={v => setColFilter('title', v)}
                    filterType="text" />}
                  {vis('ats')      && <ColHeader label="ATS"      col="ats"        sort={sort} onSort={toggleSort}
                    filterValue={colFilters.ats}      onFilter={v => setColFilter('ats', v)}
                    filterType="multi" options={atsList} />}
                  {vis('location') && <ColHeader label="Location" col="location"   sort={sort} onSort={toggleSort}
                    filterValue={colFilters.location} onFilter={v => setColFilter('location', v)}
                    filterType="text" />}
                  {vis('posted')   && <ColHeader label="Posted"   col="posted_at"  sort={sort} onSort={toggleSort} />}
                  {vis('added')    && <ColHeader label="Added"    col="date_added" sort={sort} onSort={toggleSort}
                    filterValue={colFilters.date_added} onFilter={v => setColFilter('date_added', v)}
                    filterType="text" />}
                  {vis('links')    && <th className="th-plain">Links</th>}
                  {vis('id')       && <th className="th-plain">ID</th>}
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr><td colSpan={colSpan} className="empty">No jobs match the current filters.</td></tr>
                ) : paginated.map(job => (
                  <tr key={job.id}>
                    {vis('score') && <td><ScoreBadge score={job.fit_score} /></td>}
                    {vis('status') && (
                      <td>
                        <select
                          className={`status-sel s-${job.status}`}
                          value={job.status}
                          onChange={e => updateStatus(job.id, e.target.value)}
                        >
                          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                    )}
                    {vis('company')  && <td className="col-company">{job.company}</td>}
                    {vis('title')    && <td className="col-title">{job.title}</td>}
                    {vis('ats')      && <td>{job.ats}</td>}
                    {vis('location') && (
                      <td className="col-location">
                        {job.location || ''}
                        {job.remote ? <span className="remote-badge">Remote</span> : null}
                      </td>
                    )}
                    {vis('posted') && <td className="col-date">{job.posted_at  ? job.posted_at.slice(0, 10)  : '—'}</td>}
                    {vis('added')  && <td className="col-date">{job.date_added ? job.date_added.slice(0, 10) : '—'}</td>}
                    {vis('links') && (
                      <td>
                        <div className="link-group">
                          {job.url       && <a href={job.url}       target="_blank" rel="noreferrer">View</a>}
                          {job.apply_url && <a href={job.apply_url} target="_blank" rel="noreferrer">Apply</a>}
                        </div>
                      </td>
                    )}
                    {vis('id') && (
                      <td
                        className={`col-id${copiedId === job.id ? ' col-id-copied' : ''}`}
                        title={job.id}
                        onClick={() => copyId(job.id)}
                      >
                        {copiedId === job.id ? '✓ copied' : job.id.slice(0, 8)}
                      </td>
                    )}
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

function ColVisPanel({ cols, visible, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const toggle = key => {
    const next = new Set(visible)
    next.has(key) ? next.delete(key) : next.add(key)
    onChange(next)
  }

  const hiddenCount = cols.length - visible.size

  return (
    <div className="colvis-wrap" ref={ref}>
      <button className={`colvis-btn${hiddenCount ? ' colvis-active' : ''}`} onClick={() => setOpen(o => !o)}>
        Columns{hiddenCount ? ` (${hiddenCount} hidden)` : ''}
      </button>
      {open && (
        <div className="colvis-dropdown">
          {cols.map(c => (
            <label key={c.key} className="colvis-option">
              <input type="checkbox" checked={visible.has(c.key)} onChange={() => toggle(c.key)} />
              <span>{c.label}</span>
            </label>
          ))}
          <div className="colvis-footer">
            <button onClick={() => onChange(new Set(cols.map(c => c.key)))}>Show all</button>
          </div>
        </div>
      )}
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
      {onFilter && filterType === 'multi' && (
        <MultiSelectDropdown options={options} filter={filterValue} onChange={onFilter} />
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

function MultiSelectDropdown({ options, filter, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const toggle = val => {
    const next = filter.values.includes(val)
      ? filter.values.filter(v => v !== val)
      : [...filter.values, val]
    onChange({ ...filter, values: next })
  }

  const label = filter.values.length === 0 ? 'All'
    : filter.values.length === 1 ? filter.values[0]
    : `${filter.values.length} selected`

  const active = filter.values.length > 0

  return (
    <div className={`ms-wrap${active ? ' ms-active' : ''}`} ref={ref}>
      <button className="ms-btn" onClick={() => setOpen(o => !o)}>
        <span className="ms-label">{label}</span>
        <span className="ms-arrow">▾</span>
      </button>
      {open && (
        <div className="ms-dropdown">
          <div className="ms-mode">
            <button
              className={filter.mode === 'include' ? 'ms-mode-on' : ''}
              onClick={() => onChange({ ...filter, mode: 'include' })}
            >Keep only</button>
            <button
              className={filter.mode === 'exclude' ? 'ms-mode-on' : ''}
              onClick={() => onChange({ ...filter, mode: 'exclude' })}
            >Exclude</button>
          </div>
          <div className="ms-options">
            {options.map(o => (
              <label key={o} className="ms-option">
                <input type="checkbox" checked={filter.values.includes(o)} onChange={() => toggle(o)} />
                <span>{o}</span>
              </label>
            ))}
          </div>
          <div className="ms-footer">
            <button onClick={() => onChange({ ...filter, values: [...options] })}>Select all</button>
            {active && (
              <button className="ms-clear-btn" onClick={() => onChange({ ...filter, values: [] })}>
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ScoreBadge({ score }) {
  if (score == null) return <span className="score score-none">—</span>
  const cls = score >= 75 ? 'score-high' : score >= 50 ? 'score-mid' : 'score-low'
  return <span className={`score ${cls}`}>{score}</span>
}

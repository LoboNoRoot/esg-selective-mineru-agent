/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */
import { useEffect, useMemo, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || ''
const LOW_CONFIDENCE = 70
const views = [
  ['dashboard', '总览'],
  ['reports', '报告管理'],
  ['review', '结果复核'],
  ['compare', '指标对比'],
  ['export', '导出中心'],
]
const statusLabels = {
  queued: '已排队',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  skipped: '已跳过',
  pending: '待复核',
  approved: '已确认',
  rejected: '已驳回',
  edited: '已修改',
}

async function api(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`)
  return response.json()
}

function fileName(job) {
  return (job?.summary?.filename || job?.pdf_path || '').split(/[\\/]/).pop() || '-'
}

function reportTitle(job) {
  return fileName(job)
    .replace(/\.pdf$/i, '')
    .replace(/^[a-f0-9]{16,}_[0-9]{4,}_?/i, '')
    .replace(/^[a-f0-9]{8,}_?/i, '')
    .replace(/[_-]+/g, ' ')
    .trim() || fileName(job)
}

function fmtDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

function translateReason(reason) {
  const text = String(reason || '')
  if (!text) return ''
  if (text.includes('legacy social responsibility report') || text.includes('lacks ESG')) {
    return '文档标题疑似传统社会责任报告，且缺少 ESG 或“环境、社会与治理”标题信号，已跳过抽取流程。'
  }
  if (text.includes('supporting statement') || text.includes('assurance report')) {
    return '文档疑似鉴证声明、补充说明或摘要文件，不是完整 ESG 报告，已跳过抽取流程。'
  }
  if (text.includes('PDF cannot be opened or parsed')) {
    return text.replace('PDF cannot be opened or parsed', 'PDF 无法打开或解析')
  }
  return text
}

function formatApiError(error) {
  const text = String(error?.message || error || '')
  try {
    const data = JSON.parse(text)
    const detail = data.detail
    if (detail?.code === 'duplicate_report') {
      return `${detail.message} 原任务：${detail.job_id?.slice(0, 10) || '-'}，状态：${statusLabels[detail.status] || detail.status || '-'}。`
    }
    if (typeof detail === 'string') return detail
    if (detail?.message) return detail.message
  } catch {
    // Keep original text below.
  }
  return translateReason(text) || text
}

function confidence(row) {
  const numeric = Number(row?.confidence || 0)
  return Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric)))
}

function reviewStatus(row) {
  return row?.review?.status || 'pending'
}

function displayValue(row) {
  const review = row?.review || {}
  const value = review.value ?? row?.value ?? ''
  const unit = review.unit ?? row?.unit ?? ''
  return [value, unit].filter(Boolean).join(' ') || row?.summary || (row?.matched ? '已匹配，待复核' : '未抽取')
}

function statusClass(status) {
  if (['succeeded', 'approved', 'edited'].includes(status)) return 'verified'
  if (['failed', 'skipped', 'rejected'].includes(status)) return 'rejected'
  return 'review'
}

function StatusIcon({ status }) {
  if (['failed', 'skipped', 'rejected'].includes(status)) return <span className="status-icon error">×</span>
  if (['succeeded', 'approved', 'edited'].includes(status)) return <span className="status-icon success">✓</span>
  if (['running', 'queued', 'pending'].includes(status)) return <span className="status-icon running">!</span>
  return null
}

function Badge({ status, children }) {
  return <span className={`badge ${statusClass(status)}`}><StatusIcon status={status} />{children || statusLabels[status] || status || '-'}</span>
}

export default function App() {
  const [view, setView] = useState('dashboard')
  const [jobs, setJobs] = useState([])
  const [selectedJobId, setSelectedJobId] = useState('')
  const [results, setResults] = useState([])
  const [selectedField, setSelectedField] = useState('')
  const [resultFilter, setResultFilter] = useState('all')
  const [jobFilter, setJobFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('上传 ESG 报告 PDF 后，系统会保留历史任务，并支持多份报告的指标横向对比。')

  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) || jobs[0]

  async function refreshJobs() {
    const data = await api('/jobs')
    const list = data.jobs || []
    setJobs(list)
    if (!selectedJobId && list[0]) setSelectedJobId(list[0].job_id)
  }

  async function loadResults(jobId) {
    if (!jobId) return
    try {
      const rows = await api(`/jobs/${jobId}/results`)
      setResults(rows || [])
      setSelectedField(rows?.[0]?.field_key || '')
      setResultFilter('all')
    } catch {
      setResults([])
      setSelectedField('')
      const job = jobs.find((item) => item.job_id === jobId)
      if (job?.status === 'skipped') setMessage(translateReason(job.summary?.reason))
    }
  }

  async function openJob(job, nextView = 'review') {
    setSelectedJobId(job.job_id)
    setView(nextView)
    setMessage(`正在查看：${fileName(job)}`)
    await loadResults(job.job_id)
  }

  useEffect(() => {
    refreshJobs().catch((error) => setMessage(`读取历史任务失败：${error.message}`))
  }, [])

  useEffect(() => {
    if (selectedJobId) loadResults(selectedJobId)
  }, [selectedJobId])

  useEffect(() => {
    const timer = setInterval(() => refreshJobs().catch(() => {}), 4000)
    return () => clearInterval(timer)
  }, [selectedJobId])

  async function upload(files) {
    const selected = Array.from(files || [])
    if (!selected.length) return
    const formData = new FormData()
    selected.forEach((file) => formData.append('files', file))
    setMessage(`正在上传 ${selected.length} 份报告...`)
    try {
      const data = await api('/reports/batch?mode=run&use_llm=true', { method: 'POST', body: formData })
      await refreshJobs()
      if (data.jobs?.[0]) setSelectedJobId(data.jobs[0].job_id)
      setView('reports')
      setMessage(`已创建 ${data.jobs?.length || 0} 个任务。每份报告会单独保留，后续可多选进入指标对比。`)
    } catch (error) {
      setMessage(`上传失败：${formatApiError(error)}`)
    }
  }

  async function retry(jobId) {
    try {
      await api(`/jobs/${jobId}/retry`, { method: 'POST' })
      setMessage('任务已重新排队。')
      await refreshJobs()
    } catch (error) {
      setMessage(`重跑失败：${error.message}`)
    }
  }

  async function deleteJob(jobId) {
    const job = jobs.find((item) => item.job_id === jobId)
    if (!window.confirm(`确定删除这份报告及其抽取结果吗？\n${fileName(job)}`)) return
    try {
      await api(`/jobs/${jobId}`, { method: 'DELETE' })
      setMessage('报告任务已删除。')
      if (selectedJobId === jobId) {
        setSelectedJobId('')
        setResults([])
        setSelectedField('')
      }
      await refreshJobs()
    } catch (error) {
      setMessage(`删除失败：${formatApiError(error)}`)
    }
  }

  async function saveReview(fieldKey, patch) {
    const row = results.find((item) => item.field_key === fieldKey)
    if (!row || !selectedJobId) return
    try {
      await api(`/jobs/${selectedJobId}/reviews/${encodeURIComponent(fieldKey)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: patch.status,
          value: patch.value ?? row.review?.value ?? row.value,
          unit: patch.unit ?? row.review?.unit ?? row.unit,
          year: patch.year ?? row.review?.year ?? row.year,
          evidence: patch.evidence ?? row.review?.evidence ?? row.evidence,
          reviewer_note: patch.reviewer_note ?? row.review?.reviewer_note ?? '',
        }),
      })
      const currentIndex = results.findIndex((item) => item.field_key === fieldKey)
      const fresh = await api(`/jobs/${selectedJobId}/results`)
      setResults(fresh || [])
      const pending = (fresh || []).filter((item) => reviewStatus(item) === 'pending' && item.field_key !== fieldKey)
      const next = pending.find((item) => fresh.findIndex((rowItem) => rowItem.field_key === item.field_key) > currentIndex) || pending[0]
      if (next) {
        setSelectedField(next.field_key)
        setResultFilter('pending')
        setMessage('已保存复核结果，并自动切换到下一条待复核记录。')
      } else {
        setMessage('已保存复核结果，当前报告没有更多待复核记录。')
      }
    } catch (error) {
      setMessage(`保存复核失败：${error.message}`)
    }
  }

  const stats = useMemo(() => {
    const done = jobs.filter((job) => job.status === 'succeeded').length
    const failed = jobs.filter((job) => ['failed', 'skipped'].includes(job.status)).length
    const pending = results.filter((row) => reviewStatus(row) === 'pending').length
    const avg = results.length ? Math.round(results.reduce((sum, row) => sum + confidence(row), 0) / results.length) : 0
    return { total: jobs.length, done, failed, pending, avg }
  }, [jobs, results])

  const visibleResults = useMemo(() => results.filter((row) => {
    const haystack = `${row.category} ${row.name_cn} ${row.field_key} ${row.evidence} ${displayValue(row)}`.toLowerCase()
    const status = reviewStatus(row)
    return haystack.includes(search.toLowerCase()) && (resultFilter === 'all' || status === resultFilter || (resultFilter === 'low' && confidence(row) < LOW_CONFIDENCE))
  }), [results, search, resultFilter])

  const selectedRow = results.find((row) => row.field_key === selectedField) || visibleResults[0]

  function goReports(filter) {
    setJobFilter(filter)
    setView('reports')
  }

  function goPendingReview() {
    setResultFilter('pending')
    setView('review')
  }

  return <div className="shell">
    <Topbar view={view} setView={setView} search={search} setSearch={setSearch} />
    <div className="workspace">
      <Sidebar view={view} setView={setView} />
      <main className="main">
        <Header view={view} message={message} upload={upload} />
        <div className="grid">
          <Stats stats={stats} goReports={goReports} goPendingReview={goPendingReview} />
          {view === 'dashboard' && <Dashboard jobs={jobs} openJob={openJob} />}
          {view === 'reports' && <Reports jobs={jobs} jobFilter={jobFilter} setJobFilter={setJobFilter} selectedJobId={selectedJobId} openJob={openJob} retry={retry} deleteJob={deleteJob} />}
          {view === 'review' && <Review selectedJob={selectedJob} rows={visibleResults} selectedRow={selectedRow} setSelectedField={setSelectedField} filter={resultFilter} setFilter={setResultFilter} saveReview={saveReview} onBack={() => setView('reports')} />}
          {view === 'compare' && <Compare jobs={jobs} setGlobalMessage={setMessage} />}
          {view === 'export' && <Export jobs={jobs} />}
        </div>
      </main>
    </div>
  </div>
}

function Topbar({ view, setView, search, setSearch }) {
  return <header className="topbar">
    <div className="brand"><span className="brand-mark">ESG</span><span>ESG Miner</span></div>
    <nav className="topnav">{views.map(([id, label]) => <button key={id} className={`nav-btn ${view === id ? 'active' : ''}`} onClick={() => setView(id)}>{label}</button>)}</nav>
    <div className="top-actions">
      <input className="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索指标、证据、字段" />
      <div className="avatar">ESG</div>
    </div>
  </header>
}

function Sidebar({ view, setView }) {
  return <aside className="sidebar">
    <p className="side-label">工作区</p>
    <nav className="side-nav">{views.map(([id, label]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>)}</nav>
  </aside>
}

function Header({ view, message, upload }) {
  const title = { dashboard: '项目总览', reports: '报告管理', review: '结果复核', compare: '指标对比', export: '导出中心' }[view]
  return <section className="page-header">
    <div>
      <p className="eyebrow">ESG 报告智能抽取系统</p>
      <h1>{title}</h1>
      <p className="subtitle">{message}</p>
    </div>
    <div className="actions">
      <input id="fileInput" type="file" accept="application/pdf,.pdf" multiple hidden onChange={(event) => upload(event.target.files)} />
      <button className="button primary" onClick={() => document.getElementById('fileInput').click()}>上传多份报告</button>
    </div>
  </section>
}

function Stats({ stats, goReports, goPendingReview }) {
  return <section className="stats">
    <Stat title="历史报告任务" value={stats.total} note="查看全部上传记录" onClick={() => goReports('all')} />
    <Stat title="已完成" value={stats.done} note="可复核 / 可导出 / 可对比" onClick={() => goReports('succeeded')} />
    <Stat title="失败或跳过" value={stats.failed} note="显示中文原因" warn onClick={() => goReports('failed')} />
    <Stat title="当前待复核" value={stats.pending} note={`进入待复核，平均置信度 ${stats.avg}%`} onClick={goPendingReview} />
  </section>
}

function Stat({ title, value, note, warn, onClick }) {
  return <article className="card">
    <div className="stat-top"><span>{title}</span><span className={`badge ${warn ? 'rejected' : 'verified'}`}>{warn ? '注意' : '实时'}</span></div>
    <div className="stat-value">{value}</div>
    <button className={`stat-link ${warn ? 'warn' : ''}`} onClick={onClick}>{note}</button>
  </article>
}

function Dashboard({ jobs, openJob }) {
  return <div className="panel">
    <div className="panel-header">
      <div><h2 className="panel-title">最近报告</h2><p className="panel-subtitle">点击任意报告，直接进入该报告的抽取结果与复核界面。</p></div>
    </div>
    <JobTable jobs={jobs.slice(0, 8)} onOpen={openJob} />
  </div>
}

function Reports({ jobs, jobFilter, setJobFilter, selectedJobId, openJob, retry, deleteJob }) {
  const filtered = jobs.filter((job) => jobFilter === 'all' || (jobFilter === 'failed' ? ['failed', 'skipped'].includes(job.status) : job.status === jobFilter))
  return <div className="panel">
    <div className="panel-header">
      <div><h2 className="panel-title">历史报告列表</h2><p className="panel-subtitle">每份已上传报告都会保留为独立任务，可进入复核或在“指标对比”中多选比较。</p></div>
    </div>
    <div className="filters">{[['all', '全部'], ['succeeded', '已完成'], ['running', '运行中'], ['failed', '失败/跳过']].map(([id, label]) => <button key={id} className={`chip ${jobFilter === id ? 'active' : ''}`} onClick={() => setJobFilter(id)}>{label}</button>)}</div>
    <JobTable jobs={filtered} selectedJobId={selectedJobId} onOpen={openJob} retry={retry} deleteJob={deleteJob} />
  </div>
}

function JobTable({ jobs, selectedJobId, onOpen, retry, deleteJob }) {
  if (!jobs.length) return <div className="empty">暂无符合条件的历史任务。</div>
  return <div className="table-wrap"><table>
    <thead><tr><th>报告</th><th>状态</th><th>模式</th><th>更新时间</th><th>原因</th><th>操作</th></tr></thead>
    <tbody>{jobs.map((job) => <tr key={job.job_id} className={selectedJobId === job.job_id ? 'selected' : ''} onClick={() => onOpen(job)}>
      <td><button className="table-link" onClick={(event) => { event.stopPropagation(); onOpen(job) }}><span className="strong" title={fileName(job)}>{reportTitle(job)}</span><span className="muted">{job.job_id.slice(0, 10)}</span></button></td>
      <td><Badge status={job.status} /></td>
      <td>{job.mode}</td>
      <td>{fmtDate(job.updated_at)}</td>
      <td><ReasonButton reason={job.error || job.summary?.reason} /></td>
      <td><div className="actions">
        <button className="button" onClick={(event) => { event.stopPropagation(); onOpen(job) }}>查看结果</button>
        {retry && <button className="button" disabled={job.status === 'running'} onClick={(event) => { event.stopPropagation(); retry(job.job_id) }}>重跑</button>}
        {deleteJob && <button className="button danger" disabled={job.status === 'running'} onClick={(event) => { event.stopPropagation(); deleteJob(job.job_id) }}>删除</button>}
      </div></td>
    </tr>)}</tbody>
  </table></div>
}

function ReasonButton({ reason }) {
  const text = translateReason(reason)
  if (!text) return <span className="muted">-</span>
  return <button className="reason-link" title={text} onClick={(event) => { event.stopPropagation(); window.alert(text) }}>查看原因</button>
}

function Review({ selectedJob, rows, selectedRow, setSelectedField, filter, setFilter, saveReview, onBack }) {
  return <section className="split">
    <div className="panel">
      <div className="panel-header">
        <div><h2 className="panel-title">单报告复核</h2><p className="panel-subtitle">{selectedJob ? fileName(selectedJob) : '请选择报告'}。确认或驳回后会自动跳到下一条待复核。</p></div>
        <button className="button" onClick={onBack}>返回报告管理</button>
      </div>
      <div className="filters">{[['all', '全部'], ['pending', '待复核'], ['approved', '已确认'], ['rejected', '已驳回'], ['low', '低置信度']].map(([id, label]) => <button key={id} className={`chip ${filter === id ? 'active' : ''}`} onClick={() => setFilter(id)}>{label}</button>)}</div>
      <ResultTable rows={rows} selectedRow={selectedRow} setSelectedField={setSelectedField} />
    </div>
    <Evidence row={selectedRow} saveReview={saveReview} />
  </section>
}

function ResultTable({ rows, selectedRow, setSelectedField }) {
  if (!rows.length) return <div className="empty">当前报告暂无可展示结果。</div>
  return <div className="table-wrap"><table>
    <thead><tr><th>维度</th><th>指标</th><th>抽取值</th><th>置信度</th><th>复核状态</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.field_key} className={selectedRow?.field_key === row.field_key ? 'selected' : ''} onClick={() => setSelectedField(row.field_key)}>
      <td><span className="badge neutral">{row.category || '-'}</span></td>
      <td><div className="strong">{row.name_cn || row.field_key}</div><div className="muted">{row.indicator_type}</div></td>
      <td>{displayValue(row)}</td>
      <td><span className="confidence"><span className={`meter ${confidence(row) < LOW_CONFIDENCE ? 'warn' : ''}`}><span style={{ width: `${confidence(row)}%` }} /></span>{confidence(row)}%</span></td>
      <td><Badge status={reviewStatus(row)} /></td>
    </tr>)}</tbody>
  </table></div>
}

function Evidence({ row, saveReview }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({})
  useEffect(() => { setEditing(false); setDraft({}) }, [row?.field_key])
  if (!row) return <aside className="panel evidence"><div className="evidence-body muted">请选择一条字段记录。</div></aside>

  const review = row.review || {}
  const value = draft.value ?? review.value ?? row.value ?? ''
  const unit = draft.unit ?? review.unit ?? row.unit ?? ''
  const year = draft.year ?? review.year ?? row.year ?? ''
  const evidence = draft.evidence ?? review.evidence ?? row.evidence ?? ''

  return <aside className="panel evidence">
    <div className="panel-header"><div><h2 className="panel-title">证据预览</h2><p className="panel-subtitle">{row.field_key}</p></div></div>
    <div className="evidence-body">
      <p className="detail-kicker">{row.category} - {row.indicator_type}</p>
      <h3 className="detail-title">{row.name_cn}</h3>
      <p className="detail-meta"><Badge status={reviewStatus(row)} /><span>来源：{row.source_page ? `第 ${row.source_page} 页` : row.source_chunk_id || '-'}</span></p>
      <div className="value-box"><span className="detail-kicker">抽取值</span><span className="extracted-value">{displayValue(row)}</span><span className="detail-meta">年份 {row.year || '-'} / 置信度 {confidence(row)}%</span></div>
      {row.source_text_short && <div className="evidence-block">{row.source_text_short}</div>}
      <div className="evidence-block">{row.evidence || row.reason || '暂无证据'}</div>
      {editing && <div className="form-grid">
        <div className="field"><label>值</label><input value={value} onChange={(event) => setDraft({ ...draft, value: event.target.value })} /></div>
        <div className="field"><label>单位</label><input value={unit} onChange={(event) => setDraft({ ...draft, unit: event.target.value })} /></div>
        <div className="field"><label>年份</label><input value={year} onChange={(event) => setDraft({ ...draft, year: event.target.value })} /></div>
        <div className="field"><label>证据</label><textarea rows="4" value={evidence} onChange={(event) => setDraft({ ...draft, evidence: event.target.value })} /></div>
      </div>}
      <div className="actions" style={{ marginTop: 16 }}>
        <button className="button primary" onClick={() => saveReview(row.field_key, { status: 'approved' })}>确认</button>
        <button className="button" onClick={() => editing ? saveReview(row.field_key, { status: 'edited', value, unit, year, evidence }) : setEditing(true)}>{editing ? '保存修改' : '编辑'}</button>
        <button className="button danger" onClick={() => saveReview(row.field_key, { status: 'rejected' })}>驳回</button>
      </div>
    </div>
  </aside>
}

function Compare({ jobs, setGlobalMessage }) {
  const completedJobs = jobs.filter((job) => job.status === 'succeeded')
  const defaultIds = completedJobs.slice(0, 3).map((job) => job.job_id)
  const [selectedIds, setSelectedIds] = useState(defaultIds)
  const [resultMap, setResultMap] = useState({})
  const [dimension, setDimension] = useState('')
  const [fieldQuery, setFieldQuery] = useState('')
  const [activeFieldKey, setActiveFieldKey] = useState('')
  const [indicatorPickerOpen, setIndicatorPickerOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selectedIds.length) return
    const missing = selectedIds.filter((id) => !resultMap[id])
    if (!missing.length) return
    let cancelled = false
    setLoading(true)
    Promise.all(missing.map(async (id) => [id, await api(`/jobs/${id}/results`)]))
      .then((entries) => {
        if (cancelled) return
        setResultMap((current) => ({ ...current, ...Object.fromEntries(entries) }))
      })
      .catch((error) => setGlobalMessage(`读取对比数据失败：${formatApiError(error)}`))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedIds])

  function toggleJob(jobId) {
    setSelectedIds((current) => current.includes(jobId) ? current.filter((id) => id !== jobId) : [...current, jobId])
  }

  const selectedJobs = completedJobs.filter((job) => selectedIds.includes(job.job_id))
  const selectedResults = selectedIds.flatMap((id) => (resultMap[id] || []).map((row) => ({ ...row, job_id: id })))
  const dimensions = Array.from(new Set(selectedResults.map((row) => row.category).filter(Boolean)))
  const activeDimension = dimension || dimensions[0] || ''
  const allFields = Array.from(new Map(selectedResults.map((row) => [row.field_key, row])).values())
  const fields = allFields
    .filter((row) => !activeDimension || row.category === activeDimension)
    .filter((row) => `${row.name_cn} ${row.field_key}`.toLowerCase().includes(fieldQuery.toLowerCase()))
  const activeField = fields.find((row) => row.field_key === activeFieldKey)

  const summary = useMemo(() => {
    const comparable = fields.filter((field) => selectedIds.filter((id) => (resultMap[id] || []).some((row) => row.field_key === field.field_key)).length > 1).length
    const low = selectedResults.filter((row) => confidence(row) < LOW_CONFIDENCE).length
    return { selected: selectedIds.length, indicators: fields.length, comparable, low }
  }, [fields, selectedIds, selectedResults, resultMap])

  return <section className="compare-workspace">
    <div className="panel compare-selector">
      <div className="panel-header">
        <div><h2 className="panel-title">选择已上传报告</h2><p className="panel-subtitle">可勾选任意多份已完成报告，不限制 2 份。</p></div>
        <span className="badge neutral">已选 {selectedIds.length}</span>
      </div>
      <div className="report-picker">
        {completedJobs.length ? completedJobs.map((job) => <label key={job.job_id} className={`report-option ${selectedIds.includes(job.job_id) ? 'active' : ''}`}>
          <input type="checkbox" checked={selectedIds.includes(job.job_id)} onChange={() => toggleJob(job.job_id)} />
          <span><strong title={fileName(job)}>{reportTitle(job)}</strong><small>{fmtDate(job.updated_at)} · {job.job_id.slice(0, 10)}</small></span>
        </label>) : <div className="empty">暂无已完成报告。请先上传并完成抽取。</div>}
      </div>
    </div>

    <div className="compare-main">
      <section className="compare-summary">
        <article className="card"><span>已选报告</span><strong>{summary.selected}</strong></article>
        <article className="card"><span>指标数量</span><strong>{summary.indicators}</strong></article>
        <article className="card"><span>可横向比较</span><strong>{summary.comparable}</strong></article>
        <article className="card"><span>低置信度</span><strong>{summary.low}</strong></article>
      </section>

      <div className="panel">
        <div className="panel-header compare-toolbar">
          <div><h2 className="panel-title">选择维度和指标</h2><p className="panel-subtitle">{loading ? '正在读取报告结果...' : '先点击维度，再点击下方指标查看对比小页面。'}</p></div>
          <div className="compare-controls">
            <IndicatorPicker
              fields={fields}
              query={fieldQuery}
              setQuery={setFieldQuery}
              open={indicatorPickerOpen}
              setOpen={setIndicatorPickerOpen}
              onSelect={(fieldKey) => {
                setActiveFieldKey(fieldKey)
                setIndicatorPickerOpen(false)
              }}
            />
          </div>
        </div>
        <DimensionBrowser dimensions={dimensions} activeDimension={activeDimension} setDimension={setDimension} allFields={allFields} fields={fields} openField={setActiveFieldKey} />
      </div>
    </div>
    {activeField && <CompareDialog field={activeField} jobs={selectedJobs} resultMap={resultMap} onClose={() => setActiveFieldKey('')} />}
  </section>
}

function IndicatorPicker({ fields, query, setQuery, open, setOpen, onSelect }) {
  return <div className="indicator-picker">
    <div className={`picker-input ${open ? 'active' : ''}`}>
      <input
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        placeholder="筛选指标"
      />
      <button className="picker-arrow" onClick={() => setOpen(!open)} aria-label="展开指标选择">⌄</button>
    </div>
    {open && <div className="picker-menu">
      {fields.length ? fields.map((field) => <button key={field.field_key} className="picker-option" onClick={() => onSelect(field.field_key)}>
        <strong>{field.name_cn || field.field_key}</strong>
        <small>{field.field_key}</small>
      </button>) : <div className="picker-empty">当前维度下暂无指标</div>}
    </div>}
  </div>
}

function DimensionBrowser({ dimensions, activeDimension, setDimension, allFields, fields, openField }) {
  if (!dimensions.length) return <div className="empty">选择报告后，会在这里显示可对比的 ESG 维度。</div>
  return <div className="dimension-browser">
    <div className="dimension-tabs">
      {dimensions.map((item) => <button key={item} className={`dimension-tab ${activeDimension === item ? 'active' : ''}`} onClick={() => setDimension(item)}>
        <span>{item}</span>
        <strong>{allFields.filter((field) => field.category === item).length}</strong>
      </button>)}
    </div>
    <div className="indicator-list">
      {fields.length ? fields.map((field) => <button key={field.field_key} className="indicator-item" onClick={() => openField(field.field_key)}>
        <span className="badge neutral">{field.category || '-'}</span>
        <strong>{field.name_cn || field.field_key}</strong>
        <small>{field.field_key}</small>
      </button>) : <div className="empty">当前维度下暂无匹配指标。</div>}
    </div>
  </div>
}

function CompareDialog({ field, jobs, resultMap, onClose }) {
  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className="compare-dialog" onMouseDown={(event) => event.stopPropagation()}>
      <div className="dialog-header">
        <div>
          <span className="badge neutral">{field.category || '-'}</span>
          <h2>{field.name_cn || field.field_key}</h2>
          <p>{field.field_key}</p>
        </div>
        <button className="close-button" onClick={onClose} aria-label="关闭">×</button>
      </div>
      <CompareMatrix fields={[field]} jobs={jobs} resultMap={resultMap} />
    </section>
  </div>
}

function CompareMatrix({ fields, jobs, resultMap }) {
  if (!jobs.length) return <div className="empty">请至少选择一份已完成报告。</div>
  if (!fields.length) return <div className="empty">当前筛选下暂无可对比指标。</div>

  return <div className="table-wrap compare-table"><table>
    <thead>
      <tr>
        <th className="sticky-col">指标</th>
        {jobs.map((job) => <th key={job.job_id}>{reportTitle(job)}</th>)}
        <th>差异提示</th>
      </tr>
    </thead>
    <tbody>
      {fields.map((field) => {
        const rows = jobs.map((job) => (resultMap[job.job_id] || []).find((row) => row.field_key === field.field_key))
        const values = rows.map((row) => displayValue(row)).filter((value) => value && value !== '未抽取')
        const uniqueValues = new Set(values)
        return <tr key={field.field_key}>
          <td className="sticky-col">
            <span className="badge neutral">{field.category || '-'}</span>
            <div className="strong">{field.name_cn || field.field_key}</div>
            <div className="muted">{field.field_key}</div>
          </td>
          {rows.map((row, index) => <td key={`${field.field_key}-${jobs[index].job_id}`}>
            {row ? <div className="compare-cell">
              <strong>{displayValue(row)}</strong>
              <span>{row.year || '-'} · 置信度 {confidence(row)}%</span>
              <Badge status={reviewStatus(row)} />
            </div> : <span className="muted">未抽取</span>}
          </td>)}
          <td>{uniqueValues.size > 1 ? <span className="badge review">存在差异</span> : <span className="badge verified">一致或单值</span>}</td>
        </tr>
      })}
    </tbody>
  </table></div>
}

function Export({ jobs }) {
  return <div className="panel">
    <div className="panel-header"><div><h2 className="panel-title">导出中心</h2><p className="panel-subtitle">每份报告可单独下载复核后的 CSV。</p></div></div>
    <div className="table-wrap"><table>
      <thead><tr><th>报告</th><th>状态</th><th>导出</th></tr></thead>
      <tbody>{jobs.map((job) => <tr key={job.job_id}><td title={fileName(job)}>{reportTitle(job)}</td><td><Badge status={job.status} /></td><td><button className="button" disabled={job.status !== 'succeeded'} onClick={() => window.open(`${API_BASE}/jobs/${job.job_id}/export.csv`, '_blank')}>下载 CSV</button></td></tr>)}</tbody>
    </table></div>
  </div>
}

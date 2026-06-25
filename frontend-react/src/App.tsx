import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || ''
const LOW_CONFIDENCE = 70
const JOBS_PAGE_SIZE = 12
const RESULTS_PAGE_SIZE = 12

type ViewId = 'dashboard' | 'reports' | 'review' | 'compare' | 'export'
type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'skipped'
type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'edited'

type Job = {
  job_id: string
  status: JobStatus
  mode: string
  pdf_path: string
  output_dir: string
  use_llm: boolean
  created_at: string
  updated_at: string
  error?: string
  summary?: Record<string, unknown>
}

type ReviewRecord = {
  status?: ReviewStatus
  value?: string | null
  unit?: string | null
  year?: string | null
  evidence?: string | null
  reviewer_note?: string
}

type ResultRow = {
  field_key: string
  name_cn?: string
  category?: string
  indicator_type?: string
  matched?: boolean
  value?: string
  unit?: string
  year?: string
  evidence?: string
  reason?: string
  confidence?: number
  source_page?: string | number
  source_chunk_id?: string
  source_text_short?: string
  summary?: string
  review?: ReviewRecord
}

const views: Array<[ViewId, string]> = [
  ['dashboard', '总览'],
  ['reports', '报告管理'],
  ['review', '结果复核'],
  ['compare', '指标对比'],
  ['export', '导出中心'],
]

const viewTitles: Record<ViewId, string> = {
  dashboard: '项目总览',
  reports: '报告管理',
  review: '结果复核',
  compare: '指标对比',
  export: '导出中心',
}

const statusLabels: Record<string, string> = {
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

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`)
  return response.json() as Promise<T>
}

function fileName(job?: Job): string {
  return String(job?.summary?.filename || job?.pdf_path || '').split(/[\\/]/).pop() || '-'
}

function reportTitle(job?: Job): string {
  return fileName(job)
    .replace(/\.pdf$/i, '')
    .replace(/^[a-f0-9]{16,}_[0-9]{4,}_?/i, '')
    .replace(/^[a-f0-9]{8,}_?/i, '')
    .replace(/[_-]+/g, ' ')
    .trim() || fileName(job)
}

function jobSearchText(job: Job): string {
  return `${fileName(job)} ${reportTitle(job)} ${job.job_id} ${job.status} ${job.mode} ${job.error || ''} ${String(job.summary?.reason || '')}`.toLowerCase()
}

function fmtDate(value?: string): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

function translateReason(reason?: unknown): string {
  const text = String(reason || '')
  if (!text) return ''
  if (text.includes('legacy social responsibility report') || text.includes('lacks ESG')) {
    return '标题疑似传统社会责任报告，缺少 ESG 或“环境、社会与治理”等披露框架信号，已跳过抽取流程。'
  }
  if (text.includes('supporting statement') || text.includes('assurance report')) {
    return '文档疑似鉴证声明、补充说明或摘要，不是完整 ESG 报告，已跳过抽取流程。'
  }
  if (text.includes('PDF cannot be opened or parsed')) {
    return text.replace('PDF cannot be opened or parsed', 'PDF 无法打开或解析')
  }
  return text
}

function formatApiError(error: unknown): string {
  const text = String(error instanceof Error ? error.message : error)
  try {
    const data = JSON.parse(text)
    const detail = data.detail
    if (detail?.code === 'duplicate_report') {
      return `${detail.message} 原任务：${detail.job_id?.slice(0, 10) || '-'}，状态：${statusLabels[detail.status] || detail.status || '-'}。`
    }
    if (typeof detail === 'string') return detail
    if (detail?.message) return detail.message
  } catch {
    return translateReason(text) || text
  }
  return text
}

function confidence(row?: ResultRow): number {
  const numeric = Number(row?.confidence || 0)
  return Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric)))
}

function clampPage(page: number, totalPages: number): number {
  return Math.min(Math.max(page, 1), Math.max(totalPages, 1))
}

function paginate<T>(items: T[], page: number, pageSize: number): { items: T[]; page: number; totalPages: number } {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))
  const safePage = clampPage(page, totalPages)
  const start = (safePage - 1) * pageSize
  return { items: items.slice(start, start + pageSize), page: safePage, totalPages }
}

function reviewStatus(row?: ResultRow): ReviewStatus {
  return row?.review?.status || 'pending'
}

function displayValue(row?: ResultRow): string {
  const review = row?.review || {}
  const value = review.value ?? row?.value ?? ''
  const unit = review.unit ?? row?.unit ?? ''
  return [value, unit].filter(Boolean).join(' ') || row?.summary || (row?.matched ? '已匹配，待复核' : '未抽取')
}

function statusClass(status?: string): string {
  if (status && ['succeeded', 'approved', 'edited'].includes(status)) return 'verified'
  if (status && ['failed', 'skipped', 'rejected'].includes(status)) return 'rejected'
  return 'review'
}

function Badge({ status, children }: { status?: string; children?: ReactNode }) {
  return <span className={`badge ${statusClass(status)}`}>{children || statusLabels[status || ''] || status || '-'}</span>
}

export default function App() {
  const [view, setView] = useState<ViewId>('dashboard')
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedJobId, setSelectedJobId] = useState('')
  const [results, setResults] = useState<ResultRow[]>([])
  const [selectedField, setSelectedField] = useState('')
  const [resultFilter, setResultFilter] = useState('all')
  const [jobFilter, setJobFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('上传 ESG 报告 PDF 后，系统会保留历史任务，并支持多份报告的指标横向对比。')

  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) || jobs[0]

  async function refreshJobs() {
    const data = await api<{ jobs: Job[] }>('/jobs')
    setJobs(data.jobs || [])
    if (!selectedJobId && data.jobs?.[0]) setSelectedJobId(data.jobs[0].job_id)
  }

  async function loadResults(jobId: string) {
    if (!jobId) return
    try {
      const rows = await api<ResultRow[]>(`/jobs/${jobId}/results`)
      setResults(rows || [])
      setSelectedField(rows?.[0]?.field_key || '')
      setResultFilter('all')
    } catch {
      setResults([])
      setSelectedField('')
    }
  }

  useEffect(() => {
    refreshJobs().catch((error) => setMessage(`读取历史任务失败：${formatApiError(error)}`))
  }, [])

  useEffect(() => {
    if (selectedJobId) loadResults(selectedJobId)
  }, [selectedJobId])

  useEffect(() => {
    const timer = window.setInterval(() => refreshJobs().catch(() => {}), 4000)
    return () => window.clearInterval(timer)
  }, [selectedJobId])

  async function upload(files: FileList | null) {
    const selected = Array.from(files || [])
    if (!selected.length) return
    const formData = new FormData()
    selected.forEach((file) => formData.append('files', file))
    setMessage(`正在上传 ${selected.length} 份报告...`)
    try {
      const data = await api<{ jobs: Job[] }>('/reports/batch?mode=run&use_llm=true', { method: 'POST', body: formData })
      await refreshJobs()
      if (data.jobs?.[0]) setSelectedJobId(data.jobs[0].job_id)
      setView('reports')
      setMessage(`已创建 ${data.jobs?.length || 0} 个任务。每份报告会单独保留，后续可复核和对比。`)
    } catch (error) {
      setMessage(`上传失败：${formatApiError(error)}`)
    }
  }

  async function openJob(job: Job, nextView: ViewId = 'review') {
    setSelectedJobId(job.job_id)
    setView(nextView)
    setMessage(`正在查看：${fileName(job)}`)
    await loadResults(job.job_id)
  }

  async function retry(jobId: string) {
    try {
      await api(`/jobs/${jobId}/retry`, { method: 'POST' })
      setMessage('任务已重新排队。')
      await refreshJobs()
    } catch (error) {
      setMessage(`重跑失败：${formatApiError(error)}`)
    }
  }

  async function deleteJob(jobId: string) {
    const job = jobs.find((item) => item.job_id === jobId)
    if (!window.confirm(`确定删除这份报告及其抽取结果吗？\n${fileName(job)}`)) return
    try {
      await api(`/jobs/${jobId}`, { method: 'DELETE' })
      setMessage('报告任务已删除。')
      setSelectedJobId('')
      setResults([])
      setSelectedField('')
      await refreshJobs()
    } catch (error) {
      setMessage(`删除失败：${formatApiError(error)}`)
    }
  }

  async function saveReview(fieldKey: string, patch: ReviewRecord) {
    const row = results.find((item) => item.field_key === fieldKey)
    if (!row || !selectedJobId) return
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
    const fresh = await api<ResultRow[]>(`/jobs/${selectedJobId}/results`)
    setResults(fresh || [])
    const next = fresh.find((item) => reviewStatus(item) === 'pending' && item.field_key !== fieldKey)
    if (next) {
      setSelectedField(next.field_key)
      setResultFilter('pending')
    }
    setMessage('已保存复核结果。')
  }

  const stats = useMemo(() => {
    const done = jobs.filter((job) => job.status === 'succeeded').length
    const failed = jobs.filter((job) => ['failed', 'skipped'].includes(job.status)).length
    const processing = jobs.filter((job) => ['queued', 'running'].includes(job.status)).length
    const pending = results.filter((row) => reviewStatus(row) === 'pending').length
    const avg = results.length ? Math.round(results.reduce((sum, row) => sum + confidence(row), 0) / results.length) : 0
    return { total: jobs.length, done, failed, processing, pending, avg }
  }, [jobs, results])

  const visibleResults = useMemo(() => results.filter((row) => {
    const haystack = `${row.category} ${row.name_cn} ${row.field_key} ${row.evidence} ${displayValue(row)}`.toLowerCase()
    const status = reviewStatus(row)
    return haystack.includes(search.toLowerCase()) && (resultFilter === 'all' || status === resultFilter || (resultFilter === 'low' && confidence(row) < LOW_CONFIDENCE))
  }), [results, search, resultFilter])

  const selectedRow = results.find((row) => row.field_key === selectedField) || visibleResults[0]

  return <div className="shell">
    <Topbar view={view} setView={setView} search={search} setSearch={setSearch} />
    <div className="workspace">
      <Sidebar view={view} setView={setView} />
      <main className="main">
        <Header view={view} message={message} upload={upload} />
        <div className="grid">
          <Stats stats={stats} setView={setView} setJobFilter={setJobFilter} setResultFilter={setResultFilter} />
          {view === 'dashboard' && <Dashboard jobs={jobs} openJob={openJob} />}
          {view === 'reports' && <Reports jobs={jobs} jobFilter={jobFilter} setJobFilter={setJobFilter} selectedJobId={selectedJobId} openJob={openJob} retry={retry} deleteJob={deleteJob} />}
          {view === 'review' && <Review selectedJob={selectedJob} rows={visibleResults} selectedRow={selectedRow} setSelectedField={setSelectedField} filter={resultFilter} setFilter={setResultFilter} saveReview={saveReview} onBack={() => setView('reports')} />}
          {view === 'compare' && <Compare jobs={jobs} />}
          {view === 'export' && <Export jobs={jobs} />}
        </div>
      </main>
    </div>
  </div>
}

function Topbar({ view, setView, search, setSearch }: { view: ViewId; setView: (view: ViewId) => void; search: string; setSearch: (value: string) => void }) {
  return <header className="topbar">
    <div className="brand"><span className="brand-mark">ESG</span><span>ESG Miner</span></div>
    <nav className="topnav">{views.map(([id, label]) => <button key={id} className={`nav-btn ${view === id ? 'active' : ''}`} onClick={() => setView(id)}>{label}</button>)}</nav>
    <div className="top-actions">
      <input className="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索指标、证据、字段" />
      <div className="avatar">ESG</div>
    </div>
  </header>
}

function Sidebar({ view, setView }: { view: ViewId; setView: (view: ViewId) => void }) {
  return <aside className="sidebar">
    <p className="side-label">工作区</p>
    <nav className="side-nav">{views.map(([id, label]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>)}</nav>
  </aside>
}

function Header({ view, message, upload }: { view: ViewId; message: string; upload: (files: FileList | null) => void }) {
  return <section className="page-header">
    <div>
      <p className="eyebrow">ESG 报告智能抽取系统</p>
      <h1>{viewTitles[view]}</h1>
      <p className="subtitle">{message}</p>
    </div>
    <div className="actions">
      <input id="fileInput" type="file" accept="application/pdf,.pdf" multiple hidden onChange={(event) => upload(event.target.files)} />
      <button className="button primary" onClick={() => document.getElementById('fileInput')?.click()}>上传多份报告</button>
    </div>
  </section>
}

function Stats({ stats, setView, setJobFilter, setResultFilter }: { stats: { total: number; done: number; failed: number; processing: number; pending: number; avg: number }; setView: (view: ViewId) => void; setJobFilter: (filter: string) => void; setResultFilter: (filter: string) => void }) {
  return <section className="stats">
    <Stat title="处理中" value={stats.processing} note="查看排队 / 运行任务" onClick={() => { setJobFilter('running'); setView('reports') }} />
    <Stat title="历史报告任务" value={stats.total} note="查看全部上传记录" onClick={() => { setJobFilter('all'); setView('reports') }} />
    <Stat title="已完成" value={stats.done} note="可复核 / 可导出 / 可对比" onClick={() => { setJobFilter('succeeded'); setView('reports') }} />
    <Stat title="失败或跳过" value={stats.failed} note="查看处理原因" warn onClick={() => { setJobFilter('failed'); setView('reports') }} />
    <Stat title="当前待复核" value={stats.pending} note={`平均置信度 ${stats.avg}%`} onClick={() => { setResultFilter('pending'); setView('review') }} />
  </section>
}

function Stat({ title, value, note, warn, onClick }: { title: string; value: number; note: string; warn?: boolean; onClick: () => void }) {
  return <article className="card">
    <div className="stat-top"><span>{title}</span><span className={`badge ${warn ? 'rejected' : 'verified'}`}>{warn ? '注意' : '实时'}</span></div>
    <div className="stat-value">{value}</div>
    <button className={`stat-link ${warn ? 'warn' : ''}`} onClick={onClick}>{note}</button>
  </article>
}

function Dashboard({ jobs, openJob }: { jobs: Job[]; openJob: (job: Job) => void }) {
  return <div className="panel">
    <div className="panel-header"><div><h2 className="panel-title">最近报告</h2><p className="panel-subtitle">点击任意报告，直接进入该报告的抽取结果与复核界面。</p></div></div>
    <JobTable jobs={jobs.slice(0, 8)} onOpen={openJob} />
  </div>
}

function Reports(props: { jobs: Job[]; jobFilter: string; setJobFilter: (value: string) => void; selectedJobId: string; openJob: (job: Job) => void; retry: (jobId: string) => void; deleteJob: (jobId: string) => void }) {
  const { jobs, jobFilter, setJobFilter, selectedJobId, openJob, retry, deleteJob } = props
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [pageSize, setPageSize] = useState(JOBS_PAGE_SIZE)
  const filtered = jobs.filter((job) => {
    if (jobFilter === 'all') return true
    if (jobFilter === 'failed') return ['failed', 'skipped'].includes(job.status)
    if (jobFilter === 'running') return ['queued', 'running'].includes(job.status)
    return job.status === jobFilter
  }).filter((job) => !query.trim() || jobSearchText(job).includes(query.trim().toLowerCase()))
  const pageData = paginate(filtered, page, pageSize)
  useEffect(() => { setPage(1) }, [jobFilter, jobs.length, query, pageSize])
  return <div className="panel">
    <div className="panel-header"><div><h2 className="panel-title">历史报告列表</h2><p className="panel-subtitle">每份上传报告都会保留为独立任务，可进入复核或在指标对比中多选比较。</p></div></div>
    <div className="filters">{[['all', '全部'], ['succeeded', '已完成'], ['running', '运行中'], ['failed', '失败/跳过']].map(([id, label]) => <button key={id} className={`chip ${jobFilter === id ? 'active' : ''}`} onClick={() => setJobFilter(id)}>{label}</button>)}</div>
    <div className="list-tools">
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索报告、代码、任务 ID" />
      <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
        {[12, 24, 50].map((size) => <option key={size} value={size}>每页 {size} 条</option>)}
      </select>
    </div>
    <JobTable jobs={pageData.items} selectedJobId={selectedJobId} onOpen={openJob} retry={retry} deleteJob={deleteJob} />
    <Pagination page={pageData.page} totalPages={pageData.totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />
  </div>
}

function JobTable({ jobs, selectedJobId, onOpen, retry, deleteJob }: { jobs: Job[]; selectedJobId?: string; onOpen: (job: Job) => void; retry?: (jobId: string) => void; deleteJob?: (jobId: string) => void }) {
  if (!jobs.length) return <div className="empty">暂无符合条件的历史任务。</div>
  return <div className="table-wrap"><table>
    <thead><tr><th>报告</th><th>状态</th><th>模式</th><th>更新时间</th><th>原因</th><th>操作</th></tr></thead>
    <tbody>{jobs.map((job) => <tr key={job.job_id} className={selectedJobId === job.job_id ? 'selected' : ''} onClick={() => onOpen(job)}>
      <td><button className="table-link" onClick={(event) => { event.stopPropagation(); onOpen(job) }}><span className="strong" title={fileName(job)}>{reportTitle(job)}</span><span className="muted">{job.job_id.slice(0, 10)}</span></button></td>
      <td><Badge status={job.status} /></td>
      <td>{job.mode}</td>
      <td>{fmtDate(job.updated_at)}</td>
      <td>{translateReason(job.error || job.summary?.reason) || '-'}</td>
      <td><div className="actions">
        <button className="button" onClick={(event) => { event.stopPropagation(); onOpen(job) }}>查看结果</button>
        {retry && <button className="button" disabled={job.status === 'running'} onClick={(event) => { event.stopPropagation(); retry(job.job_id) }}>重跑</button>}
        {deleteJob && <button className="button danger" disabled={job.status === 'running'} onClick={(event) => { event.stopPropagation(); deleteJob(job.job_id) }}>删除</button>}
      </div></td>
    </tr>)}</tbody>
  </table></div>
}

function Review(props: { selectedJob?: Job; rows: ResultRow[]; selectedRow?: ResultRow; setSelectedField: (field: string) => void; filter: string; setFilter: (filter: string) => void; saveReview: (fieldKey: string, patch: ReviewRecord) => Promise<void>; onBack: () => void }) {
  return <section className="split">
    <div className="panel">
      <div className="panel-header">
        <div><h2 className="panel-title">单报告复核</h2><p className="panel-subtitle">{props.selectedJob ? fileName(props.selectedJob) : '请选择报告'}。确认或驳回后会自动进入下一条待复核记录。</p></div>
        <button className="button" onClick={props.onBack}>返回报告管理</button>
      </div>
      <div className="filters">{[['all', '全部'], ['pending', '待复核'], ['approved', '已确认'], ['rejected', '已驳回'], ['low', '低置信度']].map(([id, label]) => <button key={id} className={`chip ${props.filter === id ? 'active' : ''}`} onClick={() => props.setFilter(id)}>{label}</button>)}</div>
      <ResultTable rows={props.rows} selectedRow={props.selectedRow} setSelectedField={props.setSelectedField} />
    </div>
    <Evidence row={props.selectedRow} saveReview={props.saveReview} />
  </section>
}

function ResultTable({ rows, selectedRow, setSelectedField }: { rows: ResultRow[]; selectedRow?: ResultRow; setSelectedField: (field: string) => void }) {
  const [page, setPage] = useState(1)
  const pageData = paginate(rows, page, RESULTS_PAGE_SIZE)
  useEffect(() => { setPage(1) }, [rows.length])
  if (!rows.length) return <div className="empty">当前报告暂无可展示结果。</div>
  return <>
  <div className="table-wrap"><table>
    <thead><tr><th>维度</th><th>指标</th><th>抽取值</th><th>置信度</th><th>复核状态</th></tr></thead>
    <tbody>{pageData.items.map((row) => <tr key={row.field_key} className={selectedRow?.field_key === row.field_key ? 'selected' : ''} onClick={() => setSelectedField(row.field_key)}>
      <td><span className="badge neutral">{row.category || '-'}</span></td>
      <td><div className="strong">{row.name_cn || row.field_key}</div><div className="muted">{row.indicator_type}</div></td>
      <td>{displayValue(row)}</td>
      <td><span className="confidence"><span className={`meter ${confidence(row) < LOW_CONFIDENCE ? 'warn' : ''}`}><span style={{ width: `${confidence(row)}%` }} /></span>{confidence(row)}%</span></td>
      <td><Badge status={reviewStatus(row)} /></td>
    </tr>)}</tbody>
  </table></div>
  <Pagination page={pageData.page} totalPages={pageData.totalPages} totalItems={rows.length} pageSize={RESULTS_PAGE_SIZE} onPageChange={setPage} />
  </>
}

function Pagination({ page, totalPages, totalItems, pageSize, onPageChange }: { page: number; totalPages: number; totalItems: number; pageSize: number; onPageChange: (page: number) => void }) {
  if (totalItems <= pageSize) return null
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, totalItems)
  return <div className="pagination">
    <span>{start}-{end} / {totalItems}</span>
    <div className="pagination-actions">
      <button className="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
      <span>第 {page} / {totalPages} 页</span>
      <button className="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一页</button>
    </div>
  </div>
}

function Evidence({ row, saveReview }: { row?: ResultRow; saveReview: (fieldKey: string, patch: ReviewRecord) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<ReviewRecord>({})
  useEffect(() => { setEditing(false); setDraft({}) }, [row?.field_key])
  if (!row) return <aside className="panel evidence"><div className="evidence-body muted">请选择一条字段记录。</div></aside>
  const value = draft.value ?? row.review?.value ?? row.value ?? ''
  const unit = draft.unit ?? row.review?.unit ?? row.unit ?? ''
  const year = draft.year ?? row.review?.year ?? row.year ?? ''
  const evidence = draft.evidence ?? row.review?.evidence ?? row.evidence ?? ''

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
        <div className="field"><label>值</label><input value={value || ''} onChange={(event) => setDraft({ ...draft, value: event.target.value })} /></div>
        <div className="field"><label>单位</label><input value={unit || ''} onChange={(event) => setDraft({ ...draft, unit: event.target.value })} /></div>
        <div className="field"><label>年份</label><input value={year || ''} onChange={(event) => setDraft({ ...draft, year: event.target.value })} /></div>
        <div className="field"><label>证据</label><textarea rows={4} value={evidence || ''} onChange={(event) => setDraft({ ...draft, evidence: event.target.value })} /></div>
      </div>}
      <div className="actions" style={{ marginTop: 16 }}>
        <button className="button primary" onClick={() => saveReview(row.field_key, { status: 'approved' })}>确认</button>
        <button className="button" onClick={() => editing ? saveReview(row.field_key, { status: 'edited', value, unit, year, evidence }) : setEditing(true)}>{editing ? '保存修改' : '编辑'}</button>
        <button className="button danger" onClick={() => saveReview(row.field_key, { status: 'rejected' })}>驳回</button>
      </div>
    </div>
  </aside>
}

function Compare({ jobs }: { jobs: Job[] }) {
  const completedJobs = jobs.filter((job) => job.status === 'succeeded')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [resultMap, setResultMap] = useState<Record<string, ResultRow[]>>({})
  const [activeDimension, setActiveDimension] = useState('E')
  const [activeFieldKey, setActiveFieldKey] = useState('')
  const [indicatorQuery, setIndicatorQuery] = useState('')
  const [indicatorPickerOpen, setIndicatorPickerOpen] = useState(false)

  useEffect(() => {
    if (!selectedIds.length) return
    const missing = selectedIds.filter((id) => !resultMap[id])
    if (!missing.length) return
    let cancelled = false
    Promise.all(missing.map(async (id) => [id, await api<ResultRow[]>(`/jobs/${id}/results`)] as const))
      .then((entries) => {
        if (!cancelled) setResultMap((current) => ({ ...current, ...Object.fromEntries(entries) }))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [selectedIds, resultMap])

  function toggleJob(jobId: string) {
    setSelectedIds((current) => current.includes(jobId) ? current.filter((id) => id !== jobId) : [...current, jobId])
  }

  const selectedJobs = completedJobs.filter((job) => selectedIds.includes(job.job_id))
  const selectedRows = selectedIds.flatMap((id) => resultMap[id] || [])
  const allFields = Array.from(new Map(selectedRows.map((row) => [row.field_key, row] as const)).values())
  const fields = allFields
    .filter((field) => dimensionKey(field.category) === activeDimension)
    .filter((field) => `${field.name_cn || ''} ${field.field_key}`.toLowerCase().includes(indicatorQuery.toLowerCase()))
  const activeField = fields.find((row) => row.field_key === activeFieldKey)

  function switchDimension(nextDimension: string) {
    setActiveDimension(nextDimension)
    setActiveFieldKey('')
    setIndicatorQuery('')
    setIndicatorPickerOpen(false)
  }

  function openField(fieldKey: string) {
    setActiveFieldKey(fieldKey)
    setIndicatorPickerOpen(false)
  }

  return <section className="compare-workspace">
    <div className="panel compare-selector">
      <div className="panel-header"><div><h2 className="panel-title">选择报告</h2><p className="panel-subtitle">先勾选需要对比的报告；系统不会自动选择报告。</p></div><span className="badge neutral">已选 {selectedIds.length}</span></div>
      <div className="report-picker">
        {completedJobs.length ? completedJobs.map((job) => <label key={job.job_id} className={`report-option ${selectedIds.includes(job.job_id) ? 'active' : ''}`}>
          <input type="checkbox" checked={selectedIds.includes(job.job_id)} onChange={() => toggleJob(job.job_id)} />
          <span><strong title={fileName(job)}>{reportTitle(job)}</strong><small>{fmtDate(job.updated_at)} · {job.job_id.slice(0, 10)}</small></span>
        </label>) : <div className="empty">暂无已完成报告。请先上传并完成抽取。</div>}
      </div>
    </div>
    <div className="compare-main">
      <div className="panel">
        <div className="panel-header compare-toolbar">
          <div><h2 className="panel-title">选择维度和指标</h2><p className="panel-subtitle">先选 E / S / G 维度，再从右侧箭头下拉中选择该维度指标。</p></div>
          <div className="compare-controls">
            <IndicatorPicker
              fields={fields}
              query={indicatorQuery}
              setQuery={setIndicatorQuery}
              open={indicatorPickerOpen}
              setOpen={setIndicatorPickerOpen}
              onSelect={openField}
            />
          </div>
        </div>
        <DimensionBrowser activeDimension={activeDimension} setDimension={switchDimension} fields={fields} allFields={allFields} openField={openField} />
        <div className="empty">请选择一个指标，系统会弹出对比窗口展示各报告对应值。</div>
      </div>
    </div>
    {activeField && <CompareDialog field={activeField} jobs={selectedJobs} resultMap={resultMap} onClose={() => setActiveFieldKey('')} />}
  </section>
}

function dimensionKey(category?: string) {
  const text = String(category || '').trim().toLowerCase()
  if (text === 'e' || text.includes('环境') || text.includes('environment')) return 'E'
  if (text === 's' || text.includes('社会') || text.includes('social')) return 'S'
  if (text === 'g' || text.includes('治理') || text.includes('governance')) return 'G'
  return text.slice(0, 1).toUpperCase()
}

function IndicatorPicker({
  fields,
  query,
  setQuery,
  open,
  setOpen,
  onSelect,
}: {
  fields: ResultRow[]
  query: string
  setQuery: (value: string) => void
  open: boolean
  setOpen: (value: boolean) => void
  onSelect: (fieldKey: string) => void
}) {
  return <div className="indicator-picker">
    <div className={`picker-input ${open ? 'active' : ''}`}>
      <input value={query} onChange={(event) => { setQuery(event.target.value); setOpen(true) }} onFocus={() => setOpen(true)} placeholder="筛选指标" />
      <button className="picker-arrow" onClick={() => setOpen(!open)} aria-label="展开指标选择">⌄</button>
    </div>
    {open && <div className="picker-menu">
      {fields.length ? fields.map((field) => <button key={field.field_key} className="picker-option" onClick={() => onSelect(field.field_key)}>
        <strong>{field.name_cn || field.field_key}</strong>
        <small>{field.field_key}</small>
      </button>) : <div className="picker-empty">当前维度下暂无可选指标</div>}
    </div>}
  </div>
}

function DimensionBrowser({
  activeDimension,
  setDimension,
  fields,
  allFields,
  openField,
}: {
  activeDimension: string
  setDimension: (dimension: string) => void
  fields: ResultRow[]
  allFields: ResultRow[]
  openField: (fieldKey: string) => void
}) {
  const dimensions = [
    ['E', '环境'],
    ['S', '社会'],
    ['G', '治理'],
  ]
  return <div className="dimension-browser">
    <div className="dimension-tabs">
      {dimensions.map(([key, label]) => <button key={key} className={`dimension-tab ${activeDimension === key ? 'active' : ''}`} onClick={() => setDimension(key)}>
        <span>{key} · {label}</span>
        <strong>{allFields.filter((field) => dimensionKey(field.category) === key).length}</strong>
      </button>)}
    </div>
    <div className="indicator-list">
      {fields.length ? fields.map((field) => <button key={field.field_key} className="indicator-item" onClick={() => openField(field.field_key)}>
        <span className="badge neutral">{activeDimension}</span>
        <strong>{field.name_cn || field.field_key}</strong>
        <small>{field.field_key}</small>
      </button>) : <div className="empty">请先选择报告，或当前维度没有可对比指标。</div>}
    </div>
  </div>
}

function CompareDialog({ field, jobs, resultMap, onClose }: { field: ResultRow; jobs: Job[]; resultMap: Record<string, ResultRow[]>; onClose: () => void }) {
  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className="compare-dialog" onMouseDown={(event) => event.stopPropagation()}>
      <div className="dialog-header">
        <div>
          <span className="badge neutral">{dimensionKey(field.category)}</span>
          <h2>{field.name_cn || field.field_key}</h2>
          <p>{field.field_key}</p>
        </div>
        <button className="close-button" onClick={onClose} aria-label="关闭">×</button>
      </div>
      <CompareMatrix field={field} jobs={jobs} resultMap={resultMap} />
    </section>
  </div>
}

function CompareMatrix({ field, jobs, resultMap }: { field?: ResultRow; jobs: Job[]; resultMap: Record<string, ResultRow[]> }) {
  if (!jobs.length) return <div className="empty">请至少勾选一份已完成报告。</div>
  if (!field) return <div className="empty">请选择一个指标后再进行对比。</div>
  return <div className="table-wrap compare-table"><table>
    <thead><tr><th className="sticky-col">指标</th>{jobs.map((job) => <th key={job.job_id}>{reportTitle(job)}</th>)}</tr></thead>
    <tbody><tr>
      <td className="sticky-col"><span className="badge neutral">{field.category || '-'}</span><div className="strong">{field.name_cn || field.field_key}</div><div className="muted">{field.field_key}</div></td>
      {jobs.map((job) => {
        const row = (resultMap[job.job_id] || []).find((item) => item.field_key === field.field_key)
        return <td key={job.job_id}>{row ? <div className="compare-cell"><strong>{displayValue(row)}</strong><span>{row.year || '-'} · 置信度 {confidence(row)}%</span><Badge status={reviewStatus(row)} /></div> : <span className="muted">未抽取</span>}</td>
      })}
    </tr></tbody>
  </table></div>
}

function Export({ jobs }: { jobs: Job[] }) {
  return <div className="panel">
    <div className="panel-header"><div><h2 className="panel-title">导出中心</h2><p className="panel-subtitle">每份报告可单独下载复核后的 CSV。</p></div></div>
    <div className="table-wrap"><table>
      <thead><tr><th>报告</th><th>状态</th><th>导出</th></tr></thead>
      <tbody>{jobs.map((job) => <tr key={job.job_id}><td title={fileName(job)}>{reportTitle(job)}</td><td><Badge status={job.status} /></td><td><button className="button" disabled={job.status !== 'succeeded'} onClick={() => window.open(`${API_BASE}/jobs/${job.job_id}/export.csv`, '_blank')}>下载 CSV</button></td></tr>)}</tbody>
    </table></div>
  </div>
}

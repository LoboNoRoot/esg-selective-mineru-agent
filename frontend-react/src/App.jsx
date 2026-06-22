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

function statusClass(status) {
  if (['succeeded', 'approved'].includes(status)) return 'verified'
  if (['failed', 'skipped', 'rejected'].includes(status)) return 'rejected'
  return 'review'
}

function StatusIcon({ status }) {
  if (['failed', 'skipped'].includes(status)) return <span className="status-icon error">×</span>
  if (status === 'succeeded') return <span className="status-icon success">✓</span>
  if (['running', 'queued'].includes(status)) return <span className="status-icon running">!</span>
  return null
}

function Badge({ status, children }) {
  return (
    <span className={`badge ${statusClass(status)}`}>
      <StatusIcon status={status} />
      {children || statusLabels[status] || status || '-'}
    </span>
  )
}

async function api(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (!response.ok) {
    throw new Error((await response.text()) || `HTTP ${response.status}`)
  }
  return response.json()
}

function fileName(job) {
  return (job?.summary?.filename || job?.pdf_path || '').split(/[\\/]/).pop() || '-'
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
  if (text.includes('legacy social responsibility report') || text.includes('lacks ESG')) {
    return '文档标题为传统社会责任报告，且缺少 ESG 或“环境、社会与治理”标题信号，不满足 60 字段 ESG 抽取流程要求，已跳过。'
  }
  if (text.includes('supporting statement') || text.includes('assurance report')) {
    return '文档疑似为鉴证声明、补充说明或摘要文件，不是完整 ESG 报告，已跳过 60 字段抽取流程。'
  }
  if (text.includes('PDF cannot be opened or parsed')) {
    return text.replace('PDF cannot be opened or parsed', 'PDF 无法打开或解析')
  }
  return text
}

function confidence(row) {
  const numeric = Number(row?.confidence || 0)
  return Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric)))
}

function reviewStatus(row) {
  return row?.review?.status || 'pending'
}

function displayValue(row) {
  const review = row.review || {}
  const value = review.value ?? row.value ?? ''
  const unit = review.unit ?? row.unit ?? ''
  return [value, unit].filter(Boolean).join(' ') || row.summary || (row.matched ? '已匹配，待复核' : '未披露')
}

function App() {
  const [view, setView] = useState('dashboard')
  const [jobs, setJobs] = useState([])
  const [selectedJobId, setSelectedJobId] = useState('')
  const [results, setResults] = useState([])
  const [selectedField, setSelectedField] = useState('')
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('上传 ESG 报告 PDF 后，系统会保留历史任务，并支持逐份报告复核和多公司指标对比。')

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
    } catch (error) {
      setResults([])
      setSelectedField('')
      const job = jobs.find((item) => item.job_id === jobId)
      if (job?.status === 'skipped') setMessage(translateReason(job.summary?.reason))
    }
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
      setMessage(`已创建 ${data.jobs?.length || 0} 个任务。每份报告会单独保留、单独复核。`)
    } catch (error) {
      setMessage(`上传失败：${error.message}`)
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
        setFilter('pending')
        setMessage('已保存复核结果，自动切换到下一条待复核记录。')
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

  const visibleResults = useMemo(() => {
    return results.filter((row) => {
      const haystack = `${row.category} ${row.name_cn} ${row.field_key} ${row.evidence} ${displayValue(row)}`.toLowerCase()
      const status = reviewStatus(row)
      return haystack.includes(search.toLowerCase()) && (filter === 'all' || status === filter || (filter === 'low' && confidence(row) < LOW_CONFIDENCE))
    })
  }, [results, search, filter])

  const selectedRow = results.find((row) => row.field_key === selectedField) || visibleResults[0]

  return (
    <div className="shell">
      <Topbar view={view} setView={setView} search={search} setSearch={setSearch} />
      <div className="workspace">
        <Sidebar view={view} setView={setView} />
        <main className="main">
          <Header view={view} message={message} upload={upload} />
          <div className="grid">
            <Stats stats={stats} />
            {view === 'dashboard' && <Dashboard jobs={jobs} setView={setView} setSelectedJobId={setSelectedJobId} />}
            {view === 'reports' && <Reports jobs={jobs} selectedJobId={selectedJobId} setSelectedJobId={setSelectedJobId} retry={retry} />}
            {view === 'review' && <Review selectedJob={selectedJob} results={visibleResults} selectedRow={selectedRow} setSelectedField={setSelectedField} filter={filter} setFilter={setFilter} saveReview={saveReview} />}
            {view === 'compare' && <Compare jobs={jobs} selectedJob={selectedJob} results={results} />}
            {view === 'export' && <Export jobs={jobs} />}
          </div>
        </main>
      </div>
    </div>
  )
}

function Topbar({ view, setView, search, setSearch }) {
  return <header className="topbar"><div className="brand"><span className="brand-mark">ESG</span><span>ESG Miner</span></div><nav className="topnav">{views.map(([id, label]) => <button key={id} className={`nav-btn ${view === id ? 'active' : ''}`} onClick={() => setView(id)}>{label}</button>)}</nav><div className="top-actions"><input className="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索指标、证据、字段" /><div className="avatar">ESG</div></div></header>
}

function Sidebar({ view, setView }) {
  return <aside className="sidebar"><p className="side-label">工作区</p><nav className="side-nav">{views.map(([id, label]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>{label}</button>)}</nav></aside>
}

function Header({ view, message, upload }) {
  const title = { dashboard: '项目总览', reports: '报告管理', review: '结果复核', compare: '指标对比', export: '导出中心' }[view]
  return <section className="page-header"><div><p className="eyebrow">ESG 报告智能抽取系统</p><h1>{title}</h1><p className="subtitle">{message}</p></div><div className="actions"><input id="fileInput" type="file" accept="application/pdf,.pdf" multiple hidden onChange={(event) => upload(event.target.files)} /><button className="button primary" onClick={() => document.getElementById('fileInput').click()}>上传多份报告</button></div></section>
}

function Stats({ stats }) {
  return <section className="stats"><Stat title="历史报告任务" value={stats.total} note="保留所有上传记录" /><Stat title="已完成" value={stats.done} note="可复核 / 可导出" /><Stat title="失败或跳过" value={stats.failed} note="显示中文原因" warn /><Stat title="当前待复核" value={stats.pending} note={`平均置信度 ${stats.avg}%`} /></section>
}

function Stat({ title, value, note, warn }) {
  return <article className="card"><div className="stat-top"><span>{title}</span><span className={`badge ${warn ? 'rejected' : 'verified'}`}>{warn ? '注意' : '实时'}</span></div><div className="stat-value">{value}</div><span className={`trend ${warn ? 'warn' : ''}`}>{note}</span></article>
}

function Dashboard({ jobs, setView, setSelectedJobId }) {
  return <div className="panel"><div className="panel-header"><div><h2 className="panel-title">最近报告</h2><p className="panel-subtitle">点击任意报告可进入单报告复核。</p></div></div><JobTable jobs={jobs.slice(0, 8)} onSelect={(job) => { setSelectedJobId(job.job_id); setView('review') }} /></div>
}

function Reports({ jobs, selectedJobId, setSelectedJobId, retry }) {
  return <div className="panel"><div className="panel-header"><div><h2 className="panel-title">历史报告列表</h2><p className="panel-subtitle">每份上传报告都会保留任务、状态、结果和复核记录。</p></div></div><JobTable jobs={jobs} selectedJobId={selectedJobId} onSelect={(job) => setSelectedJobId(job.job_id)} retry={retry} /></div>
}

function JobTable({ jobs, onSelect, selectedJobId, retry }) {
  if (!jobs.length) return <div className="empty">暂无历史任务。请先上传 ESG PDF 报告。</div>
  return <div className="table-wrap"><table><thead><tr><th>报告</th><th>状态</th><th>模式</th><th>更新时间</th><th>原因</th><th>操作</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id} className={selectedJobId === job.job_id ? 'selected' : ''} onClick={() => onSelect?.(job)}><td><div className="strong">{fileName(job)}</div><div className="muted">{job.job_id.slice(0, 10)}</div></td><td><Badge status={job.status} /></td><td>{job.mode}</td><td>{fmtDate(job.updated_at)}</td><td className="muted">{translateReason(job.error || job.summary?.reason) || '-'}</td><td>{retry && <button className="button" disabled={job.status === 'running'} onClick={(event) => { event.stopPropagation(); retry(job.job_id) }}>重跑</button>}</td></tr>)}</tbody></table></div>
}

function Review({ selectedJob, results, selectedRow, setSelectedField, filter, setFilter, saveReview }) {
  return <section className="split"><div className="panel"><div className="panel-header"><div><h2 className="panel-title">单报告复核</h2><p className="panel-subtitle">{selectedJob ? fileName(selectedJob) : '请选择报告'}。确认/驳回后会自动跳到下一条待复核。</p></div></div><div className="filters">{[['all', '全部'], ['pending', '待复核'], ['approved', '已确认'], ['rejected', '已驳回'], ['low', '低置信度']].map(([id, label]) => <button key={id} className={`chip ${filter === id ? 'active' : ''}`} onClick={() => setFilter(id)}>{label}</button>)}</div><ResultTable rows={results} selectedRow={selectedRow} setSelectedField={setSelectedField} /></div><Evidence row={selectedRow} saveReview={saveReview} /></section>
}

function ResultTable({ rows, selectedRow, setSelectedField }) {
  if (!rows.length) return <div className="empty">当前报告暂无可展示结果。</div>
  return <div className="table-wrap"><table><thead><tr><th>维度</th><th>指标</th><th>抽取值</th><th>置信度</th><th>复核状态</th></tr></thead><tbody>{rows.map((row) => <tr key={row.field_key} className={selectedRow?.field_key === row.field_key ? 'selected' : ''} onClick={() => setSelectedField(row.field_key)}><td><span className="badge neutral">{row.category || '-'}</span></td><td><div className="strong">{row.name_cn || row.field_key}</div><div className="muted">{row.indicator_type}</div></td><td>{displayValue(row)}</td><td><span className="confidence"><span className={`meter ${confidence(row) < LOW_CONFIDENCE ? 'warn' : ''}`}><span style={{ width: `${confidence(row)}%` }} /></span>{confidence(row)}%</span></td><td><Badge status={reviewStatus(row)} /></td></tr>)}</tbody></table></div>
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
  return <aside className="panel evidence"><div className="panel-header"><div><h2 className="panel-title">证据预览</h2><p className="panel-subtitle">{row.field_key}</p></div></div><div className="evidence-body"><p className="detail-kicker">{row.category} - {row.indicator_type}</p><h3 className="detail-title">{row.name_cn}</h3><p className="detail-meta"><Badge status={reviewStatus(row)} /><span>来源：{row.source_page ? `第 ${row.source_page} 页` : row.source_chunk_id || '-'}</span></p><div className="value-box"><span className="detail-kicker">抽取值</span><span className="extracted-value">{displayValue(row)}</span><span className="detail-meta">年份 {row.year || '-'} / 置信度 {confidence(row)}%</span></div>{row.source_text_short && <div className="evidence-block">{row.source_text_short}</div>}<div className="evidence-block">{row.evidence || row.reason || '暂无证据'}</div>{editing && <div className="form-grid"><div className="field"><label>值</label><input value={value} onChange={(event) => setDraft({ ...draft, value: event.target.value })} /></div><div className="field"><label>单位</label><input value={unit} onChange={(event) => setDraft({ ...draft, unit: event.target.value })} /></div><div className="field"><label>年份</label><input value={year} onChange={(event) => setDraft({ ...draft, year: event.target.value })} /></div><div className="field"><label>证据</label><textarea rows="4" value={evidence} onChange={(event) => setDraft({ ...draft, evidence: event.target.value })} /></div></div>}<div className="actions" style={{ marginTop: 16 }}><button className="button primary" onClick={() => saveReview(row.field_key, { status: 'approved' })}>确认</button><button className="button" onClick={() => editing ? saveReview(row.field_key, { status: 'edited', value, unit, year, evidence }) : setEditing(true)}>{editing ? '保存修改' : '编辑'}</button><button className="button danger" onClick={() => saveReview(row.field_key, { status: 'rejected' })}>驳回</button></div></div></aside>
}

function Compare({ selectedJob, results }) {
  const fields = Array.from(new Map(results.map((row) => [row.field_key, row])).values())
  const [field, setField] = useState('')
  const activeField = field || fields[0]?.field_key || ''
  const rows = results.filter((row) => row.field_key === activeField)
  return <section className="compare-grid"><div className="panel"><div className="panel-header"><div><h2 className="panel-title">选择指标</h2><p className="panel-subtitle">当前展示所选报告内指标；后续可扩展为后端跨报告聚合接口。</p></div></div><div className="form-grid"><div className="field"><label>指标</label><select value={activeField} onChange={(event) => setField(event.target.value)}>{fields.map((row) => <option key={row.field_key} value={row.field_key}>{row.name_cn || row.field_key}</option>)}</select></div></div></div><div className="panel"><div className="panel-header"><div><h2 className="panel-title">指标对比</h2><p className="panel-subtitle">{selectedJob ? fileName(selectedJob) : '请选择报告'}</p></div></div>{rows.length ? <div className="table-wrap"><table><thead><tr><th>报告</th><th>值</th><th>单位</th><th>年份</th><th>置信度</th></tr></thead><tbody>{rows.map((row) => <tr key={row.field_key}><td>{fileName(selectedJob)}</td><td>{row.value || row.summary || '-'}</td><td>{row.unit || '-'}</td><td>{row.year || '-'}</td><td>{confidence(row)}%</td></tr>)}</tbody></table></div> : <div className="empty">暂无可对比数据。</div>}</div></section>
}

function Export({ jobs }) {
  return <div className="panel"><div className="panel-header"><div><h2 className="panel-title">导出中心</h2><p className="panel-subtitle">每份报告单独下载复核后的 CSV。</p></div></div><div className="table-wrap"><table><thead><tr><th>报告</th><th>状态</th><th>导出</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id}><td>{fileName(job)}</td><td><Badge status={job.status} /></td><td><button className="button" disabled={job.status !== 'succeeded'} onClick={() => window.open(`${API_BASE}/jobs/${job.job_id}/export.csv`, '_blank')}>下载 CSV</button></td></tr>)}</tbody></table></div></div>
}

export default App

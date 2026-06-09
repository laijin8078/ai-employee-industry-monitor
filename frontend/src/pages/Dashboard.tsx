import { Row, Col, Card, Statistic, Button, Tag, Spin, Progress, Space } from 'antd'
import {
  ReloadOutlined, ThunderboltOutlined, RiseOutlined,
  FileProtectOutlined, ExperimentOutlined, DashboardOutlined, SyncOutlined,
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { useState, useEffect, useMemo, useRef } from 'react'

const categoryConfig: Record<string, { color: string; icon: React.ReactNode; bg: string }> = {
  '竞品动态': { color: '#4b5de6', icon: <RiseOutlined />, bg: '#eef0ff' },
  '行业政策': { color: '#2e8b57', icon: <FileProtectOutlined />, bg: '#ebf5ee' },
  '行业动态': { color: '#d4a017', icon: <DashboardOutlined />, bg: '#fef9ed' },
  '技术突破': { color: '#b05ce6', icon: <ExperimentOutlined />, bg: '#f8f0ff' },
}

function parseSummary(summary: string) {
  const items: { title: string; category: string }[] = []
  const pattern = /「([^」]+)」(?:（([^）]+)）)?/g
  let match
  while ((match = pattern.exec(summary)) !== null) {
    items.push({ title: match[1], category: match[2] || '未分类' })
  }
  const header = summary.replace(new RegExp('[；;]?「[^」]+」(?:（[^）]+）)?', 'g'), '').replace(/[；;]\s*$/, '').trim()
  return { header, items }
}

interface LogEntry {
  time: string
  level: string
  message: string
  step: string
  source: string
  status: string
}

interface JobRecord {
  job_id: string
  execution_time: string
  status: string
  total_items_collected: number
  important_items_found: number
  current_stage: string
  last_heartbeat: string
}

const stageLabels: Record<string, string> = {
  starting: '启动中', collecting: '采集中', cleaning: '清洗中',
  screening: 'AI初筛', analyzing: '深度分析', summarizing: '竞品汇总',
  reporting: '报告生成', notifying: '发送通知', completed: '已完成',
}

const stepToStage: Record<string, string> = {
  初始化: 'starting',
  启动: 'starting',
  采集: 'collecting',
  清洗: 'cleaning',
  AI初筛: 'screening',
  深度分析: 'analyzing',
  报告生成: 'reporting',
  通知: 'notifying',
  完成: 'completed',
}

const stageOrder = ['starting', 'collecting', 'cleaning', 'screening', 'analyzing', 'summarizing', 'reporting', 'notifying', 'completed']

function getProgress(stage: string) {
  const idx = stageOrder.indexOf(stage)
  if (idx < 0) return 8
  return Math.round(((idx + 1) / stageOrder.length) * 100)
}

function formatElapsed(sec: number) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}

function parseStartMs(value?: string | null) {
  if (!value) return 0
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : 0
}

export default function Dashboard() {
  const [loading, setLoading] = useState(false)
  const [latestReport, setLatestReport] = useState<any>(null)
  const [collecting, setCollecting] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<JobRecord | null>(null)
  const [currentStage, setCurrentStage] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [startedAtMs, setStartedAtMs] = useState(0)
  const [lastMessage, setLastMessage] = useState('')
  const [runStatus, setRunStatus] = useState<'running' | 'success' | 'partial' | 'failed' | ''>('')
  const eventSourceRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchLatestReport()
    restoreActiveJob()
    return () => {
      eventSourceRef.current?.close()
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  useEffect(() => {
    if (collecting) {
      if (timerRef.current) clearInterval(timerRef.current)
      const tick = () => {
        const start = startedAtMs || parseStartMs(sessionStorage.getItem('cc_job_started_at'))
        setElapsed(start ? Math.max(0, Math.floor((Date.now() - start) / 1000)) : 0)
      }
      tick()
      timerRef.current = setInterval(tick, 1000)
    } else if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [collecting, startedAtMs])

  const fetchLatestReport = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/reports/latest')
      if (response.ok) setLatestReport(await response.json())
    } catch (error) { console.error(error) }
    finally { setLoading(false) }
  }

  const restoreActiveJob = async () => {
    try {
      const response = await fetch('/api/jobs/active')
      if (!response.ok) return
      const data = await response.json()
      if (data.has_active && data.job) {
        const job: JobRecord = data.job
        const start = parseStartMs(job.execution_time) || parseStartMs(sessionStorage.getItem('cc_job_started_at')) || Date.now()
        setActiveJob(job)
        setJobId(job.job_id)
        setStartedAtMs(start)
        sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
        setCollecting(true)
        setRunStatus('running')
        setCurrentStage(job.current_stage || 'starting')
        setLastMessage('检测到正在运行的采集任务')
        sessionStorage.setItem('cc_job_id', job.job_id)
        connectSSE(job.job_id)
      }
    } catch (error) {
      console.error(error)
    }
  }

  const connectSSE = (jid: string) => {
    eventSourceRef.current?.close()
    const es = new EventSource(`/api/execute/${jid}/stream`)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data)
        const nextStage = stepToStage[entry.step] || currentStage || 'starting'
        if (entry.step) setCurrentStage(nextStage)
        if (entry.message) setLastMessage(summarizeLog(entry))
        if (entry.status === 'running') setRunStatus('running')

        if (entry.step === '完成' && ['success', 'partial', 'failed', 'timeout', 'cancelled'].includes(entry.status)) {
          const finalStatus = entry.status === 'partial' ? 'partial' : entry.status === 'success' ? 'success' : 'failed'
          setRunStatus(finalStatus)
          setCollecting(false)
          setCurrentStage('completed')
          es.close()
          eventSourceRef.current = null
          setTimeout(fetchLatestReport, 1200)
        }
      } catch (error) {
        console.error(error)
      }
    }

    es.onerror = () => {
      setTimeout(async () => {
        try {
          const response = await fetch('/api/jobs/active')
          const data = await response.json()
          if (data.has_active && data.job?.job_id === jid) {
            connectSSE(jid)
          } else {
            setCollecting(false)
            setTimeout(fetchLatestReport, 800)
          }
        } catch {
          setCollecting(false)
        }
      }, 2500)
    }
  }

  const summarizeLog = (entry: LogEntry) => {
    if (entry.step === '采集' && entry.status === 'success') return '采集阶段完成，正在进入后续处理'
    if (entry.step === '清洗' && entry.status === 'success') return '数据清洗与去重完成'
    if (entry.step === 'AI初筛' && entry.status === 'success') return 'AI初筛完成'
    if (entry.step === '深度分析' && entry.status === 'success') return '深度分析完成'
    if (entry.step === '报告生成' && entry.status === 'success') return '报告已生成'
    if (entry.step === '完成') return entry.message
    if (entry.step) return `${entry.step}：${entry.status === 'warning' ? '需要关注' : '进行中'}`
    return entry.message
  }

  const handleExecute = async () => {
    setLoading(true)
    setCollecting(true)
    setRunStatus('running')
    setCurrentStage('starting')
    const localStart = Date.now()
    setStartedAtMs(localStart)
    setElapsed(0)
    setLastMessage('正在启动采集任务')
    try {
      const response = await fetch('/api/execute', { method: 'POST' })
      const data = await response.json()
      if (response.ok && data.job_id) {
        const start = parseStartMs(data.execution_time) || localStart
        setJobId(data.job_id)
        setStartedAtMs(start)
        sessionStorage.setItem('cc_job_id', data.job_id)
        sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
        setLastMessage(data.status === 'already_running' ? '已有采集任务运行中，已接入实时进度' : '采集任务已启动')
        connectSSE(data.job_id)
      } else {
        setCollecting(false)
        setRunStatus('failed')
        setLastMessage(data.message || '启动采集失败')
      }
    } catch (error) {
      console.error(error)
      setCollecting(false)
      setRunStatus('failed')
      setLastMessage('无法连接后端服务')
    }
    finally { setLoading(false) }
  }

  const parsed = useMemo(() => {
    if (!latestReport?.summary) return { header: '', items: [] }
    return parseSummary(latestReport.summary)
  }, [latestReport?.summary])

  const counts = latestReport?.category_counts || {}
  const progressStage = currentStage || activeJob?.current_stage || ''
  const progressPercent = runStatus === 'success' || runStatus === 'partial' ? 100 : getProgress(progressStage)
  const progressStatus = runStatus === 'failed' ? 'exception' : runStatus === 'success' ? 'success' : 'active'

  const statCards = [
    { title: '总情报数', value: latestReport?.totalCount || 0, icon: '📊', color: '#4b5de6', bg: '#eef0ff' },
    { title: '竞品动态', value: counts['竞品动态'] || 0, icon: '🏢', color: '#4b5de6', bg: '#eef0ff' },
    { title: '行业政策', value: counts['行业政策'] || 0, icon: '📜', color: '#2e8b57', bg: '#ebf5ee' },
    { title: '技术突破', value: counts['技术突破'] || 0, icon: '🔬', color: '#b05ce6', bg: '#f8f0ff' },
  ]

  return (
    <Spin spinning={loading}>
      {/* ====== 统计卡片行 ====== */}
      <Row gutter={[20, 20]} style={{ marginBottom: 28 }}>
        {statCards.map(s => (
          <Col xs={24} sm={12} lg={6} key={s.title}>
            <div style={{
              background: '#fff', borderRadius: 12, padding: '20px 24px',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.03)',
              border: '1px solid oklch(0.93 0.01 260)',
              display: 'flex', alignItems: 'center', gap: 16,
              transition: 'box-shadow 0.2s',
            }}
              onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.08)'}
              onMouseLeave={e => e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.03)'}
            >
              <div style={{
                width: 48, height: 48, borderRadius: 12, background: s.bg,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 22,
              }}>
                {s.icon}
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'oklch(0.45 0.01 260)', marginBottom: 2 }}>{s.title}</div>
                <div style={{ fontSize: 28, fontWeight: 700, color: s.color, lineHeight: 1 }}>
                  {s.value}
                </div>
              </div>
            </div>
          </Col>
        ))}
      </Row>

      <Row gutter={[20, 20]}>
        {/* ====== 报告摘要 ====== */}
        <Col xs={24} lg={16}>
          <Card
            title={<span style={{ fontSize: 16, fontWeight: 600 }}>📋 最新报告摘要</span>}
            extra={latestReport ? <Tag color="blue" style={{ borderRadius: 6 }}>{latestReport.date}</Tag> : undefined}
            style={{ borderRadius: 12, height: '100%' }}
          >
            {parsed.header || parsed.items.length > 0 ? (
              <div>
                {parsed.header && (
                  <div style={{
                    background: '#fffdf0', padding: '14px 18px', borderRadius: 8,
                    borderLeft: '4px solid #d4a017', marginBottom: 20,
                    fontSize: 14, fontWeight: 500, color: '#8b6914',
                    lineHeight: 1.6,
                  }}>
                    <ThunderboltOutlined style={{ marginRight: 8, color: '#d4a017' }} />
                    {parsed.header}
                  </div>
                )}
                {parsed.items.map((item, i) => {
                  const cfg = categoryConfig[item.category] || { color: '#999', icon: null, bg: '#f5f5f5' }
                  return (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '10px 0', borderBottom: i < parsed.items.length - 1 ? '1px solid oklch(0.94 0.01 260)' : 'none'
                    }}>
                      <span style={{
                        width: 28, height: 28, minWidth: 28, borderRadius: 8,
                        background: cfg.bg, color: cfg.color,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 12, fontWeight: 700,
                      }}>
                        {i + 1}
                      </span>
                      <span style={{ flex: 1, fontSize: 14, color: 'oklch(0.2 0.01 260)', lineHeight: 1.5 }}>
                        {item.title}
                      </span>
                      <Tag color={cfg.color} style={{ borderRadius: 4, fontWeight: 500 }}>
                        {item.category}
                      </Tag>
                    </div>
                  )
                })}
                {parsed.items.length === 0 && parsed.header && (
                  <p style={{ color: '#999', textAlign: 'center', padding: 24 }}>暂无详细条目</p>
                )}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 48, color: '#999' }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>📡</div>
                <p style={{ fontSize: 15 }}>暂无报告数据</p>
                <p style={{ fontSize: 13 }}>点击右侧「立即执行采集」开始获取情报</p>
              </div>
            )}
          </Card>
        </Col>

        {/* ====== 快捷面板 ====== */}
        <Col xs={24} lg={8}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <Card style={{ borderRadius: 12 }}>
              <Button type="primary" size="large" icon={<ThunderboltOutlined />}
                onClick={handleExecute} loading={loading || collecting} disabled={collecting} block
                style={{
                  height: 48, fontWeight: 600, fontSize: 15,
                  borderRadius: 10, marginBottom: 16,
                }}
              >
                {collecting ? '采集中...' : '立即执行采集'}
              </Button>
              {(collecting || runStatus) && (
                <div style={{
                  background: runStatus === 'failed' ? '#fff2f0' : '#f6ffed',
                  padding: '14px 16px', borderRadius: 8,
                  border: `1px solid ${runStatus === 'failed' ? '#ffccc7' : '#b7eb8f'}`,
                  marginBottom: 12,
                }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 10 }}>
                    <Space>
                      {collecting ? <SyncOutlined spin style={{ color: '#1890ff' }} /> :
                        runStatus === 'failed' ? <CloseCircleOutlined style={{ color: '#cf1322' }} /> :
                          runStatus === 'partial' ? <WarningOutlined style={{ color: '#d48806' }} /> :
                            <CheckCircleOutlined style={{ color: '#389e0d' }} />}
                      <span style={{ fontSize: 13, fontWeight: 600 }}>
                        {collecting ? stageLabels[progressStage] || '运行中' :
                          runStatus === 'partial' ? '部分完成' :
                            runStatus === 'failed' ? '采集失败' : '采集完成'}
                      </span>
                    </Space>
                    <span style={{ fontSize: 12, color: '#666' }}>{formatElapsed(elapsed)}</span>
                  </Space>
                  <Progress percent={progressPercent} status={progressStatus as any} showInfo={false} />
                  <div style={{ fontSize: 12, color: '#555', marginTop: 8, lineHeight: 1.5 }}>
                    {lastMessage || '等待后端返回进度'}
                  </div>
                  {jobId && (
                    <div style={{ fontSize: 11, color: '#999', marginTop: 6, fontFamily: 'monospace' }}>
                      {jobId}
                    </div>
                  )}
                </div>
              )}
              <div style={{
                background: '#f0fdf4', padding: '12px 16px', borderRadius: 8,
                border: '1px solid #bbf7d0', marginBottom: 12,
              }}>
                <div style={{ fontSize: 13, color: '#166534', fontWeight: 500, marginBottom: 4 }}>
                  📅 定时计划
                </div>
                <div style={{ fontSize: 13, color: '#333' }}>每两周周一 09:00 自动执行</div>
              </div>
            </Card>

            <Card title={<span style={{ fontWeight: 600 }}>📊 分类概览</span>} style={{ borderRadius: 12 }}>
              {Object.entries(counts).length > 0 ? (
                Object.entries(counts).map(([cat, cnt]) => {
                  const cfg = categoryConfig[cat]
                  return (
                    <div key={cat} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '8px 0', borderBottom: '1px solid oklch(0.94 0.01 260)',
                    }}>
                      <Tag color={cfg?.color || '#999'} style={{ borderRadius: 4 }}>
                        {cat}
                      </Tag>
                      <strong style={{ fontSize: 16, color: cfg?.color || '#333' }}>
                        {cnt as number} <span style={{ fontSize: 12, fontWeight: 400 }}>条</span>
                      </strong>
                    </div>
                  )
                })
              ) : (
                <span style={{ fontSize: 13, color: '#999' }}>暂无数据</span>
              )}
            </Card>
          </div>
        </Col>
      </Row>
    </Spin>
  )
}

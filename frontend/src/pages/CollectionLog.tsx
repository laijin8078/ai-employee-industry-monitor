import { useState, useEffect, useRef, useCallback } from 'react'
import { Card, Button, Tag, Table, Space, Spin, Progress, Row, Col, Statistic, message } from 'antd'
import {
  PlayCircleOutlined, ReloadOutlined, CheckCircleOutlined,
  CloseCircleOutlined, SyncOutlined, WarningOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

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
  channels_succeeded: string[]
  channels_failed: string[]
  total_items_collected: number
  important_items_found: number
  report_generated: boolean
  error_message: string
  duration_seconds: number
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

function parseStartMs(value?: string | null) {
  if (!value) return 0
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : 0
}

const stepColors: Record<string, string> = {
  '启动': '#1890ff', '初始化': '#1890ff', '采集': '#722ed1',
  '清洗': '#13c2c2', 'AI初筛': '#eb2f96', '深度分析': '#fa541c',
  '报告生成': '#2f54eb', '通知': '#faad14', '完成': '#52c41a',
  '错误': '#ff4d4f', '取消': '#faad14',
}

const statusConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  running: { color: 'processing', icon: <SyncOutlined spin />, label: '运行中' },
  success: { color: 'success', icon: <CheckCircleOutlined />, label: '成功' },
  partial: { color: 'warning', icon: <WarningOutlined />, label: '部分成功' },
  failed: { color: 'error', icon: <CloseCircleOutlined />, label: '失败' },
  timeout: { color: 'default', icon: <ClockCircleOutlined />, label: '超时' },
  cancelled: { color: 'default', icon: <CloseCircleOutlined />, label: '已取消' },
}

export default function CollectionLog() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [running, setRunning] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [activeJob, setActiveJob] = useState<JobRecord | null>(null)
  const [jobsLoading, setJobsLoading] = useState(true)
  const [currentStep, setCurrentStep] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [startedAtMs, setStartedAtMs] = useState(0)
  const logEndRef = useRef<HTMLDivElement>(null)
  const logContainerRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const elapsedTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const userScrolledUp = useRef(false)
  const runningRef = useRef(false)
  const sessionOwned = useRef(sessionStorage.getItem('cc_job_id'))
  const manualStopRef = useRef(false)  // 用户手动停止后禁止自动重连

  // 同步 runningRef
  useEffect(() => { runningRef.current = running }, [running])

  // 判断用户是否在底部
  const isNearBottom = () => {
    const el = logContainerRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }

  // 智能滚动：仅在用户未手动上滚时才自动滚到底部（直接控制容器 scrollTop）
  useEffect(() => {
    if (!userScrolledUp.current) {
      const el = logContainerRef.current
      if (el) {
        el.scrollTop = el.scrollHeight
      }
    }
  }, [logs])

  // 监听用户滚动
  const handleLogScroll = useCallback(() => {
    userScrolledUp.current = !isNearBottom()
  }, [])

  // 加载数据——仅当本标签页启动的任务处于 running 状态时才自动重连
  const fetchJobs = useCallback(async () => {
    setJobsLoading(true)
    try {
      const jobsR = await fetch('/api/jobs')
      if (jobsR.ok) {
        const allJobs: JobRecord[] = await jobsR.json()
        setJobs(allJobs)
        const runningJob = allJobs.find(j => j.status === 'running')
        if (runningJob) {
          // 手动停止后禁止自动重连
          if (manualStopRef.current) {
            setActiveJob(runningJob)
            setJobsLoading(false)
            return
          }
          const isOurs = sessionOwned.current && sessionOwned.current === runningJob.job_id
          if (isOurs && !runningRef.current) {
            const start = parseStartMs(runningJob.execution_time) || parseStartMs(sessionStorage.getItem('cc_job_started_at')) || Date.now()
            setActiveJob(runningJob)
            setRunning(true)
            setJobId(runningJob.job_id)
            setStartedAtMs(start)
            sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
            setCurrentStep(runningJob.current_stage || 'starting')
            if (!eventSourceRef.current) {
              connectSSE(runningJob.job_id)
            }
          } else {
            // 非本会话的任务或心跳过期，仅展示状态不自动连接
            setActiveJob(runningJob)
          }
        } else {
          setActiveJob(null)
        }
      }
    } catch (e) { console.error(e) }
    finally { setJobsLoading(false) }
  }, [])

  useEffect(() => { fetchJobs() }, [fetchJobs])

  // 运行中的耗时计时器
  useEffect(() => {
    if (running) {
      if (elapsedTimer.current) clearInterval(elapsedTimer.current)
      const tick = () => {
        const start = startedAtMs || parseStartMs(sessionStorage.getItem('cc_job_started_at'))
        setElapsed(start ? Math.max(0, Math.floor((Date.now() - start) / 1000)) : 0)
      }
      tick()
      elapsedTimer.current = setInterval(tick, 1000)
    } else {
      if (elapsedTimer.current) { clearInterval(elapsedTimer.current); elapsedTimer.current = null }
    }
    return () => { if (elapsedTimer.current) clearInterval(elapsedTimer.current) }
  }, [running, startedAtMs])

  // 清理
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close()
      if (elapsedTimer.current) clearInterval(elapsedTimer.current)
    }
  }, [])

  // 连接 SSE
  const connectSSE = (jid: string) => {
    eventSourceRef.current?.close()
    const es = new EventSource(`/api/execute/${jid}/stream`)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data)
        setLogs(prev => [...prev, entry])
        if (entry.step) setCurrentStep(stepToStage[entry.step] || entry.step)

        // 检测完成或取消信号
        const terminalStatuses = ['success', 'partial', 'failed', 'timeout', 'cancelled']
        if (entry.status && terminalStatuses.includes(entry.status) && entry.step === '完成') {
          setRunning(false)
          setCurrentStep('')
          es.close()
          eventSourceRef.current = null
          setTimeout(fetchJobs, 1500)
        }
        if (entry.step === '取消' && entry.status === 'cancelling') {
          // 用户主动取消，等待最终结果
        }
      } catch { /* ignore */ }
    }

    es.onerror = () => {
      // 延迟检查——若连接意外断开且任务仍在跑，尝试重连
      setTimeout(() => {
        if (es.readyState === EventSource.CLOSED && runningRef.current) {
          // SSE 断开但任务可能还在运行，尝试用 active endpoint 恢复
          fetch('/api/jobs/active').then(r => r.json()).then(ad => {
            if (ad.has_active && ad.job?.job_id === jid) {
              // 任务仍在运行，重连 SSE
              connectSSE(jid)
            } else {
              setRunning(false)
              setCurrentStep('')
              fetchJobs()
            }
          }).catch(() => {
            setRunning(false)
            setCurrentStep('')
            fetchJobs()
          })
        } else if (es.readyState === EventSource.CLOSED) {
          setRunning(false)
          setCurrentStep('')
          fetchJobs()
        }
      }, 3000)
    }
  }

  // 开始采集
  const startCollect = async () => {
    setLogs([])
    userScrolledUp.current = false
    manualStopRef.current = false  // 新任务开始，清除手动停止标记
    setRunning(true)
    setCurrentStep('启动')
    const localStart = Date.now()
    setStartedAtMs(localStart)
    sessionStorage.setItem('cc_job_started_at', new Date(localStart).toISOString())

    try {
      const r = await fetch('/api/execute', { method: 'POST' })
      const data = await r.json()

      if (data.status === 'already_running') {
        const start = parseStartMs(data.execution_time) || localStart
        setJobId(data.job_id)
        setStartedAtMs(start)
        sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
        connectSSE(data.job_id)
        fetchJobs()
        return
      }

      if (!r.ok) {
        setLogs([{ time: new Date().toLocaleTimeString(), level: 'error', message: '启动采集失败', step: '错误', source: '', status: 'failed' }])
        setRunning(false)
        return
      }

      setJobId(data.job_id)
      const start = parseStartMs(data.execution_time) || localStart
      setStartedAtMs(start)
      sessionStorage.setItem('cc_job_id', data.job_id)
      sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
      sessionOwned.current = data.job_id
      connectSSE(data.job_id)
    } catch (e: any) {
      setLogs([{ time: new Date().toLocaleTimeString(), level: 'error', message: `启动失败: ${e.message}`, step: '错误', source: '', status: 'failed' }])
      setRunning(false)
    }
  }

  // 停止采集：调用后端取消接口 + 清除 session 防重连
  const stopCollect = async () => {
    const jid = jobId || activeJob?.job_id
    if (!jid) return

    // 立即清除 sessionStorage 防止 fetchJobs 重连
    sessionStorage.removeItem('cc_job_id')
    sessionOwned.current = null
    manualStopRef.current = true

    try {
      const r = await fetch(`/api/execute/${jid}/cancel`, { method: 'POST' })
      if (r.ok) {
        message.success('采集已中止')
      } else {
        message.warning('中断请求发送失败')
      }
    } catch (e) {
      message.error('无法连接到服务器')
    }
    // 关闭前端 SSE 连接
    eventSourceRef.current?.close()
    eventSourceRef.current = null
    setRunning(false)
    setCurrentStep('')
    // 延迟刷新状态确认 DB 已更新
    setTimeout(fetchJobs, 3000)
  }

  const formatElapsed = (sec: number) => {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return m > 0 ? `${m}分${s}秒` : `${s}秒`
  }

  const jobColumns = [
    {
      title: '执行时间', dataIndex: 'execution_time', key: 'time', width: 160,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
      sorter: (a: JobRecord, b: JobRecord) => a.execution_time.localeCompare(b.execution_time),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (s: string) => {
        const cfg = statusConfig[s] || { color: 'default' as const, icon: null, label: s }
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>
      },
    },
    {
      title: '阶段', dataIndex: 'current_stage', key: 'stage', width: 90,
      render: (s: string) => s ? <span style={{ fontSize: 12 }}>{stageLabels[s] || s}</span> : '-',
    },
    {
      title: '采集量', dataIndex: 'total_items_collected', key: 'total', width: 70,
    },
    {
      title: '重要', dataIndex: 'important_items_found', key: 'important', width: 60,
    },
    {
      title: '渠道', key: 'channels', width: 200,
      render: (_: any, r: JobRecord) => (
        <Space size={2} wrap>
          {r.channels_succeeded?.map((ch: string) => (
            <Tag key={ch} color="green" style={{ fontSize: 11 }}>✅ {ch}</Tag>
          ))}
          {r.channels_failed?.map((ch: string) => (
            <Tag key={ch} color="red" style={{ fontSize: 11 }}>❌ {ch}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '耗时', dataIndex: 'duration_seconds', key: 'duration', width: 80,
      render: (d: number) => d ? formatElapsed(Math.round(d)) : '-',
    },
    {
      title: '备注', dataIndex: 'error_message', key: 'error', width: 150, ellipsis: true,
      render: (msg: string) => msg ? (
        <span style={{ color: msg.includes('中断') ? '#faad14' : '#ff4d4f', fontSize: 12 }}>{msg}</span>
      ) : '-',
    },
  ]

  return (
    <div>
      {/* ====== 活跃任务卡片 ====== */}
      {(running || activeJob) && (
        <Card
          style={{ marginBottom: 16, border: running ? '2px solid #1890ff' : '2px solid #faad14' }}
          title={
            <Space>
              {running ? (
                <SyncOutlined spin style={{ color: '#1890ff' }} />
              ) : (
                <WarningOutlined style={{ color: '#faad14' }} />
              )}
              <span style={{ color: running ? '#1890ff' : '#faad14' }}>
                {running ? '当前运行任务' : '后台运行中任务'}
              </span>
              {running && <Tag color="processing">本标签页</Tag>}
              {!running && activeJob && <Tag color="warning">其他标签页</Tag>}
            </Space>
          }
          extra={
            running ? (
              <Button danger size="small" onClick={stopCollect}>中断采集</Button>
            ) : (
              <Button size="small" onClick={() => {
                setJobId(activeJob!.job_id)
                sessionStorage.setItem('cc_job_id', activeJob!.job_id)
                sessionOwned.current = activeJob!.job_id
                const start = parseStartMs(activeJob!.execution_time) || parseStartMs(sessionStorage.getItem('cc_job_started_at')) || Date.now()
                setStartedAtMs(start)
                sessionStorage.setItem('cc_job_started_at', new Date(start).toISOString())
                setRunning(true)
                setCurrentStep(activeJob!.current_stage || 'starting')
                connectSSE(activeJob!.job_id)
              }}>接管任务</Button>
            )
          }
        >
          <Row gutter={[16, 16]}>
            <Col xs={12} sm={6}>
              <Statistic
                title="任务ID"
                value={activeJob?.job_id || jobId || ''}
                valueStyle={{ fontSize: 14, fontFamily: 'monospace' }}
              />
            </Col>
            <Col xs={12} sm={4}>
              <Statistic
                title="当前阶段"
                value={stageLabels[currentStep] || currentStep || (activeJob?.current_stage ? stageLabels[activeJob.current_stage] || activeJob.current_stage : '初始化')}
                valueStyle={{ fontSize: 16, color: '#1890ff' }}
              />
            </Col>
            <Col xs={12} sm={4}>
              <Statistic
                title="已运行"
                value={formatElapsed(elapsed)}
                valueStyle={{ fontSize: 16 }}
                suffix={<SyncOutlined spin />}
              />
            </Col>
            <Col xs={12} sm={5}>
              <Statistic
                title="采集数量"
                value={activeJob?.total_items_collected || (logs.filter(l => l.step === '采集' && l.status === 'success').length > 0 ? '...' : 0)}
                valueStyle={{ fontSize: 16 }}
              />
            </Col>
            <Col xs={24} sm={5}>
              <Progress percent={100} status="active" strokeColor={{ from: '#108ee9', to: '#87d068' }} showInfo={false} style={{ marginTop: 8 }} />
            </Col>
          </Row>
          <div style={{ marginTop: 12 }}>
            {['starting', 'collecting', 'cleaning', 'screening', 'analyzing', 'summarizing', 'reporting', 'notifying', 'completed'].map(stage => {
              const activeStage = currentStep || activeJob?.current_stage || ''
              const isActive = activeStage === stage
              const isDone = stageOrder.indexOf(stage) < stageOrder.indexOf(activeStage)
              const isPending = !isActive && !isDone
              return (
                <Tag key={stage}
                  color={isActive ? 'processing' : isDone ? 'green' : 'default'}
                  style={{ opacity: isPending ? 0.4 : 1, marginBottom: 4 }}
                >
                  {stageLabels[stage] || stage}
                </Tag>
              )
            })}
          </div>
        </Card>
      )}

      {/* ====== 操作按钮 ====== */}
      <Card style={{ marginBottom: 16 }}>
        <Space size="middle" align="center">
          <Button
            type="primary" size="large"
            icon={running ? <SyncOutlined spin /> : <PlayCircleOutlined />}
            onClick={startCollect}
            disabled={running}
          >
            {running ? '采集中...' : '执行采集'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchJobs} loading={jobsLoading}>
            刷新
          </Button>
          {!running && (
            <span style={{ color: '#999', fontSize: 13 }}>
              {activeJob ? '上次任务仍在后台运行中' : '点击开始新一轮情报采集'}
            </span>
          )}
        </Space>
      </Card>

      {/* ====== 实时日志 ====== */}
      <Card
        title={
          <Space>
            <span>📋 实时日志</span>
            {running && <Tag color="processing">收集中...</Tag>}
            {logs.length > 0 && <span style={{ fontWeight: 'normal', fontSize: 13, color: '#999' }}>共 {logs.length} 条</span>}
            <span style={{ fontWeight: 'normal', fontSize: 11, color: '#bbb' }}>（上滚可暂停自动滚动）</span>
          </Space>
        }
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: 0 } }}
      >
        <div
          ref={logContainerRef}
          onScroll={handleLogScroll}
          style={{
            height: 350, overflow: 'auto', background: '#1e1e1e', color: '#d4d4d4',
            fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
            fontSize: 13, lineHeight: 1.8, padding: '12px 16px', borderRadius: '0 0 8px 8px',
          }}
        >
          {logs.length === 0 ? (
            <div style={{ color: '#666', textAlign: 'center', paddingTop: 150 }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>📡</div>
              <div>点击「执行采集」开始采集情报</div>
              <div style={{ fontSize: 12, marginTop: 4 }}>实时日志将在此显示</div>
            </div>
          ) : (
            logs.map((log, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, padding: '1px 0', alignItems: 'baseline' }}>
                <span style={{ color: '#666', minWidth: 68, flexShrink: 0, fontSize: 12 }}>{log.time}</span>
                <span style={{ minWidth: 16, flexShrink: 0, textAlign: 'center' }}>
                  {log.level === 'success' ? '✅' : log.level === 'error' ? '❌' : log.level === 'warning' ? '⚠️' : 'ℹ️'}
                </span>
                {log.step && (
                  <span style={{
                    color: stepColors[log.step] || '#888',
                    background: (stepColors[log.step] || '#333') + '22',
                    padding: '0 5px', borderRadius: 3, fontSize: 11,
                    minWidth: 48, textAlign: 'center', flexShrink: 0,
                    alignSelf: 'flex-start', marginTop: 2,
                  }}>
                    {log.step}
                  </span>
                )}
                {log.source && (
                  <span style={{ color: '#ce9178', minWidth: 56, flexShrink: 0, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    [{log.source}]
                  </span>
                )}
                <span style={{
                  color: log.level === 'error' ? '#f44747' :
                    log.level === 'warning' ? '#cca700' :
                      log.level === 'success' ? '#6a9955' : '#d4d4d4',
                  wordBreak: 'break-all',
                }}>
                  {log.message}
                </span>
              </div>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </Card>

      {/* ====== 历史记录 ====== */}
      <Card title="📜 历史采集记录" loading={jobsLoading}
        extra={<Button size="small" onClick={fetchJobs} icon={<ReloadOutlined />}>刷新</Button>}
      >
        <Table
          dataSource={jobs}
          columns={jobColumns}
          rowKey="job_id"
          pagination={{ pageSize: 15, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          size="small"
          scroll={{ x: 1000 }}
          locale={{ emptyText: '暂无采集记录' }}
        />
      </Card>
    </div>
  )
}

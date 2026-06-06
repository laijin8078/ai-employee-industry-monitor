import { Row, Col, Card, Statistic, Button, Tag, Spin } from 'antd'
import {
  ReloadOutlined, ThunderboltOutlined, RiseOutlined,
  FileProtectOutlined, ExperimentOutlined, DashboardOutlined,
} from '@ant-design/icons'
import { useState, useEffect, useMemo } from 'react'

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

export default function Dashboard() {
  const [loading, setLoading] = useState(false)
  const [latestReport, setLatestReport] = useState<any>(null)

  useEffect(() => { fetchLatestReport() }, [])

  const fetchLatestReport = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/reports/latest')
      if (response.ok) setLatestReport(await response.json())
    } catch (error) { console.error(error) }
    finally { setLoading(false) }
  }

  const handleExecute = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/execute', { method: 'POST' })
      if (response.ok) {
        alert('采集已启动，请前往「采集日志」查看实时进度')
        setTimeout(fetchLatestReport, 8000)
      }
    } catch (error) { console.error(error) }
    finally { setLoading(false) }
  }

  const parsed = useMemo(() => {
    if (!latestReport?.summary) return { header: '', items: [] }
    return parseSummary(latestReport.summary)
  }, [latestReport?.summary])

  const counts = latestReport?.category_counts || {}

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
                onClick={handleExecute} loading={loading} block
                style={{
                  height: 48, fontWeight: 600, fontSize: 15,
                  borderRadius: 10, marginBottom: 16,
                }}
              >
                立即执行采集
              </Button>
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

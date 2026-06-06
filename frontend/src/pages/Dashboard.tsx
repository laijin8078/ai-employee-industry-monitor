import { Row, Col, Card, Statistic, Button, Tag } from 'antd'
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useState, useEffect, useMemo } from 'react'

const categoryColors: Record<string, string> = {
  '竞品动态': '#1890ff', '行业政策': '#52c41a', '行业动态': '#faad14', '技术突破': '#722ed1'
}

function parseSummary(summary: string) {
  // 「标题」（分类） 格式
  const items: { title: string; category: string }[] = []
  const regex = /「([^」]+)」(?:（([^）]+)）)?/g
  let match
  while ((match = regex.exec(summary)) !== null) {
    items.push({ title: match[1], category: match[2] || '未分类' })
  }
  // 去掉匹配部分，剩下的就是头部文字
  const header = summary.replace(/[；;]?「[^」]+」(?:（[^）]+)）?/g, '').replace(/[；;]\s*$/, '').trim()
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
        alert('采集已启动，请稍后刷新查看结果')
        setTimeout(fetchLatestReport, 5000)
      }
    } catch (error) { console.error(error) }
    finally { setLoading(false) }
  }

  const parsed = useMemo(() => {
    if (!latestReport?.summary) return { header: '', items: [] }
    return parseSummary(latestReport.summary)
  }, [latestReport?.summary])

  const counts = latestReport?.category_counts || {}

  return (
    <div>
      {/* ====== 统计卡片 ====== */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable><Statistic title="📊 总情报数" value={latestReport?.totalCount || 0} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable><Statistic title="🏢 竞品动态" value={counts['竞品动态'] || 0} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable><Statistic title="📜 行业政策" value={counts['行业政策'] || 0} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable><Statistic title="🔬 技术突破" value={counts['技术突破'] || 0} valueStyle={{ color: '#722ed1' }} /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* ====== 本期摘要 ====== */}
        <Col xs={24} lg={16}>
          <Card
            title="📋 最新报告摘要"
            loading={loading}
            extra={latestReport ? <Tag color="blue">{latestReport.date}</Tag> : undefined}
          >
            {parsed.header || parsed.items.length > 0 ? (
              <div>
                {/* 头部 */}
                {parsed.header && (
                  <div style={{
                    backgroundColor: '#fff7e6', padding: '12px 16px', borderRadius: 6,
                    borderLeft: '4px solid #faad14', marginBottom: 20, fontSize: 15, fontWeight: 500, color: '#ad6800'
                  }}>
                    <ThunderboltOutlined style={{ marginRight: 6 }} />
                    {parsed.header}
                  </div>
                )}

                {/* 情报列表 */}
                {parsed.items.map((item, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'flex-start', gap: 12,
                    padding: '12px 0', borderBottom: i < parsed.items.length - 1 ? '1px solid #f0f0f0' : 'none'
                  }}>
                    <span style={{
                      width: 24, height: 24, minWidth: 24, borderRadius: '50%',
                      background: categoryColors[item.category] || '#999',
                      color: 'white', textAlign: 'center', lineHeight: '24px',
                      fontSize: 12, fontWeight: 'bold'
                    }}>
                      {i + 1}
                    </span>
                    <div style={{ flex: 1, lineHeight: 1.6 }}>
                      <span style={{ fontSize: 14, color: '#262626' }}>{item.title}</span>
                    </div>
                    <Tag color={categoryColors[item.category]} style={{ marginLeft: 8, flexShrink: 0 }}>
                      {item.category}
                    </Tag>
                  </div>
                ))}

                {/* 底部统计 */}
                {parsed.items.length === 0 && parsed.header && (
                  <p style={{ color: '#999', textAlign: 'center', padding: 20 }}>暂无详细条目</p>
                )}
              </div>
            ) : (
              <p style={{ textAlign: 'center', color: '#999', padding: 40 }}>暂无报告数据，请点击右侧「立即执行采集」</p>
            )}
          </Card>
        </Col>

        {/* ====== 操作面板 ====== */}
        <Col xs={24} lg={8}>
          <Card title="⚙️ 快捷操作">
            <Button type="primary" size="large" icon={<ReloadOutlined />}
              onClick={handleExecute} loading={loading} block style={{ marginBottom: 16, height: 48 }}>
              立即执行采集
            </Button>

            <div style={{
              background: '#f6ffed', padding: '12px 16px', borderRadius: 6,
              border: '1px solid #b7eb8f', marginBottom: 12
            }}>
              <div style={{ fontSize: 13, color: '#52c41a', fontWeight: 500, marginBottom: 6 }}>📅 定时计划</div>
              <div style={{ fontSize: 13, color: '#333' }}>每两周周一 09:00 自动执行</div>
            </div>

            <div style={{
              background: '#e6f7ff', padding: '12px 16px', borderRadius: 6,
              border: '1px solid #91d5ff'
            }}>
              <div style={{ fontSize: 13, color: '#1890ff', fontWeight: 500, marginBottom: 6 }}>📊 分类概览</div>
              {Object.entries(counts).length > 0 ? (
                Object.entries(counts).map(([cat, cnt]) => (
                  <div key={cat} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
                    <Tag color={categoryColors[cat]}>{cat}</Tag>
                    <strong>{cnt as number} 条</strong>
                  </div>
                ))
              ) : (
                <span style={{ fontSize: 13, color: '#999' }}>暂无数据</span>
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

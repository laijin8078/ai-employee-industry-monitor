import { useParams, useNavigate } from 'react-router-dom'
import { Card, Row, Col, Button, Spin, Divider, Tag } from 'antd'
import { ArrowLeftOutlined, DownloadOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'

interface Intelligence {
  id: string; title: string; category: string; summary: string
  impact: string; strategy: string; priority: string; source: string
}

export default function ReportDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [report, setReport] = useState<any>(null)

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const r = await fetch(`/api/reports/${id}`)
        if (r.ok) setReport(await r.json())
      } catch (e) { console.error(e) }
      finally { setLoading(false) }
    })()
  }, [id])

  if (loading) return <Spin size="large" style={{ display: 'flex', justifyContent: 'center', marginTop: 50 }} />
  if (!report) return <Card>报告不存在</Card>

  const priorityColors: any = { '高': 'red', '中': 'orange', '低': 'green' }
  const categoryColors: any = { '竞品动态': 'blue', '行业政策': 'green', '行业动态': 'orange', '技术突破': 'purple' }

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/reports')}>返回列表</Button>
      <Card style={{ marginTop: 16 }} title={`📄 报告详情 - ${report.date}`}>
        <h3>📝 本期摘要</h3>
        <p style={{ lineHeight: 1.8, padding: 12, background: '#fafafa', borderRadius: 6, borderLeft: '4px solid #faad14' }}>
          {report.summary}
        </p>
        <Divider />
        <h3>📊 情报详情 ({report.items?.length || 0} 条)</h3>
        {(report.items || []).map((item: Intelligence, i: number) => (
          <div key={item.id} style={{ marginBottom: 16, padding: 16, background: '#fafafa', borderRadius: 6, border: '1px solid #e8e8e8', borderLeft: '4px solid #1890ff' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 10 }}>
              <span style={{ width: 28, height: 28, background: '#1890ff', color: 'white', borderRadius: '50%', textAlign: 'center', lineHeight: '28px', fontSize: 13, fontWeight: 'bold', marginRight: 10, flexShrink: 0 }}>
                {i + 1}
              </span>
              <div style={{ flex: 1 }}>
                <h4 style={{ margin: '0 0 6px 0', fontSize: 15 }}>{item.title}</h4>
                <Tag color={categoryColors[item.category]}>{item.category}</Tag>
                <Tag color={priorityColors[item.priority]}>优先级: {item.priority}</Tag>
                <Tag>{item.source}</Tag>
              </div>
            </div>
            <div style={{ marginLeft: 38, lineHeight: 1.8 }}>
              <p><strong style={{ color: '#1890ff' }}>📝 摘要：</strong> {item.summary}</p>
              <p><strong style={{ color: '#faad14' }}>⚡ 影响分析：</strong> {item.impact}</p>
              <p><strong style={{ color: '#52c41a' }}>✅ 应对策略：</strong></p>
              <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, padding: '8px 0' }}>{item.strategy}</pre>
            </div>
          </div>
        ))}
        {report.competitor_summary && Object.keys(report.competitor_summary).length > 0 && (
          <>
            <Divider />
            <h3>🏢 竞品汇总</h3>
            {Object.entries(report.competitor_summary).map(([name, summary]: [string, any]) => (
              <Card key={name} size="small" style={{ marginBottom: 8 }}>
                <strong>{name}：</strong> {summary}
              </Card>
            ))}
          </>
        )}
        {report.recommendations && (
          <>
            <Divider />
            <h3>💡 战略建议</h3>
            <p style={{ lineHeight: 1.8 }}>{report.recommendations}</p>
          </>
        )}
        <div style={{ marginTop: 20 }}>
          <Button type="primary" icon={<DownloadOutlined />} onClick={() => window.open(`/api/reports/${id}/download`)}>下载报告</Button>
        </div>
      </Card>
    </div>
  )
}

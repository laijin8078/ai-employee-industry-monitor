import { useParams, useNavigate } from 'react-router-dom'
import { Button, Card, Divider, Form, Input, Select, Space, Spin, Tag, message } from 'antd'
import { ArrowLeftOutlined, CloseOutlined, DownloadOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'

interface Intelligence {
  id: string; title: string; category: string; summary: string
  impact: string; strategy: string; priority: string; source: string
}

export default function ReportDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState(false)
  const [report, setReport] = useState<any>(null)

  const fetchReport = async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/reports/${id}`)
      if (r.ok) {
        const data = await r.json()
        setReport(data)
        form.setFieldsValue(data)
      }
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchReport()
  }, [id])

  const handleEdit = () => {
    form.setFieldsValue(report)
    setEditing(true)
  }

  const handleCancelEdit = () => {
    form.setFieldsValue(report)
    setEditing(false)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const response = await fetch(`/api/reports/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })
      if (!response.ok) throw new Error('保存失败')
      const updated = await response.json()
      setReport(updated)
      form.setFieldsValue(updated)
      setEditing(false)
      message.success('报告已保存')
    } catch (error) {
      if (error instanceof Error) message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spin size="large" style={{ display: 'flex', justifyContent: 'center', marginTop: 50 }} />
  if (!report) return <Card>报告不存在</Card>

  const priorityColors: any = { '高': 'red', '中': 'orange', '低': 'green' }
  const categoryColors: any = { '竞品动态': 'blue', '行业政策': 'green', '行业动态': 'orange', '技术突破': 'purple' }

  return (
    <div>
      <Space>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/reports')}>返回列表</Button>
        {editing ? (
          <>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
            <Button icon={<CloseOutlined />} onClick={handleCancelEdit}>取消</Button>
          </>
        ) : (
          <Button icon={<EditOutlined />} onClick={handleEdit}>编辑报告</Button>
        )}
      </Space>
      <Card
        style={{ marginTop: 16 }}
        title={`📄 报告详情 - ${report.date}`}
        extra={<Button icon={<DownloadOutlined />} onClick={() => window.open(`/api/reports/${id}/download`)}>下载报告</Button>}
      >
        <Form form={form} layout="vertical" disabled={!editing}>
          <h3>📝 本期摘要</h3>
          {editing ? (
            <Form.Item name="summary" rules={[{ required: true, message: '请输入本期摘要' }]}>
              <Input.TextArea autoSize={{ minRows: 4, maxRows: 10 }} />
            </Form.Item>
          ) : (
            <p style={{ lineHeight: 1.8, padding: 12, background: '#fafafa', borderRadius: 6, borderLeft: '4px solid #faad14' }}>
              {report.summary}
            </p>
          )}
        <Divider />
        <h3>📊 情报详情 ({report.items?.length || 0} 条)</h3>
        {(report.items || []).map((item: Intelligence, i: number) => (
          <div key={item.id} style={{ marginBottom: 16, padding: 16, background: '#fafafa', borderRadius: 6, border: '1px solid #e8e8e8', borderLeft: '4px solid #1890ff' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 10 }}>
              <span style={{ width: 28, height: 28, background: '#1890ff', color: 'white', borderRadius: '50%', textAlign: 'center', lineHeight: '28px', fontSize: 13, fontWeight: 'bold', marginRight: 10, flexShrink: 0 }}>
                {i + 1}
              </span>
              <div style={{ flex: 1 }}>
                {editing ? (
                  <>
                    <Form.Item name={['items', i, 'title']} style={{ marginBottom: 8 }} rules={[{ required: true, message: '请输入标题' }]}>
                      <Input placeholder="标题" />
                    </Form.Item>
                    <Space wrap>
                      <Form.Item name={['items', i, 'category']} style={{ marginBottom: 0 }}>
                        <Select style={{ width: 132 }} options={['竞品动态', '行业政策', '行业动态', '技术突破'].map(value => ({ value, label: value }))} />
                      </Form.Item>
                      <Form.Item name={['items', i, 'priority']} style={{ marginBottom: 0 }}>
                        <Select style={{ width: 104 }} options={['高', '中', '低'].map(value => ({ value, label: `优先级: ${value}` }))} />
                      </Form.Item>
                      <Form.Item name={['items', i, 'source']} style={{ marginBottom: 0 }}>
                        <Input placeholder="来源" style={{ width: 220 }} />
                      </Form.Item>
                    </Space>
                  </>
                ) : (
                  <>
                    <h4 style={{ margin: '0 0 6px 0', fontSize: 15 }}>{item.title}</h4>
                    <Tag color={categoryColors[item.category]}>{item.category}</Tag>
                    <Tag color={priorityColors[item.priority]}>优先级: {item.priority}</Tag>
                    <Tag>{item.source}</Tag>
                  </>
                )}
              </div>
            </div>
            <div style={{ marginLeft: 38, lineHeight: 1.8 }}>
              {editing ? (
                <>
                  <Form.Item label="摘要" name={['items', i, 'summary']}>
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
                  </Form.Item>
                  <Form.Item label="影响分析" name={['items', i, 'impact']}>
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
                  </Form.Item>
                  <Form.Item label="应对策略" name={['items', i, 'strategy']}>
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} />
                  </Form.Item>
                </>
              ) : (
                <>
                  <p><strong style={{ color: '#1890ff' }}>📝 摘要：</strong> {item.summary}</p>
                  <p><strong style={{ color: '#faad14' }}>⚡ 影响分析：</strong> {item.impact}</p>
                  <p><strong style={{ color: '#52c41a' }}>✅ 应对策略：</strong></p>
                  <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, padding: '8px 0' }}>{item.strategy}</pre>
                </>
              )}
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
        {(editing || report.recommendations) && (
          <>
            <Divider />
            <h3>💡 战略建议</h3>
            {editing ? (
              <Form.Item name="recommendations">
                <Input.TextArea autoSize={{ minRows: 3, maxRows: 10 }} />
              </Form.Item>
            ) : (
              <p style={{ lineHeight: 1.8 }}>{report.recommendations}</p>
            )}
          </>
        )}
        </Form>
      </Card>
    </div>
  )
}

import { Card, Button, Space, Modal, Input, Spin, Row, Col, Tag } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'

export default function Config() {
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<any>(null)
  const [newKeyword, setNewKeyword] = useState('')

  useEffect(() => { fetchConfig() }, [])

  const fetchConfig = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/config')
      if (r.ok) setConfig(await r.json())
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  const save = async (c: any) => {
    await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c) })
    setConfig(c)
  }

  const addWechat = () => {
    Modal.confirm({
      title: '添加微信公众号', content: <Input placeholder="输入公众号名称" id="w_in" />,
      onOk: () => {
        const el = document.getElementById('w_in') as HTMLInputElement
        if (el?.value && config) save({ ...config, competitor_wechat: [...config.competitor_wechat, { id: Date.now().toString(), name: el.value, status: '正常' }] })
      }
    })
  }

  const addWebsite = () => {
    Modal.confirm({
      title: '添加竞品官网',
      content: <div><Input placeholder="竞品名称" id="ws_n" style={{ marginBottom: 8 }} /><Input placeholder="官网URL" id="ws_u" /></div>,
      onOk: () => {
        const n = (document.getElementById('ws_n') as HTMLInputElement)?.value
        const u = (document.getElementById('ws_u') as HTMLInputElement)?.value
        if (n && u && config) save({ ...config, competitor_websites: [...config.competitor_websites, { id: Date.now().toString(), name: n, url: u, status: '正常' }] })
      }
    })
  }

  return (
    <Spin spinning={loading}>
      <Row gutter={[16, 16]}>
        <Col xs={24}>
          <Card title="📱 微信公众号监控" extra={<Button type="primary" icon={<PlusOutlined />} onClick={addWechat}>添加</Button>}>
            {config?.competitor_wechat?.map((w: any) => (
              <div key={w.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #f0f0f0' }}>
                <span>{w.name}</span>
                <Space><Tag color="green">{w.status}</Tag>
                  <Button danger size="small" icon={<DeleteOutlined />} onClick={() => save({ ...config, competitor_wechat: config.competitor_wechat.filter((x: any) => x.id !== w.id) })} />
                </Space>
              </div>
            ))}
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="🌐 竞品官网监控" extra={<Button type="primary" icon={<PlusOutlined />} onClick={addWebsite}>添加</Button>}>
            {config?.competitor_websites?.map((s: any) => (
              <div key={s.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #f0f0f0' }}>
                <div><div><strong>{s.name}</strong></div><div style={{ fontSize: 12, color: '#999' }}>{s.url}</div></div>
                <Space><Tag color="green">{s.status}</Tag>
                  <Button danger size="small" icon={<DeleteOutlined />} onClick={() => save({ ...config, competitor_websites: config.competitor_websites.filter((x: any) => x.id !== s.id) })} />
                </Space>
              </div>
            ))}
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="🔑 行业关键词">
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <Input placeholder="输入新关键词" value={newKeyword} onChange={e => setNewKeyword(e.target.value)} onPressEnter={() => {
                if (newKeyword && config) { save({ ...config, industry_keywords: [...config.industry_keywords, newKeyword] }); setNewKeyword('') }
              }} style={{ flex: 1 }} />
              <Button type="primary" onClick={() => {
                if (newKeyword && config) { save({ ...config, industry_keywords: [...config.industry_keywords, newKeyword] }); setNewKeyword('') }
              }}>添加</Button>
            </div>
            {config?.industry_keywords?.map((k: string) => (
              <Tag key={k} closable onClose={() => save({ ...config, industry_keywords: config.industry_keywords.filter((x: string) => x !== k) })}>{k}</Tag>
            ))}
          </Card>
        </Col>
      </Row>
    </Spin>
  )
}

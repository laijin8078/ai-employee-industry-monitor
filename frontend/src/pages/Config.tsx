import { Card, Button, Space, Modal, Input, Spin, Row, Col, Tag, Empty, message } from 'antd'
import { DeleteOutlined, PlusOutlined, WechatOutlined, GlobalOutlined, KeyOutlined } from '@ant-design/icons'
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
    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(c),
    })
    if (!response.ok) {
      message.error('配置保存失败')
      return
    }
    await fetchConfig()
    message.success('配置已保存')
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

  const renderItem = (icon: React.ReactNode, name: string, subtitle: string, status: string, onDelete: () => void) => (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
      background: '#fafafa', borderRadius: 10, marginBottom: 8,
      border: '1px solid oklch(0.93 0.01 260)',
      transition: 'box-shadow 0.15s',
    }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.06)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
    >
      <div style={{
        width: 40, height: 40, borderRadius: 10, background: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 18, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
        flexShrink: 0,
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{name}</div>
        {subtitle && <div style={{ fontSize: 12, color: '#999', marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{subtitle}</div>}
      </div>
      <Tag color="green" style={{ borderRadius: 4 }}>{status}</Tag>
      <Button danger size="small" icon={<DeleteOutlined />} onClick={onDelete} style={{ borderRadius: 6 }} />
    </div>
  )

  return (
    <Spin spinning={loading}>
      <Row gutter={[20, 20]}>
        {/* WeChat */}
        <Col xs={24} lg={12}>
          <Card
            title={<Space><WechatOutlined style={{ color: '#07c160' }} /><span style={{ fontWeight: 600 }}>微信公众号监控</span></Space>}
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={addWechat} style={{ borderRadius: 6 }} size="small">添加</Button>}
            style={{ borderRadius: 12, height: '100%' }}
          >
            {config?.competitor_wechat?.length > 0 ? (
              config.competitor_wechat.map((w: any) =>
                renderItem(
                  <WechatOutlined style={{ color: '#07c160' }} />,
                  w.name, '', w.status,
                  () => save({ ...config, competitor_wechat: config.competitor_wechat.filter((x: any) => x.id !== w.id) })
                )
              )
            ) : (
              <Empty description="暂无监控公众号" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        {/* Websites */}
        <Col xs={24} lg={12}>
          <Card
            title={<Space><GlobalOutlined style={{ color: '#4b5de6' }} /><span style={{ fontWeight: 600 }}>竞品官网监控</span></Space>}
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={addWebsite} style={{ borderRadius: 6 }} size="small">添加</Button>}
            style={{ borderRadius: 12, height: '100%' }}
          >
            {config?.competitor_websites?.length > 0 ? (
              config.competitor_websites.map((s: any) =>
                renderItem(
                  <GlobalOutlined style={{ color: '#4b5de6' }} />,
                  s.name, s.url, s.status,
                  () => save({ ...config, competitor_websites: config.competitor_websites.filter((x: any) => x.id !== s.id) })
                )
              )
            ) : (
              <Empty description="暂无监控网站" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        {/* Keywords */}
        <Col xs={24}>
          <Card
            title={<Space><KeyOutlined style={{ color: '#d4a017' }} /><span style={{ fontWeight: 600 }}>行业关键词</span></Space>}
            style={{ borderRadius: 12 }}
          >
            <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
              <Input
                placeholder="输入新关键词，回车添加"
                value={newKeyword}
                onChange={e => setNewKeyword(e.target.value)}
                onPressEnter={() => {
                  if (newKeyword.trim() && config) {
                    save({ ...config, industry_keywords: [...config.industry_keywords, newKeyword.trim()] })
                    setNewKeyword('')
                  }
                }}
                style={{ flex: 1, borderRadius: 8 }}
                size="large"
              />
              <Button type="primary" size="large" onClick={() => {
                if (newKeyword.trim() && config) {
                  save({ ...config, industry_keywords: [...config.industry_keywords, newKeyword.trim()] })
                  setNewKeyword('')
                }
              }} style={{ borderRadius: 8 }}>
                添加
              </Button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {config?.industry_keywords?.length > 0 ? (
                config.industry_keywords.map((k: string) => (
                  <Tag key={k} closable
                    onClose={() => save({ ...config, industry_keywords: config.industry_keywords.filter((x: string) => x !== k) })}
                    style={{ fontSize: 13, padding: '4px 12px', borderRadius: 20 }}
                  >
                    {k}
                  </Tag>
                ))
              ) : (
                <Empty description="暂无关键词" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </Spin>
  )
}

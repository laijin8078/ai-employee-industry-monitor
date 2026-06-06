import { Card, Form, Input, Button, Select, Switch, Row, Col, Divider, message, Spin, Popconfirm } from 'antd'
import { ReloadOutlined, MailOutlined, BellOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'

const defaultSettings = {
  execution_schedule: '每两周周一 09:00',
  email_enabled: true,
  email_address: '',
  wechat_enabled: false,
  wechat_webhook: '',
  alert_level: 'medium',
}

export default function Settings() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const r = await fetch('/api/settings')
        if (r.ok) {
          const saved = await r.json()
          form.setFieldsValue(saved)
        }
      } catch (e) { console.error(e) }
      finally { setLoading(false) }
    })()
  }, [form])

  const handleSave = async (values: any) => {
    setSaving(true)
    try {
      const r = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })
      if (r.ok) message.success('设置已保存')
      else message.error('保存失败')
    } catch (e) { message.error('保存失败') }
    finally { setSaving(false) }
  }

  const handleReset = async () => {
    try {
      const r = await fetch('/api/settings/reset', { method: 'POST' })
      if (r.ok) {
        const data = await r.json()
        form.setFieldsValue(data.settings)
        message.success('已恢复默认设置')
      }
    } catch (e) { message.error('恢复失败') }
  }

  return (
    <Row gutter={[20, 20]}>
      <Col xs={24} md={16}>
        <Spin spinning={loading}>
          <Card
            title={<span style={{ fontWeight: 600, fontSize: 16 }}>⚙️ 系统设置</span>}
            extra={
              <Popconfirm title="恢复默认设置？当前设置将被覆盖。" onConfirm={handleReset} okText="确认" cancelText="取消">
                <Button icon={<ReloadOutlined />} size="small" style={{ borderRadius: 6 }}>恢复默认</Button>
              </Popconfirm>
            }
            style={{ borderRadius: 12 }}
          >
            <Form layout="vertical" form={form} onFinish={handleSave} initialValues={defaultSettings}>
              <Form.Item label={<span><ClockCircleOutlined /> 执行计划</span>} name="execution_schedule">
                <Select size="large" style={{ borderRadius: 8 }} options={[
                  { label: '每两周周一 09:00', value: '每两周周一 09:00' },
                  { label: '每周一 09:00', value: '每周一 09:00' },
                  { label: '每天 09:00', value: '每天 09:00' },
                ]} />
              </Form.Item>

              <Divider><MailOutlined /> 通知设置</Divider>
              <Form.Item label="启用邮件通知" name="email_enabled" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item label="邮件地址" name="email_address">
                <Input size="large" placeholder="receiver@example.com" style={{ borderRadius: 8 }} />
              </Form.Item>
              <Form.Item label="启用企业微信通知" name="wechat_enabled" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item label="企业微信 Webhook" name="wechat_webhook">
                <Input size="large" placeholder="https://qyapi.weixin.qq.com/..." style={{ borderRadius: 8 }} />
              </Form.Item>

              <Divider><BellOutlined /> 告警设置</Divider>
              <Form.Item label="告警级别" name="alert_level">
                <Select size="large" style={{ borderRadius: 8 }} options={[
                  { label: '仅高优先级', value: 'high' },
                  { label: '中/高优先级', value: 'medium' },
                  { label: '所有', value: 'low' },
                ]} />
              </Form.Item>

              <Form.Item>
                <Button type="primary" htmlType="submit" loading={saving} size="large"
                  style={{ borderRadius: 8, fontWeight: 600 }}>
                  保存设置
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Spin>
      </Col>

      <Col xs={24} md={8}>
        <Card title={<span style={{ fontWeight: 600 }}>📊 系统信息</span>} style={{ borderRadius: 12 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { label: '版本', value: '1.0.0' },
              { label: '最后更新', value: '2026-06-06' },
              { label: '运行模式', value: '开发模式' },
              { label: '技术栈', value: 'FastAPI + React + Ant Design' },
            ].map(item => (
              <div key={item.label} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '8px 12px', background: '#fafafa', borderRadius: 8,
                border: '1px solid oklch(0.93 0.01 260)',
              }}>
                <span style={{ color: 'oklch(0.45 0.01 260)', fontSize: 13 }}>{item.label}</span>
                <span style={{ fontWeight: 500, fontSize: 13 }}>{item.value}</span>
              </div>
            ))}
          </div>
        </Card>
      </Col>
    </Row>
  )
}

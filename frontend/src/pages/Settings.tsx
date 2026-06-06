import { Card, Form, Input, Button, Select, Switch, Row, Col, Divider, message } from 'antd'
import { useState } from 'react'

export default function Settings() {
  const [loading, setLoading] = useState(false)

  const handleSave = async (values: any) => {
    setLoading(true)
    try {
      const r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) })
      if (r.ok) message.success('设置已保存')
    } catch (e) { message.error('保存失败') }
    finally { setLoading(false) }
  }

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={16}>
        <Card title="⚙️ 系统设置">
          <Form layout="vertical" onFinish={handleSave} initialValues={{ execution_schedule: '每两周周一 09:00', email_enabled: true, wechat_enabled: false, alert_level: 'medium' }}>
            <Form.Item label="执行计划" name="execution_schedule">
              <Select options={[
                { label: '每两周周一 09:00', value: '每两周周一 09:00' },
                { label: '每周一 09:00', value: '每周一 09:00' },
                { label: '每天 09:00', value: '每天 09:00' },
              ]} />
            </Form.Item>
            <Divider>📧 通知设置</Divider>
            <Form.Item label="启用邮件通知" name="email_enabled" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item label="邮件地址" name="email_address"><Input placeholder="receiver@example.com" /></Form.Item>
            <Form.Item label="启用企业微信通知" name="wechat_enabled" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item label="企业微信 Webhook" name="wechat_webhook"><Input placeholder="https://qyapi.weixin.qq.com/..." /></Form.Item>
            <Divider>🚨 告警设置</Divider>
            <Form.Item label="告警级别" name="alert_level">
              <Select options={[
                { label: '仅高优先级', value: 'high' },
                { label: '中/高优先级', value: 'medium' },
                { label: '所有', value: 'low' },
              ]} />
            </Form.Item>
            <Form.Item><Button type="primary" htmlType="submit" loading={loading}>保存设置</Button></Form.Item>
          </Form>
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card title="📊 系统信息">
          <p><strong>版本：</strong> 1.0.0</p>
          <p><strong>最后更新：</strong> 2026-06-06</p>
          <p><strong>模式：</strong> 开发模式</p>
        </Card>
      </Col>
    </Row>
  )
}

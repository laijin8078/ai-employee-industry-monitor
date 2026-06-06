import { Link, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu } from 'antd'
import {
  DashboardOutlined, FileTextOutlined, SettingOutlined,
  RadarChartOutlined, ThunderboltOutlined,
} from '@ant-design/icons'

const { Sider, Content } = AntLayout

const menuItems = [
  { key: '/', label: <Link to="/">仪表盘</Link>, icon: <DashboardOutlined /> },
  { key: '/reports', label: <Link to="/reports">报告管理</Link>, icon: <FileTextOutlined /> },
  { key: '/collection', label: <Link to="/collection">采集日志</Link>, icon: <ThunderboltOutlined /> },
  { key: '/config', label: <Link to="/config">监控配置</Link>, icon: <RadarChartOutlined /> },
  { key: '/settings', label: <Link to="/settings">系统设置</Link>, icon: <SettingOutlined /> },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      {/* ====== Sidebar ====== */}
      <Sider width={220} style={{
        background: 'oklch(0.12 0.02 260)',
        boxShadow: '2px 0 24px rgba(0,0,0,0.12)',
        position: 'relative', zIndex: 10,
      }}>
        {/* Logo */}
        <div style={{
          padding: '24px 20px 20px',
          borderBottom: '1px solid oklch(0.22 0.03 260)',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{
              width: 32, height: 32, borderRadius: 8,
              background: 'linear-gradient(135deg, oklch(0.55 0.2 260), oklch(0.48 0.22 290))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16,
            }}>🔍</span>
            <div>
              <div style={{ color: '#fff', fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>
                情报系统
              </div>
              <div style={{ color: 'oklch(0.55 0.03 260)', fontSize: 11, fontWeight: 400 }}>
                Intelligence Monitor
              </div>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          style={{
            background: 'transparent',
            borderInlineEnd: 'none',
            marginTop: 8,
            fontSize: 14,
          }}
        />
      </Sider>

      {/* ====== Main ====== */}
      <AntLayout style={{ background: 'oklch(0.97 0.005 260)' }}>
        {/* Top bar */}
        <div style={{
          background: '#fff',
          padding: '0 28px',
          height: 52,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
          borderBottom: '1px solid oklch(0.93 0.01 260)',
          position: 'sticky', top: 0, zIndex: 5,
        }}>
          <h1 style={{
            margin: 0, fontSize: 15, fontWeight: 600,
            color: 'oklch(0.2 0.01 260)',
            letterSpacing: '-0.01em',
          }}>
            竞品与行业动态情报 · AI 员工
          </h1>
          <span style={{ fontSize: 12, color: 'oklch(0.5 0.01 260)' }}>
            v1.0
          </span>
        </div>

        {/* Content */}
        <Content style={{ padding: '24px 28px', minHeight: 360 }}>
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

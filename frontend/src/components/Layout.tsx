import { Link, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu } from 'antd'
import { DashboardOutlined, FileTextOutlined, SettingOutlined, BgColorsOutlined } from '@ant-design/icons'

const { Header, Sider, Content } = AntLayout

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  const menuItems = [
    { key: '/', label: <Link to="/">仪表盘</Link>, icon: <DashboardOutlined /> },
    { key: '/reports', label: <Link to="/reports">报告管理</Link>, icon: <FileTextOutlined /> },
    { key: '/config', label: <Link to="/config">监控配置</Link>, icon: <BgColorsOutlined /> },
    { key: '/settings', label: <Link to="/settings">系统设置</Link>, icon: <SettingOutlined /> },
  ]

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" width={200}>
        <div style={{ textAlign: 'center', padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.2)' }}>
          <h2 style={{ color: 'white', fontSize: '16px', margin: 0 }}>🔍 情报系统</h2>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[location.pathname]} items={menuItems} />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 20px', boxShadow: '0 2px 8px rgba(0,0,0,0.1)', display: 'flex', alignItems: 'center' }}>
          <h1 style={{ margin: 0, fontSize: '18px' }}>竞品与行业动态情报AI员工</h1>
        </Header>
        <Content style={{ margin: '20px', padding: '20px', background: '#fff', borderRadius: '4px', minHeight: 360 }}>
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

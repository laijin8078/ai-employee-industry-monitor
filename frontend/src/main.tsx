import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        token: {
          fontFamily: `'Segoe UI', system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif`,
          borderRadius: 6,
          colorPrimary: '#4b5de6',
          colorSuccess: '#2e8b57',
          colorWarning: '#d4a017',
          colorError: '#c4423a',
          colorInfo: '#4b5de6',
          colorBgContainer: '#ffffff',
          colorBgLayout: '#f5f4f7',
          fontSize: 14,
          wireframe: false,
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)

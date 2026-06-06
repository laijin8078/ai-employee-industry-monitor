import { Table, Card, Button, Space, Modal, Tag } from 'antd'
import { DeleteOutlined, EyeOutlined, DownloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'

export default function Reports() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [reports, setReports] = useState<any[]>([])

  useEffect(() => { fetchReports() }, [])

  const fetchReports = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/reports')
      if (response.ok) setReports(await response.json())
    } catch (error) { console.error('Failed to fetch reports:', error) }
    finally { setLoading(false) }
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除', content: '确定要删除这份报告吗？',
      onOk: async () => {
        await fetch(`/api/reports/${id}`, { method: 'DELETE' })
        fetchReports()
      }
    })
  }

  const columns = [
    { title: '报告日期', dataIndex: 'date', key: 'date' },
    { title: '情报数量', dataIndex: 'total_count', key: 'total_count' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={s === 'completed' ? 'green' : 'blue'}>{s === 'completed' ? '已完成' : s}</Tag> },
    {
      title: '操作', key: 'action',
      render: (_: any, r: any) => (
        <Space size="small">
          <Button type="primary" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/reports/${r.id}`)}>查看</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => window.open(`/api/reports/${r.id}/download`)}>下载</Button>
          <Button danger size="small" icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      )
    }
  ]

  return (
    <Card title="📑 报告管理" loading={loading}>
      <Table dataSource={reports} columns={columns} rowKey="id" pagination={{ pageSize: 10 }} />
    </Card>
  )
}

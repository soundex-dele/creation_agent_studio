import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Popconfirm, Spin, Tag, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Delegate } from '@/types/delegate';
import './Delegates.css';

const DelegatesPage = () => {
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [items, setItems] = useState<Delegate[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    try {
      setItems(await api.get<Delegate[]>(`/organizations/${organizationId}/delegates`));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  const start = async (item: Delegate) => {
    try {
      const conversation = await api.post<{ id: number }>('/conversations/', {
        title: '', agent_id: item.id,
      });
      navigate(`/delegates/${item.id}/tasks/${conversation.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '无法创建分身任务');
    }
  };

  const remove = async (id: number) => {
    if (!organizationId) return;
    try {
      await api.delete(`/organizations/${organizationId}/delegates/${id}`);
      message.success('AI 分身已删除');
      await load();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    }
  };

  return (
    <div className="delegates-page">
      <div className="delegates-heading">
        <div><h1>AI 分身</h1><p>创建代表你的总指挥，规划并调度智能体和应用完成复杂任务。</p></div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/delegates/new')}>新建分身</Button>
      </div>
      {loading ? <Spin size="large" /> : items.length === 0 ? (
        <Empty description="还没有 AI 分身" />
      ) : (
        <div className="delegate-grid">
          {items.map((item) => (
            <article className="delegate-card" key={item.id}>
              <div className="delegate-icon">{item.icon || '🧭'}</div>
              <div className="delegate-card-copy">
                <div className="delegate-card-title">
                  <strong>{item.name}</strong>
                  <Tag>{item.visibility === 'private' ? '仅自己' : '组织共享'}</Tag>
                </div>
                <p>{item.description || '暂无说明'}</p>
                <small>{item.agent_ids.length} 个智能体 · {item.application_ids.length} 个应用</small>
              </div>
              <div className="delegate-card-actions">
                {item.can_run && item.active_revision_id && (
                  <Button type="primary" icon={<SendOutlined />} onClick={() => void start(item)}>交代任务</Button>
                )}
                {item.can_edit && <Button icon={<EditOutlined />} onClick={() => navigate(`/delegates/${item.id}`)}>配置</Button>}
                {item.can_edit && (
                  <Popconfirm title="删除这个 AI 分身？" onConfirm={() => void remove(item.id)}>
                    <Button danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
};

export default DelegatesPage;

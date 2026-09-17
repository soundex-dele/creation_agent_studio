import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Empty, Popconfirm, Spin, Tag, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, RightOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Delegate, DelegateInstance } from '@/types/delegate';
import './Delegates.css';

const instanceTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
}).format(new Date(value));

const DelegatesPage = () => {
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [items, setItems] = useState<Delegate[]>([]);
  const [instances, setInstances] = useState<DelegateInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [summoningId, setSummoningId] = useState<number | null>(null);
  const [deletingInstanceId, setDeletingInstanceId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    try {
      const [delegates, conversations] = await Promise.all([
        api.get<Delegate[]>(`/organizations/${organizationId}/delegates`),
        api.get<DelegateInstance[]>('/conversations/', { agent_kind: 'supervisor' }),
      ]);
      setItems(delegates);
      setInstances(conversations);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载 AI 分身失败');
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  const instancesByDelegate = useMemo(() => instances.reduce<Record<number, DelegateInstance[]>>(
    (result, instance) => {
      if (instance.agent) (result[instance.agent.id] ||= []).push(instance);
      return result;
    },
    {},
  ), [instances]);

  const summon = async (item: Delegate) => {
    setSummoningId(item.id);
    try {
      const conversation = await api.post<DelegateInstance>('/conversations/', {
        title: '', agent_id: item.id,
      });
      navigate(`/delegates/${item.id}/tasks/${conversation.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '召唤分身实例失败');
    } finally {
      setSummoningId(null);
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

  const removeInstance = async (instanceId: number) => {
    setDeletingInstanceId(instanceId);
    try {
      await api.delete(`/conversations/${instanceId}/delete_conversation/`);
      setInstances((current) => current.filter((instance) => instance.id !== instanceId));
      message.success('分身实例已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除分身实例失败');
    } finally {
      setDeletingInstanceId(null);
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
          {items.map((item) => {
            const delegateInstances = instancesByDelegate[item.id] || [];
            return (
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
              <div className="delegate-instance-section">
                <div className="delegate-instance-heading">
                  <span>分身实例</span>
                  <Tag bordered={false}>{delegateInstances.length}</Tag>
                </div>
                {delegateInstances.length === 0 ? (
                  <div className="delegate-instance-empty">召唤一个实例，然后向它交代任务</div>
                ) : delegateInstances.map((instance) => (
                  <div className="delegate-instance-item" key={instance.id}>
                    <button
                      type="button"
                      className="delegate-instance-open"
                      onClick={() => navigate(`/delegates/${item.id}/tasks/${instance.id}`)}
                    >
                      <span className="delegate-instance-copy">
                        <strong>{instance.title || `分身实例 #${instance.id}`}</strong>
                        <small>{instance.last_message?.content || '尚未交代任务'} · {instanceTime(instance.updated_at)}</small>
                      </span>
                      <RightOutlined />
                    </button>
                    <Popconfirm
                      title="删除这个分身实例？"
                      description="聊天记录和实例任务入口将被删除。"
                      onConfirm={() => void removeInstance(instance.id)}
                    >
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        loading={deletingInstanceId === instance.id}
                        aria-label={`删除 ${instance.title || `分身实例 #${instance.id}`}`}
                      />
                    </Popconfirm>
                  </div>
                ))}
              </div>
              <div className="delegate-card-actions">
                {item.can_run && item.active_revision_id && (
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    loading={summoningId === item.id}
                    onClick={() => void summon(item)}
                  >召唤</Button>
                )}
                {item.can_edit && <Button icon={<EditOutlined />} onClick={() => navigate(`/delegates/${item.id}`)}>配置</Button>}
                {item.can_edit && (
                  <Popconfirm title="删除这个 AI 分身？" onConfirm={() => void remove(item.id)}>
                    <Button danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default DelegatesPage;

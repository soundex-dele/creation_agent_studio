import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Empty, Popconfirm, Spin, Switch, Tag, message } from 'antd';
import { CompassOutlined, DeleteOutlined, EditOutlined, PlusOutlined, RightOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Delegate, DelegateInstance } from '@/types/delegate';
import WorkspaceHeader from '@/components/Workspace/WorkspaceHeader';
import './Delegates.css';

const instanceTime = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
}).format(new Date(value));

const DelegatesPage = () => {
  const navigate = useNavigate();
  const { organizations, currentOrganizationId: organizationId } = useOrganizationStore();
  const user = useAuthStore((state) => state.user);
  const currentRole = organizations.find((item) => item.id === organizationId)?.role;
  const canCreateAgent = user?.role === 'admin'
    || ['owner', 'admin', 'developer'].includes(currentRole ?? '');
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

  const toggle = async (item: Delegate, isActive: boolean) => {
    if (!organizationId) return;
    try {
      const updated = await api.patch<Delegate>(
        `/organizations/${organizationId}/delegates/${item.id}/status`,
        { is_active: isActive },
      );
      setItems((current) => current.map((value) => (
        value.id === updated.id ? updated : value
      )));
      message.success(`AI 分身已${isActive ? '启用' : '停用'}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新状态失败');
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
    <div className="delegates-page workspace-page">
      <WorkspaceHeader
        icon={<CompassOutlined />} eyebrow="智能协作" title="AI 分身"
        description="把任务交给你的专属分身，让它规划步骤、调度智能体与应用，协同完成工作。"
        loading={loading}
        action={canCreateAgent && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/delegates/new')}>新建分身</Button>}
        metrics={[
          { label: '全部分身', value: items.length, hint: '你的专属协作团队' },
          { label: '已启用', value: items.filter(item => item.is_active).length, hint: '当前启用的分身' },
          { label: '分身实例', value: instances.length, hint: '保留任务上下文' },
        ]}
      />
      <div className="workspace-section-heading"><h2>我的分身</h2><span>配置职责，或召唤实例开始协作</span></div>
      {loading ? <div className="workspace-empty"><Spin size="large" /></div> : items.length === 0 ? (
        <div className="workspace-empty"><Empty description="还没有 AI 分身，创建后即可开始协作" /></div>
      ) : (
        <div className="delegate-grid">
          {items.map((item) => {
            const delegateInstances = instancesByDelegate[item.id] || [];
            return (
              <article className="delegate-card" key={item.id}>
              <div className="delegate-icon" aria-hidden="true">{item.icon || <CompassOutlined />}</div>
              <div className="delegate-card-copy">
                <div className="delegate-card-title">
                  <h3>{item.name}</h3>
                  <Tag>{item.visibility === 'private' ? '仅自己' : '组织共享'}</Tag>
                  <Tag color={item.is_active ? 'green' : 'default'}>{item.is_active ? '已启用' : '已停用'}</Tag>
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
                {item.can_toggle && (
                  <Switch
                    checked={item.is_active}
                    checkedChildren="启用"
                    unCheckedChildren="停用"
                    onChange={(checked) => void toggle(item, checked)}
                    aria-label={`${item.name}启用状态`}
                  />
                )}
                {item.can_edit && <Button icon={<EditOutlined />} onClick={() => navigate(`/delegates/${item.id}`)}>配置</Button>}
                {item.can_delete && (
                  <Popconfirm title="删除这个 AI 分身？" onConfirm={() => void remove(item.id)}>
                    <Button danger icon={<DeleteOutlined />} aria-label={`删除 ${item.name}`} />
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

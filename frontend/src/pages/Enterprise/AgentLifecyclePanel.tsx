import { useCallback, useEffect, useState, type Key } from 'react';
import {
  Alert, Button, Card, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table,
  Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined, EditOutlined, LockOutlined } from '@ant-design/icons';
import { api } from '@/services/api';
import AgentEditorModal from '@/components/Agents/AgentEditorModal';
import BulkResourcePermissionModal from '@/components/Permissions/BulkResourcePermissionModal';
import ResourcePermissionModal, {
  type ResourceVisibility,
} from '@/components/Permissions/ResourcePermissionModal';

type Row = Record<string, any>;

interface ManagedAgent extends Row {
  id: number;
  created_by_id: number;
  name: string;
  slug: string;
  description: string;
  is_active: boolean;
  visibility: ResourceVisibility;
  can_edit: boolean;
  can_delete: boolean;
  can_toggle: boolean;
  can_manage_permissions: boolean;
}

const normalize = <T,>(value: any): T[] => (
  Array.isArray(value) ? value : value?.results ?? []
);

const asJson = (value: string, fallback: any) => (
  value?.trim() ? JSON.parse(value) : fallback
);

const accessLabels: Record<ResourceVisibility, string> = {
  private: '仅创建者',
  restricted: '指定账号',
  organization: '组织全员',
};

export default function AgentLifecyclePanel() {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [agentId, setAgentId] = useState<number>();
  const [versions, setVersions] = useState<Row[]>([]);
  const [deployment, setDeployment] = useState<Row | null>(null);
  const [versionOpen, setVersionOpen] = useState(false);
  const [versionForm] = Form.useForm();
  const [permissionAgent, setPermissionAgent] = useState<ManagedAgent | null>(null);
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<Key[]>([]);
  const [bulkPermissionOpen, setBulkPermissionOpen] = useState(false);
  const [editingAgentId, setEditingAgentId] = useState<number | null>(null);
  const [deletingAgentId, setDeletingAgentId] = useState<number | null>(null);

  const selectedAgent = agents.find((agent) => agent.id === agentId);
  const selectedPermissionAgents = agents.filter((agent) => (
    selectedPermissionKeys.includes(agent.id)
  ));
  const canUpdateAgents = Boolean(selectedAgent?.can_edit);
  const canToggleAgents = Boolean(selectedAgent?.can_toggle);

  const loadAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const data = normalize<ManagedAgent>(await api.get('/agents/', {
        manageable: 1,
        mine: 1,
      }));
      setAgents(data);
      setAgentId((current) => (
        data.some((agent) => agent.id === current) ? current : data[0]?.id
      ));
      setSelectedPermissionKeys((current) => current.filter((key) => (
        data.some((agent) => agent.id === key && agent.can_manage_permissions)
      )));
    } finally {
      setAgentsLoading(false);
    }
  }, []);

  const loadDetails = useCallback(async () => {
    if (!agentId || selectedAgent?.is_active === false) {
      setVersions([]);
      setDeployment(null);
      return;
    }
    const [versionData, deploymentData] = await Promise.all([
      api.get(`/agents/${agentId}/versions/`),
      api.get(`/agents/${agentId}/deployment/`),
    ]);
    setVersions(versionData as Row[]);
    setDeployment(deploymentData as Row | null);
  }, [agentId, selectedAgent?.is_active]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    void loadDetails();
  }, [loadDetails]);

  const createVersion = async () => {
    try {
      const values = await versionForm.validateFields();
      for (const key of [
        'model_config', 'tool_config', 'knowledge_config',
        'guardrail_config', 'workflow_config',
      ]) {
        values[key] = asJson(
          values[key],
          ['tool_config', 'knowledge_config'].includes(key) ? [] : {},
        );
      }
      await api.post(`/agents/${agentId}/versions/`, values);
      message.success('版本草稿已创建');
      setVersionOpen(false);
      await loadDetails();
    } catch (error: any) {
      if (!error?.errorFields) message.error(error.message || 'JSON 格式错误');
    }
  };

  const act = async (version: Row, action: string, payload: Row = {}) => {
    await api.post(`/agents/${agentId}/versions/${version.id}/${action}/`, payload);
    message.success('操作成功');
    await loadDetails();
  };

  const deploy = async (version: Row) => {
    await api.post(`/agents/${agentId}/deploy/`, { version_id: version.id });
    message.success('版本已激活');
    await loadDetails();
  };

  const rollback = async () => {
    await api.post(`/agents/${agentId}/rollback/`, {});
    message.success('已回滚');
    await loadDetails();
  };

  const toggleStatus = async (isActive: boolean) => {
    if (!agentId) return;
    const updated = await api.patch<ManagedAgent>(`/agents/${agentId}/status/`, {
      is_active: isActive,
    });
    setAgents((items) => items.map((item) => (
      item.id === agentId ? { ...item, ...updated } : item
    )));
    message.success(`智能体已${isActive ? '启用' : '停用'}`);
  };

  const deleteAgent = async (id: number) => {
    setDeletingAgentId(id);
    try {
      await api.delete(`/agents/${id}/`);
      message.success('智能体已删除');
      await loadAgents();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除智能体失败');
    } finally {
      setDeletingAgentId(null);
    }
  };

  const permissionColumns: ColumnsType<ManagedAgent> = [
    {
      title: '智能体',
      dataIndex: 'name',
      render: (_, agent) => (
        <div className="enterprise-application-name">
          <strong>{agent.name}</strong>
          <Typography.Text type="secondary">{agent.description || agent.slug}</Typography.Text>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 100,
      render: (isActive: boolean) => (
        <Tag color={isActive ? 'green' : 'default'}>{isActive ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '可见权限',
      dataIndex: 'visibility',
      width: 140,
      render: (visibility: ResourceVisibility) => (
        <Tag>{accessLabels[visibility] ?? visibility}</Tag>
      ),
    },
    {
      title: '操作',
      width: 320,
      render: (_, agent) => (agent.can_edit || agent.can_delete || agent.can_manage_permissions) ? (
        <Space wrap>
          {agent.can_edit && (
            <Button
              icon={<EditOutlined aria-hidden="true" />}
              disabled={!agent.is_active}
              title={!agent.is_active ? '请先启用智能体再编辑' : undefined}
              aria-label={`编辑 ${agent.name}`}
              onClick={() => setEditingAgentId(agent.id)}
            >编辑</Button>
          )}
          {agent.can_delete && (
            <Popconfirm
              title="删除智能体"
              description={`确定删除“${agent.name}”吗？`}
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => deleteAgent(agent.id)}
            >
              <Button
                danger
                icon={<DeleteOutlined aria-hidden="true" />}
                aria-label={`删除 ${agent.name}`}
                loading={deletingAgentId === agent.id}
                disabled={deletingAgentId !== null}
              >删除</Button>
            </Popconfirm>
          )}
          {agent.can_manage_permissions && (
            <Button
              icon={<LockOutlined aria-hidden="true" />}
              onClick={() => setPermissionAgent(agent)}
            >权限设置</Button>
          )}
        </Space>
      ) : '—',
    },
  ];

  return (
    <div className="enterprise-subpanel">
      <Alert
        type="info"
        showIcon
        message="智能体管理"
        description="可执行的操作由当前组织角色和该智能体的资源授权共同决定。"
      />

      <Card title="智能体列表">
        <div className="enterprise-bulk-toolbar">
          <Typography.Text type="secondary">
            勾选智能体后可统一覆盖可见范围和账号授权，支持表头全选。
          </Typography.Text>
          <Space wrap size={12}>
            <Button
              disabled={selectedPermissionKeys.length === 0}
              onClick={() => setSelectedPermissionKeys([])}
            >
              取消选择
            </Button>
            <Button
              type="primary"
              icon={<LockOutlined aria-hidden="true" />}
              disabled={selectedPermissionKeys.length === 0}
              onClick={() => setBulkPermissionOpen(true)}
            >
              批量设置权限
              {selectedPermissionKeys.length > 0 ? `（${selectedPermissionKeys.length}）` : ''}
            </Button>
          </Space>
        </div>
        <Table<ManagedAgent>
          rowKey="id"
          loading={agentsLoading}
          dataSource={agents}
          columns={permissionColumns}
          pagination={false}
          scroll={{ x: 920 }}
          rowSelection={{
            selectedRowKeys: selectedPermissionKeys,
            onChange: setSelectedPermissionKeys,
            getCheckboxProps: (agent) => ({
              disabled: !agent.can_manage_permissions,
              'aria-label': `选择${agent.name}`,
            }),
          }}
          locale={{ emptyText: <Empty description="当前组织暂无智能体" /> }}
        />
      </Card>

      <Card
        title="智能体版本与部署"
        extra={(
          <Space wrap size={12} className="enterprise-agent-lifecycle-actions">
            <Select
              className="enterprise-agent-select"
              placeholder="选择组织智能体"
              value={agentId}
              onChange={setAgentId}
              options={agents.map((agent) => ({
                value: agent.id,
                label: `${agent.name}${agent.is_active ? '' : '（已停用）'}`,
              }))}
            />
            {canToggleAgents && (
              <Switch
                checked={Boolean(selectedAgent?.is_active)}
                checkedChildren="启用"
                unCheckedChildren="停用"
                disabled={!agentId}
                onChange={(checked) => void toggleStatus(checked)}
                aria-label={`${selectedAgent?.name ?? '智能体'}启用状态`}
              />
            )}
            {canUpdateAgents && (
              <Button
                type="primary"
                disabled={!agentId || selectedAgent?.is_active === false}
                onClick={() => {
                  versionForm.resetFields();
                  setVersionOpen(true);
                }}
              >
                新版本
              </Button>
            )}
          </Space>
        )}
      >
        <Table
          rowKey="id"
          dataSource={versions}
          scroll={{ x: 920 }}
          columns={[
            { title: '版本', dataIndex: 'version' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value) => (
                <Tag color={value === 'approved' ? 'green' : value === 'rejected' ? 'red' : 'blue'}>
                  {value}
                </Tag>
              ),
            },
            { title: '变更说明', dataIndex: 'changelog' },
            {
              title: '操作',
              width: 520,
              render: (_, version: Row) => (canUpdateAgents || canToggleAgents) ? (
                <Space wrap>
                  {canUpdateAgents && version.status === 'draft' && (
                    <Button size="small" onClick={() => act(version, 'submit')}>送审</Button>
                  )}
                  {canUpdateAgents && version.status === 'in_review' && (
                    <>
                      <Button
                        size="small"
                        type="primary"
                        onClick={() => act(version, 'review', { decision: 'approved' })}
                      >
                        批准
                      </Button>
                      <Button
                        danger
                        size="small"
                        onClick={() => act(version, 'review', { decision: 'rejected' })}
                      >
                        拒绝
                      </Button>
                    </>
                  )}
                  {canToggleAgents && (
                    <Button size="small" type="primary" onClick={() => deploy(version)}>
                      激活版本
                    </Button>
                  )}
                </Space>
              ) : '—',
            },
          ]}
          locale={{ emptyText: <Empty description="暂无版本" /> }}
        />
      </Card>

      <Card title="当前激活部署">
        <Table
          rowKey="id"
          pagination={false}
          dataSource={deployment ? [deployment] : []}
          columns={[
            { title: '当前 Revision', dataIndex: 'revision_id' },
            { title: '部署版本', dataIndex: 'version' },
            { title: '更新时间', dataIndex: 'updated_at' },
            {
              title: '操作',
              render: (_, current: Row) => canToggleAgents ? (
                <Button
                  size="small"
                  disabled={!current.previous_revision_id}
                  onClick={() => rollback()}
                >
                  回滚
                </Button>
              ) : '—',
            },
          ]}
          locale={{ emptyText: <Empty description="暂无激活部署" /> }}
        />
      </Card>

      <Modal
        title="新建智能体版本"
        open={versionOpen}
        onCancel={() => setVersionOpen(false)}
        onOk={createVersion}
        width={800}
      >
        <Form layout="vertical" form={versionForm}>
          <Form.Item name="version" label="版本号" rules={[{ required: true }]}>
            <Input placeholder="1.0.0" />
          </Form.Item>
          <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item name="changelog" label="变更说明"><Input.TextArea /></Form.Item>
          {[
            ['model_config', '{}'],
            ['tool_config', '[]'],
            ['knowledge_config', '[]'],
            ['guardrail_config', '{}'],
            ['workflow_config', '{}'],
          ].map(([key, value]) => (
            <Form.Item key={key} name={key} label={`${key}（JSON）`} initialValue={value}>
              <Input.TextArea rows={2} />
            </Form.Item>
          ))}
        </Form>
      </Modal>

      <AgentEditorModal
        agentId={editingAgentId}
        open={editingAgentId !== null}
        onClose={() => setEditingAgentId(null)}
        onSaved={async () => {
          await loadAgents();
          await loadDetails();
        }}
      />
      <ResourcePermissionModal
        resourceType="agent"
        resourceId={permissionAgent?.id ?? null}
        resourceName={permissionAgent?.name ?? ''}
        open={permissionAgent !== null}
        onClose={() => setPermissionAgent(null)}
        onSaved={loadAgents}
      />
      <BulkResourcePermissionModal
        resourceType="agent"
        resources={selectedPermissionAgents.map((agent) => ({
          id: agent.id,
          permissionId: agent.id,
          name: agent.name,
          ownerId: agent.created_by_id,
        }))}
        open={bulkPermissionOpen}
        onClose={() => setBulkPermissionOpen(false)}
        onSaved={async () => {
          await loadAgents();
          setSelectedPermissionKeys([]);
        }}
      />
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
import {
  Button, Card, Empty, Input, InputNumber, Modal, Popconfirm, Select, Spin, Switch,
  Tag, Typography, message,
} from 'antd';
import {
  AppstoreOutlined, DeleteOutlined, EditOutlined, HistoryOutlined, PlayCircleOutlined,
  PlusOutlined, PartitionOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { createIdempotencyKey } from '@/lib/idempotencyKey';
import { api } from '@/services/api';
import type {
  GuidedPrompt, Workflow, WorkflowInputValue, WorkflowRunInputField,
} from '@/types';
import {
  validateWorkflowInput,
  workflowInputDefaults,
  workflowInputFields,
} from '@/lib/workflowInputSchema';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';
import WorkspaceHeader from '@/components/Workspace/WorkspaceHeader';
import { WECHAT_PARALLEL_PRESET } from '@/lib/wechatParallelWorkflow';
import './Workflows.css';

const unwrap = <T,>(value: T[] | { results?: T[] }): T[] =>
  Array.isArray(value) ? value : value.results ?? [];

const wait = (milliseconds: number) => new Promise((resolve) => {
  window.setTimeout(resolve, milliseconds);
});

const promptFields = (prompt: GuidedPrompt): WorkflowRunInputField[] => (
  prompt.questions.map((question) => ({
    key: question.key,
    label: question.label,
    description: question.help_text,
    placeholder: question.placeholder,
    type: question.type === 'multi_choice' ? 'array'
      : question.type === 'number' ? 'number' : 'string',
    required: question.required,
    defaultValue: question.default_value as WorkflowInputValue | undefined,
    options: question.options.map((option) => ({
      value: option.value,
      label: option.label,
    })),
    multiline: question.type === 'text',
  }))
);

const WorkflowsPage = () => {
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<RunResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingWorkflowId, setDeletingWorkflowId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [runWorkflow, setRunWorkflow] = useState<Workflow | null>(null);
  const [runPrompt, setRunPrompt] = useState<GuidedPrompt | null>(null);
  const [runFields, setRunFields] = useState<WorkflowRunInputField[]>([]);
  const [runAnswers, setRunAnswers] = useState<Record<string, WorkflowInputValue>>({});
  const [runErrors, setRunErrors] = useState<Record<string, string>>({});
  const [preparingRunId, setPreparingRunId] = useState<string | null>(null);
  const [startingRun, setStartingRun] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [workflowResponse, runResponse] = await Promise.all([
        api.get<Workflow[] | { results?: Workflow[] }>('/workflows/'),
        organizationId
          ? api.get<RunResource[]>(`${tenantApiRoot(organizationId)}/runs`, {
              source_type: 'workflow',
            })
          : Promise.resolve([]),
      ]);
      setWorkflows(unwrap(workflowResponse));
      setRuns(unwrap(runResponse));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  const launch = async (workflow: Workflow, input: Record<string, WorkflowInputValue>) => {
    setStartingRun(true);
    try {
      const run = await api.post<{ id: string }>(
        `/workflows/${workflow.id}/start/`,
        { input },
        { headers: { 'Idempotency-Key': createIdempotencyKey('workflow') } },
      );
      setRunWorkflow(null);
      setRunPrompt(null);
      setRunFields([]);
      setRunErrors({});
      navigate(`/runs/${run.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '工作流启动失败');
    } finally {
      setStartingRun(false);
    }
  };

  const start = async (workflow: Workflow) => {
    if (workflow.execution_mode === 'manual') {
      navigate(`/workflows/${workflow.id}/manual`);
      return;
    }
    setPreparingRunId(workflow.id);
    try {
      const detail = await api.get<Workflow>(`/workflows/${workflow.id}/`);
      const schemaFields = workflowInputFields(detail.input_schema);
      if (schemaFields.length) {
        setRunWorkflow(detail);
        setRunPrompt(null);
        setRunFields(schemaFields);
        setRunAnswers(workflowInputDefaults(schemaFields));
        setRunErrors({});
        return;
      }
      const entryStep = [...(detail.steps || [])]
        .sort((left, right) => left.order - right.order)
        .find((step) => step.depends_on.length === 0 && step.application.kind === 'chat');
      if (!entryStep || entryStep.application.kind !== 'chat') {
        await launch(detail, {});
        return;
      }
      const preferredKey = String(
        entryStep.application.default_config.guided_entry_prompt_key || '',
      );
      const prompt = entryStep.application.guided_prompts.find((item) => (
        String(item.id || item.key) === preferredKey
      )) || entryStep.application.guided_prompts[0];
      if (!prompt) {
        await launch(detail, {});
        return;
      }
      setRunWorkflow(detail);
      setRunPrompt(prompt);
      const fields = promptFields(prompt);
      setRunFields(fields);
      setRunAnswers(workflowInputDefaults(fields));
      setRunErrors({});
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '读取工作流输入配置失败');
    } finally {
      setPreparingRunId(null);
    }
  };

  const setRunAnswer = (key: string, value: WorkflowInputValue | null) => {
    setRunAnswers((current) => ({
      ...current,
      [key]: value === null ? '' : value,
    }));
    setRunErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  const submitAutomaticRun = async () => {
    if (!runWorkflow) return;
    const errors = validateWorkflowInput(runFields, runAnswers);
    if (Object.keys(errors).length) {
      setRunErrors(errors);
      message.warning('请检查工作流输入');
      return;
    }
    await launch(runWorkflow, runAnswers);
  };

  const remove = async (workflow: Workflow) => {
    setDeletingWorkflowId(workflow.id);
    try {
      await api.delete(`/workflows/${workflow.id}/`);
      setWorkflows((current) => current.filter((item) => item.id !== workflow.id));
      message.success('工作流已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除工作流失败');
    } finally {
      setDeletingWorkflowId(null);
    }
  };

  const removeRun = async (run: RunResource) => {
    if (!organizationId) return;
    setDeletingRunId(run.id);
    try {
      const endpoint = `${tenantApiRoot(organizationId)}/runs/${run.id}`;
      let deleted = false;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const result = await api.delete<{
          deletion_pending?: boolean;
          detail?: string;
        } | undefined>(endpoint);
        if (!result?.deletion_pending) {
          deleted = true;
          break;
        }
        await wait(500);
      }
      if (!deleted) {
        throw new Error('取消工作流超时，请稍后重试');
      }
      setRuns((current) => current.filter((item) => item.id !== run.id));
      message.success('执行历史及关联对话已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '删除执行历史失败');
    } finally {
      setDeletingRunId(null);
    }
  };

  return (
    <div className="workflows-page workspace-page">
      <WorkspaceHeader
        icon={<PartitionOutlined />} eyebrow="流程编排" title="工作流"
        description="连接应用与步骤，把重复的工作整理成清晰、可复用的业务流程。"
        loading={loading}
        action={<div className="workflow-create-actions">
          <Button icon={<PartitionOutlined />} onClick={() => navigate(`/workflows/new?preset=${WECHAT_PARALLEL_PRESET}`)}>
            公众号图文并行预设
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/workflows/new')}>新建工作流</Button>
        </div>}
        metrics={[
          { label: '全部工作流', value: workflows.length, hint: '沉淀可复用的流程' },
          { label: '自动执行', value: workflows.filter(item => item.execution_mode !== 'manual').length, hint: '一键启动完整流程' },
          { label: '执行记录', value: runs.length, hint: '查看过程与产出' },
        ]}
      />
      <div className="workspace-section-heading"><h2>我的工作流</h2><span>按需选择手动操作或自动执行</span></div>
      {loading ? <div className="workflows-loading"><Spin size="large" /></div> : (
        <>
          {workflows.length === 0 ? <div className="workspace-empty"><Empty description="还没有工作流，连接应用来创建第一个流程" /></div>
            : <div className="workflow-grid">{workflows.map((workflow) => (
              <Card key={workflow.id} className="workflow-card">
                <div className="workflow-card-heading">
                  <div className="workflow-card-icon" aria-hidden="true">{workflow.icon || <PartitionOutlined />}</div>
                  <h3>{workflow.name}</h3>
                  {workflow.can_delete && (
                    <Popconfirm
                      title="删除工作流"
                      description={`确定删除“${workflow.name}”吗？此操作不可撤销。`}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => remove(workflow)}
                    >
                      <Button
                        type="text"
                        className="workflow-card-delete"
                        danger
                        icon={<DeleteOutlined />}
                        loading={deletingWorkflowId === workflow.id}
                        aria-label={`删除 ${workflow.name}`}
                        title="删除工作流"
                      />
                    </Popconfirm>
                  )}
                </div>
                <Typography.Paragraph
                  className="workflow-card-description"
                  ellipsis={{ rows: 2, expandable: 'collapsible', symbol: expanded => expanded ? '收起' : '展开' }}
                >
                  {workflow.description || '尚未添加说明，可在编辑中补充流程用途。'}
                </Typography.Paragraph>
                <div className="workflow-card-meta">
                  <span className="workflow-card-count"><AppstoreOutlined aria-hidden="true" /><strong>{workflow.step_count || 0}</strong>个应用</span>
                  <Tag color={workflow.execution_mode === 'manual' ? 'gold' : 'blue'}>
                    {workflow.execution_mode === 'manual' ? '手动执行' : '自动执行'}
                  </Tag>
                </div>
                <div className="workflow-card-actions">
                  <Button icon={<EditOutlined />} onClick={() => navigate(`/workflows/${workflow.id}/edit`)}>编辑</Button>
                  <Button
                    type="primary"
                    icon={workflow.execution_mode === 'manual'
                      ? <AppstoreOutlined /> : <PlayCircleOutlined />}
                    disabled={!workflow.step_count}
                    title={!workflow.step_count ? '请先编辑工作流并添加应用' : undefined}
                    loading={preparingRunId === workflow.id}
                    onClick={() => start(workflow)}
                  >
                    {workflow.execution_mode === 'manual' ? '打开' : '运行'}
                  </Button>
                </div>
              </Card>
            ))}</div>}

          <section className="workflow-history">
            <div className="workflow-history-heading">
              <div><HistoryOutlined /><h2>执行历史</h2></div>
              <span>回顾每一次执行的进度与结果</span>
            </div>
            {runs.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无执行历史" />
            ) : (
              <div className="workflow-history-list">
                {runs.map((run) => {
                  const definition = run.definition_snapshot as {
                    workflow_name?: string;
                    workflow_steps?: unknown[];
                    execution_mode?: 'manual' | 'automatic';
                  };
                  return (
                    <div key={run.id} className="workflow-history-item">
                      <button
                        type="button"
                        className="workflow-history-link"
                        onClick={() => navigate(definition.execution_mode === 'manual'
                          ? `/workflows/${run.source_id}/manual?runId=${run.id}`
                          : `/runs/${run.id}`)}
                      >
                        <span className="workflow-history-icon"><HistoryOutlined /></span>
                        <span className="workflow-history-copy">
                          <strong>{definition.workflow_name || `Workflow ${run.source_id || ''}`}</strong>
                          <small>{new Date(run.created_at || '').toLocaleString()}</small>
                        </span>
                        <span className="workflow-history-progress">
                          {definition.execution_mode === 'manual' ? '手动执行 · ' : ''}
                          {definition.workflow_steps?.length || 0} 个应用
                        </span>
                        <span className={`workflow-history-status workflow-history-status--${run.status}`}>
                          {run.status === 'succeeded' ? '已完成'
                            : run.status === 'failed' ? '失败'
                              : run.status === 'cancelled' ? '已取消' : '进行中'}
                        </span>
                      </button>
                      {run.can_delete && (
                        <Popconfirm
                          title="删除执行历史"
                          description={['succeeded', 'failed', 'cancelled'].includes(run.status)
                            ? '确定删除这条执行历史吗？关联对话、消息、事件和产物也会删除，且无法恢复。'
                            : '执行仍在进行。删除时会先自动取消或结束工作流，再删除关联对话、消息、事件和产物。'}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => removeRun(run)}
                        >
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingRunId === run.id}
                            aria-label={`删除 ${definition.workflow_name || '工作流'} 的执行历史`}
                          />
                        </Popconfirm>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
      <Modal
        title={runPrompt?.title || `运行 ${runWorkflow?.name || '工作流'}`}
        open={Boolean(runWorkflow && runFields.length)}
        okText="开始自动运行"
        cancelText="取消"
        width={680}
        confirmLoading={startingRun}
        onOk={submitAutomaticRun}
        onCancel={() => {
          if (startingRun) return;
          setRunWorkflow(null);
          setRunPrompt(null);
          setRunFields([]);
          setRunErrors({});
        }}
      >
        <p className="workflow-run-form-description">
          {runPrompt?.description || '填写本次运行输入；映射到该字段的应用会收到相同内容。'}
        </p>
        <div className="workflow-run-form">
          {runFields.map((field) => {
            const errorId = `workflow-input-${field.key}-error`;
            return (
            <label className={`workflow-run-field${runErrors[field.key] ? ' has-error' : ''}`} key={field.key}>
              <span>{field.label}{field.required && <b>*</b>}</span>
              {field.description && <small>{field.description}</small>}
              {field.options?.length ? (
                <Select
                  id={`workflow-input-${field.key}`}
                  aria-describedby={runErrors[field.key] ? errorId : undefined}
                  status={runErrors[field.key] ? 'error' : undefined}
                  mode={field.type === 'array' ? 'multiple' : undefined}
                  value={runAnswers[field.key] ?? undefined}
                  placeholder={field.placeholder}
                  options={field.options}
                  onChange={(value) => setRunAnswer(field.key, value)}
                  allowClear
                />
              ) : field.type === 'number' || field.type === 'integer' ? (
                <InputNumber
                  id={`workflow-input-${field.key}`}
                  aria-describedby={runErrors[field.key] ? errorId : undefined}
                  status={runErrors[field.key] ? 'error' : undefined}
                  value={runAnswers[field.key] as number | undefined}
                  placeholder={field.placeholder}
                  min={field.minimum}
                  max={field.maximum}
                  onChange={(value) => setRunAnswer(field.key, value)}
                />
              ) : field.type === 'boolean' ? (
                <Switch
                  id={`workflow-input-${field.key}`}
                  aria-describedby={runErrors[field.key] ? errorId : undefined}
                  checked={Boolean(runAnswers[field.key])}
                  onChange={(value) => setRunAnswer(field.key, value)}
                />
              ) : !field.multiline ? (
                <Input
                  id={`workflow-input-${field.key}`}
                  aria-describedby={runErrors[field.key] ? errorId : undefined}
                  status={runErrors[field.key] ? 'error' : undefined}
                  value={(runAnswers[field.key] as string | undefined) || ''}
                  placeholder={field.placeholder}
                  maxLength={field.maxLength}
                  onChange={(event) => setRunAnswer(field.key, event.target.value)}
                />
              ) : (
                <Input.TextArea
                  id={`workflow-input-${field.key}`}
                  aria-describedby={runErrors[field.key] ? errorId : undefined}
                  status={runErrors[field.key] ? 'error' : undefined}
                  value={(runAnswers[field.key] as string | undefined) || ''}
                  placeholder={field.placeholder}
                  maxLength={field.maxLength}
                  autoSize={{ minRows: 4, maxRows: 10 }}
                  onChange={(event) => setRunAnswer(field.key, event.target.value)}
                />
              )}
              {runErrors[field.key] && (
                <small id={errorId} className="workflow-run-field-error" role="alert">
                  {runErrors[field.key]}
                </small>
              )}
            </label>
            );
          })}
        </div>
      </Modal>
    </div>
  );
};

export default WorkflowsPage;

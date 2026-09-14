import { useEffect, useMemo, useState } from 'react';
import { Button, Card, Empty, Input, InputNumber, Segmented, Select, Spin, message } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/services/api';
import type { ApplicationRuntime, AppItem, Workflow, WorkflowStep } from '@/types';
import './Workflows.css';

const unwrap = <T,>(value: T[] | { results?: T[] }): T[] =>
  Array.isArray(value) ? value : value.results ?? [];

const WorkflowEditorPage = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [apps, setApps] = useState<AppItem[]>([]);
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [selectedApplication, setSelectedApplication] = useState<number>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.get<Workflow>(`/workflows/${id}/`),
      api.get<any[]>('/apps/'),
    ]).then(([workflowData, appData]) => {
      setWorkflow(workflowData);
      setSteps(workflowData.steps || []);
      setApps(unwrap(appData).map((app: any) => ({
        id: app.slug, name: app.name, description: app.description,
        category: app.category_slug, icon: app.icon, color: app.color,
        tags: app.tags || [], applicationId: app.id,
        rendererKey: app.renderer_key, kind: app.kind,
      })));
    });
  }, [id]);

  const choices = useMemo(() => apps.filter((app) => app.applicationId).map((app) => ({
    value: app.applicationId!, label: `${app.icon || '◈'} ${app.name}`,
  })), [apps]);

  if (!workflow) return <div className="workflows-loading"><Spin size="large" /></div>;

  const addStep = () => {
    const app = apps.find((item) => item.applicationId === selectedApplication);
    if (!app || !selectedApplication) return;
    const key = `step-${Date.now()}`;
    const applicationBase = {
      id: selectedApplication,
      application_id: selectedApplication,
      application_slug: app.id,
      application_name: app.name,
      application_description: app.description,
      application_icon: app.icon,
      application_color: app.color,
      executor_key: undefined,
      default_config: {},
    };
    const application: ApplicationRuntime = app.kind === 'chat'
      ? {
          ...applicationBase,
          kind: 'chat',
          renderer_key: 'chat',
          chat_profile: {
            allow_agent_selection: false,
            allow_skill_selection: true,
            allow_extra_skills: false,
            starter_layout: 'cards',
          },
          agent_bindings: [],
          skill_bindings: [],
          guided_prompts: [],
        }
      : {
          ...applicationBase,
          kind: app.kind === 'custom' ? 'custom' : 'task',
          renderer_key: app.rendererKey || 'generic-task',
        };
    setSteps((current) => [...current, {
      id: `draft-${Date.now()}`,
      key,
      name: app.name,
      order: current.length,
      config: {},
      depends_on: current.length ? [current[current.length - 1].key] : [],
      condition: {},
      max_attempts: 1,
      application_id: selectedApplication,
      application,
    }]);
    setSelectedApplication(undefined);
  };

  const move = (index: number, delta: number) => {
    const next = [...steps];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next.map((step, order) => ({ ...step, order })));
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/workflows/${workflow.id}/`, {
        name: workflow.name,
        description: workflow.description || '',
        icon: workflow.icon || '🔀',
        execution_mode: workflow.execution_mode,
        is_public: workflow.is_public,
        steps: steps.map((step, order) => ({
          application_id: step.application_id || step.application.id,
          key: step.key,
          name: step.name || step.application.application_name,
          order,
          config: step.config || {},
          depends_on: step.depends_on || [],
          condition: step.condition || {},
          max_attempts: step.max_attempts || 1,
        })),
      });
      message.success('工作流已保存');
      navigate('/workflows');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="workflow-editor">
      <div className="workflows-heading">
        <div>
          <Input className="workflow-name-input" value={workflow.name}
            onChange={(event) => setWorkflow({ ...workflow, name: event.target.value })} />
          <Input.TextArea value={workflow.description}
            placeholder="说明这个工作流要完成什么"
            onChange={(event) => setWorkflow({ ...workflow, description: event.target.value })} />
          <div className="workflow-mode-field">
            <span>执行方式</span>
            <Segmented
              value={workflow.execution_mode}
              options={[
                { label: '手动执行', value: 'manual' },
                { label: '自动执行', value: 'automatic' },
              ]}
              onChange={(value) => setWorkflow({
                ...workflow,
                execution_mode: value as Workflow['execution_mode'],
              })}
            />
            <small>
              {workflow.execution_mode === 'manual'
                ? '运行时从左侧列表选择应用并手动操作。'
                : '运行时按照步骤依赖自动执行。'}
            </small>
          </div>
        </div>
        <Button type="primary" loading={saving} onClick={save}>保存工作流</Button>
      </div>
      <Card title="添加应用" className="workflow-add-card">
        <div className="workflow-add-row">
          <Select showSearch value={selectedApplication} onChange={setSelectedApplication}
            placeholder="选择应用" options={choices} />
          <Button icon={<PlusOutlined />} disabled={!selectedApplication} onClick={addStep}>添加</Button>
        </div>
      </Card>
      <div className="workflow-step-list">
        {steps.length === 0 ? <Empty description="请添加至少一个应用" />
          : steps.map((step, index) => (
            <Card key={step.id} className="workflow-editor-step">
              <span className="workflow-step-index">{index + 1}</span>
              <span className="workflow-step-icon">{step.application.application_icon}</span>
              <div className="workflow-step-copy">
                <strong>{step.name || step.application.application_name}</strong>
                <span>{step.application.application_description}</span>
                {workflow.execution_mode === 'automatic' && (
                  <>
                    <Select
                      mode="multiple"
                      value={step.depends_on || []}
                      placeholder="无依赖（可并行）"
                      options={steps.filter((candidate) => candidate.key !== step.key).map((candidate) => ({
                        value: candidate.key,
                        label: candidate.name || candidate.application.application_name,
                      }))}
                      onChange={(depends_on) => setSteps((current) => current.map((item) =>
                        item.key === step.key ? { ...item, depends_on } : item))}
                    />
                    <span>
                      节点重试：<InputNumber min={1} max={10} value={step.max_attempts || 1}
                        onChange={(value) => setSteps((current) => current.map((item) =>
                          item.key === step.key ? { ...item, max_attempts: value || 1 } : item))} />
                    </span>
                  </>
                )}
              </div>
              <Button icon={<ArrowUpOutlined />} disabled={index === 0}
                onClick={() => move(index, -1)} />
              <Button icon={<ArrowDownOutlined />} disabled={index === steps.length - 1}
                onClick={() => move(index, 1)} />
              <Button danger icon={<DeleteOutlined />}
                onClick={() => setSteps((current) => current.filter((_, i) => i !== index)
                  .map((item, order) => ({
                    ...item,
                    order,
                    depends_on: (item.depends_on || []).filter((key) => key !== step.key),
                    condition: item.condition?.source === 'dependency'
                      && item.condition?.step === step.key ? {} : item.condition,
                  })))} />
            </Card>
          ))}
      </div>
    </div>
  );
};

export default WorkflowEditorPage;

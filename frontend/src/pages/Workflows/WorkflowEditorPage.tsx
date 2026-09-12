import { useEffect, useMemo, useState } from 'react';
import { Button, Card, Empty, Input, Select, Spin, message } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/services/api';
import type { AppItem, ApplicationRuntime, Workflow, WorkflowStep } from '@/types';
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
    const base = {
      id: selectedApplication, application_id: selectedApplication, application_slug: app.id,
      application_name: app.name, application_description: app.description,
      application_icon: app.icon, application_color: app.color,
      renderer_key: app.rendererKey || 'generic-task', default_config: {},
    };
    const runtime: ApplicationRuntime = app.kind === 'chat'
      ? {
          ...base,
          kind: 'chat',
          renderer_key: 'chat',
          chat_profile: {
            allow_agent_selection: false,
            allow_skill_selection: true,
            allow_extra_skills: false,
            starter_layout: 'cards',
          },
          agent_bindings: [], skill_bindings: [], guided_prompts: [],
        }
      : { ...base, kind: app.kind === 'custom' ? 'custom' : 'task' };
    setSteps((current) => [...current, {
      id: `draft-${Date.now()}`,
      name: app.name,
      order: current.length,
      config: {},
      application_id: selectedApplication,
      application: runtime,
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
        is_public: workflow.is_public,
        steps: steps.map((step, order) => ({
          application_id: step.application_id || step.application.id,
          name: step.name || step.application.application_name,
          order,
          config: step.config || {},
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
              </div>
              <Button icon={<ArrowUpOutlined />} disabled={index === 0}
                onClick={() => move(index, -1)} />
              <Button icon={<ArrowDownOutlined />} disabled={index === steps.length - 1}
                onClick={() => move(index, 1)} />
              <Button danger icon={<DeleteOutlined />}
                onClick={() => setSteps((current) => current.filter((_, i) => i !== index)
                  .map((item, order) => ({ ...item, order })))} />
            </Card>
          ))}
      </div>
    </div>
  );
};

export default WorkflowEditorPage;

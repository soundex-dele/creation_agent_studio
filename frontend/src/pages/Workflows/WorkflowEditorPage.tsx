import { useEffect, useRef, useState } from 'react';
import { Button, Card, Empty, Input, InputNumber, Modal, Segmented, Select, Spin, message } from 'antd';
import type { InputRef } from 'antd';
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
  const [saving, setSaving] = useState(false);
  const [appPickerOpen, setAppPickerOpen] = useState(false);
  const [addingApplicationId, setAddingApplicationId] = useState<number | null>(null);
  const nameInputRef = useRef<InputRef>(null);

  useEffect(() => {
    const loadApps = () => api.get<any[]>('/apps/').then((appData) => {
      setApps(unwrap(appData).map((app: any) => ({
        id: app.slug, name: app.name, description: app.description,
        category: app.category_slug, icon: app.icon, color: app.color,
        tags: app.tags || [], applicationId: app.id,
        rendererKey: app.renderer_key, kind: app.kind,
      })));
    });
    if (!id) {
      setWorkflow({
        id: '',
        name: '',
        description: '',
        icon: '🔀',
        execution_mode: 'manual',
        output_mapping: {},
        is_public: false,
        steps: [],
      });
      setSteps([]);
      void loadApps();
      return;
    }
    Promise.all([
      api.get<Workflow>(`/workflows/${id}/`),
      loadApps(),
    ]).then(([workflowData]) => {
      setWorkflow(workflowData);
      setSteps(workflowData.steps || []);
    });
  }, [id]);

  if (!workflow) return <div className="workflows-loading"><Spin size="large" /></div>;

  const addStep = async (applicationId: number) => {
    const app = apps.find((item) => item.applicationId === applicationId);
    if (!app) return;
    setAddingApplicationId(applicationId);
    try {
      const application = await api.get<ApplicationRuntime>(`/apps/${app.id}/`);
      const stamp = Date.now();
      setSteps((current) => [...current, {
        id: `draft-${stamp}`,
        key: `step-${stamp}`,
        name: app.name,
        order: current.length,
        config: {},
        depends_on: current.length ? [current[current.length - 1].key] : [],
        condition: {},
        max_attempts: 1,
        application_id: applicationId,
        application,
      }]);
      setAppPickerOpen(false);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '应用详情加载失败，请重试');
    } finally {
      setAddingApplicationId(null);
    }
  };

  const move = (index: number, delta: number) => {
    const next = [...steps];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next.map((step, order) => ({ ...step, order })));
  };

  const updateStepAutomation = (
    stepKey: string,
    updater: (automation: Record<string, any>) => Record<string, any>,
  ) => {
    setSteps((current) => current.map((step) => {
      if (step.key !== stepKey) return step;
      const config = { ...(step.config || {}) };
      config.automation = updater({ ...((config.automation as Record<string, any>) || {}) });
      return { ...step, config };
    }));
  };

  const setOutputAlias = (stepKey: string, alias: string) => {
    const current = { ...(workflow.output_mapping || {}) };
    Object.entries(current).forEach(([name, binding]) => {
      const source = typeof binding === 'string' ? binding : binding?.from;
      if (source === `steps.${stepKey}.output.result`) delete current[name];
    });
    if (alias.trim()) {
      current[alias.trim()] = { from: `steps.${stepKey}.output.result` };
    }
    setWorkflow({ ...workflow, output_mapping: current });
  };

  const save = async () => {
    if (!workflow.name.trim()) {
      message.warning('请填写工作流名称');
      nameInputRef.current?.focus();
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: workflow.name.trim(),
        description: workflow.description || '',
        icon: workflow.icon || '🔀',
        execution_mode: workflow.execution_mode,
        output_mapping: workflow.output_mapping || {},
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
      };
      if (id) {
        await api.put(`/workflows/${workflow.id}/`, payload);
      } else {
        await api.post<Workflow>('/workflows/', payload);
      }
      message.success(id ? '工作流已保存' : '工作流已创建');
      navigate('/workflows');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '工作流保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="workflow-editor">
      <div className="workflows-heading">
        <div>
          <Input ref={nameInputRef} autoFocus={!id} className="workflow-name-input"
            value={workflow.name} placeholder="工作流名称"
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
        <Button type="primary" loading={saving} onClick={save}>
          {id ? '保存工作流' : '创建工作流'}
        </Button>
      </div>
      <div className="workflow-add-actions">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAppPickerOpen(true)}>
          添加应用
        </Button>
      </div>
      <Modal
        title="选择应用"
        open={appPickerOpen}
        footer={null}
        width={760}
        onCancel={() => setAppPickerOpen(false)}
      >
        {apps.some((app) => app.applicationId) ? (
          <div className="workflow-app-picker-grid">
            {apps.filter((app) => app.applicationId).map((app) => (
              <button
                key={app.applicationId}
                type="button"
                className="workflow-app-picker-item"
                disabled={addingApplicationId !== null}
                onClick={() => void addStep(app.applicationId!)}
              >
                <span className="workflow-app-picker-icon">
                  {addingApplicationId === app.applicationId ? <Spin size="small" /> : (app.icon || '◈')}
                </span>
                <span className="workflow-app-picker-copy">
                  <strong>{app.name}</strong>
                  <small>{app.description || '暂无应用说明'}</small>
                </span>
              </button>
            ))}
          </div>
        ) : <Empty description="暂无可添加的应用" />}
      </Modal>
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
                    {step.application.kind === 'chat'
                      && step.application.guided_prompts.length > 0 && (() => {
                        const automation = (
                          (step.config?.automation as Record<string, any>) || {}
                        );
                        const selectedPromptKey = String(
                          automation.guided_prompt_key
                          || step.application.default_config.guided_entry_prompt_key
                          || step.application.guided_prompts[0].key,
                        );
                        const prompt = step.application.guided_prompts.find((item) => (
                          String(item.id || item.key) === selectedPromptKey
                        )) || step.application.guided_prompts[0];
                        const answers = (automation.answers || {}) as Record<string, any>;
                        return (
                          <div className="workflow-step-mapping">
                            <strong>自动输入映射</strong>
                            <Select
                              value={selectedPromptKey}
                              options={step.application.guided_prompts.map((item) => ({
                                value: String(item.id || item.key), label: item.title,
                              }))}
                              onChange={(guided_prompt_key) => updateStepAutomation(
                                step.key,
                                (value) => ({ ...value, guided_prompt_key, answers: {} }),
                              )}
                            />
                            {prompt.questions.map((question) => {
                              const binding = answers[question.key];
                              const selected = binding?.from
                                ? `from:${binding.from}`
                                : Object.prototype.hasOwnProperty.call(binding || {}, 'value')
                                  ? 'fixed' : 'default';
                              return (
                                <div className="workflow-mapping-row" key={question.key}>
                                  <span>{question.label}</span>
                                  <Select
                                    value={selected}
                                    options={[
                                      { value: 'default', label: '应用默认值' },
                                      {
                                        value: `from:workflow.input.${question.key}`,
                                        label: `启动输入 · ${question.label}`,
                                      },
                                      ...step.depends_on.map((dependency) => ({
                                        value: `from:steps.${dependency}.output.result`,
                                        label: `节点输出 · ${steps.find((item) => item.key === dependency)?.name || dependency}`,
                                      })),
                                      { value: 'fixed', label: '固定值' },
                                    ]}
                                    onChange={(value) => updateStepAutomation(step.key, (current) => {
                                      const nextAnswers = { ...(current.answers || {}) };
                                      if (value === 'default') delete nextAnswers[question.key];
                                      else if (value === 'fixed') nextAnswers[question.key] = { value: '' };
                                      else nextAnswers[question.key] = { from: value.replace(/^from:/, '') };
                                      return { ...current, guided_prompt_key: selectedPromptKey, answers: nextAnswers };
                                    })}
                                  />
                                  {selected === 'fixed' && (
                                    <Input
                                      value={String(binding?.value || '')}
                                      placeholder="固定输入值"
                                      onChange={(event) => updateStepAutomation(step.key, (current) => ({
                                        ...current,
                                        guided_prompt_key: selectedPromptKey,
                                        answers: {
                                          ...(current.answers || {}),
                                          [question.key]: { value: event.target.value },
                                        },
                                      }))}
                                    />
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })()}
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
      {workflow.execution_mode === 'automatic' && steps.length > 0 && (
        <Card title="最终成品汇总" className="workflow-output-mapping">
          <p>为需要交付的节点结果填写字段名；留空的节点仍保留在 outputs 中。</p>
          {steps.map((step) => {
            const source = `steps.${step.key}.output.result`;
            const alias = Object.entries(workflow.output_mapping || {}).find(([, binding]) => (
              (typeof binding === 'string' ? binding : binding?.from) === source
            ))?.[0] || '';
            return (
              <label key={step.key}>
                <span>{step.name || step.application.application_name}</span>
                <Input
                  value={alias}
                  placeholder="例如 article、layout、cover"
                  onChange={(event) => setOutputAlias(step.key, event.target.value)}
                />
              </label>
            );
          })}
        </Card>
      )}
    </div>
  );
};

export default WorkflowEditorPage;

import { useEffect, useRef, useState } from 'react';
import {
  Button, Card, Checkbox, Empty, Input, InputNumber, Modal, Segmented, Select, Spin,
  message,
} from 'antd';
import type { InputRef } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/services/api';
import type { ApplicationRuntime, AppItem, Workflow, WorkflowStep } from '@/types';
import {
  emptyWorkflowInputSchema,
  workflowInputFields,
  workflowInputProperty,
  workflowInputSourceOptions,
} from '@/lib/workflowInputSchema';
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
        input_schema: emptyWorkflowInputSchema(),
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
        input_mapping: {},
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

  const updateStepInputMapping = (
    stepKey: string,
    targetKey: string,
    binding?: { from: string } | { value: unknown },
  ) => {
    setSteps((current) => current.map((step) => {
      if (step.key !== stepKey) return step;
      const inputMapping = { ...(step.input_mapping || {}) };
      if (binding === undefined) delete inputMapping[targetKey];
      else inputMapping[targetKey] = binding;
      return { ...step, input_mapping: inputMapping };
    }));
  };

  const addWorkflowInput = () => {
    const schema = workflow.input_schema || emptyWorkflowInputSchema();
    const properties = { ...(schema.properties || {}) };
    let key = 'text';
    let suffix = 2;
    while (properties[key]) {
      key = `text_${suffix}`;
      suffix += 1;
    }
    properties[key] = {
      ...workflowInputProperty('textarea', properties.text ? `文本 ${suffix - 1}` : '原始文本'),
      description: '运行工作流时填写，可映射到多个应用并行处理。',
      'x-placeholder': '请输入需要处理的文本',
    };
    setWorkflow({
      ...workflow,
      input_schema: {
        ...schema,
        type: 'object',
        properties,
        required: [...new Set([...(schema.required || []), key])],
        additionalProperties: false,
      },
    });
  };

  const updateWorkflowInput = (
    fieldKey: string,
    patch: { key?: string; title?: string; description?: string; placeholder?: string;
      control?: 'text' | 'textarea' | 'number' | 'boolean'; required?: boolean },
  ) => {
    const schema = workflow.input_schema || emptyWorkflowInputSchema();
    const properties = { ...(schema.properties || {}) };
    const current = properties[fieldKey];
    if (!current) return;
    const nextKey = patch.key ?? fieldKey;
    if (nextKey !== fieldKey && properties[nextKey]) {
      message.warning(`输入字段 ${nextKey} 已存在`);
      return;
    }
    const currentControl = (
      current.type === 'number' || current.type === 'integer' ? 'number'
        : current.type === 'boolean' ? 'boolean'
          : current['x-control'] === 'textarea' ? 'textarea' : 'text'
    );
    const control = patch.control || currentControl;
    const nextProperty = {
      ...(patch.control && patch.control !== currentControl
        ? workflowInputProperty(control, patch.title ?? current.title ?? nextKey)
        : { ...current, title: patch.title ?? current.title ?? nextKey }),
      ...(patch.description !== undefined
        ? { description: patch.description } : current.description ? { description: current.description } : {}),
      ...(patch.placeholder !== undefined
        ? { 'x-placeholder': patch.placeholder }
        : current['x-placeholder'] ? { 'x-placeholder': current['x-placeholder'] } : {}),
    };
    const nextProperties = Object.fromEntries(Object.entries(properties).map(([key, value]) => (
      key === fieldKey ? [nextKey, nextProperty] : [key, value]
    )));
    const wasRequired = (schema.required || []).includes(fieldKey);
    const required = (schema.required || []).filter((key) => key !== fieldKey);
    if (patch.required ?? wasRequired) required.push(nextKey);

    if (nextKey !== fieldKey) {
      const previousSource = `workflow.input.${fieldKey}`;
      const nextSource = `workflow.input.${nextKey}`;
      setSteps((currentSteps) => currentSteps.map((step) => {
        const config = { ...(step.config || {}) };
        const automation = { ...((config.automation as Record<string, any>) || {}) };
        const answers = { ...((automation.answers as Record<string, any>) || {}) };
        Object.entries(answers).forEach(([answerKey, binding]) => {
          if (binding?.from === previousSource) answers[answerKey] = { ...binding, from: nextSource };
        });
        const inputMapping = { ...(step.input_mapping || {}) };
        Object.entries(inputMapping).forEach(([targetKey, binding]) => {
          if ('from' in binding && binding.from === previousSource) {
            inputMapping[targetKey] = { from: nextSource };
          }
        });
        automation.answers = answers;
        config.automation = automation;
        const condition = step.condition?.source === 'input'
          && step.condition.path === fieldKey
          ? { ...step.condition, path: nextKey } : step.condition;
        return { ...step, config, input_mapping: inputMapping, condition };
      }));
    }
    setWorkflow({
      ...workflow,
      input_schema: { ...schema, properties: nextProperties, required },
    });
  };

  const removeWorkflowInput = (fieldKey: string) => {
    const schema = workflow.input_schema || emptyWorkflowInputSchema();
    const properties = { ...(schema.properties || {}) };
    delete properties[fieldKey];
    const source = `workflow.input.${fieldKey}`;
    setSteps((current) => current.map((step) => {
      const config = { ...(step.config || {}) };
      const automation = { ...((config.automation as Record<string, any>) || {}) };
      const answers = { ...((automation.answers as Record<string, any>) || {}) };
      Object.entries(answers).forEach(([answerKey, binding]) => {
        if (binding?.from === source) delete answers[answerKey];
      });
      const inputMapping = { ...(step.input_mapping || {}) };
      Object.entries(inputMapping).forEach(([targetKey, binding]) => {
        if ('from' in binding && binding.from === source) delete inputMapping[targetKey];
      });
      automation.answers = answers;
      config.automation = automation;
      return {
        ...step,
        config,
        input_mapping: inputMapping,
        condition: step.condition?.source === 'input' && step.condition.path === fieldKey
          ? {} : step.condition,
      };
    }));
    setWorkflow({
      ...workflow,
      input_schema: {
        ...schema,
        properties,
        required: (schema.required || []).filter((key) => key !== fieldKey),
      },
    });
  };

  const save = async () => {
    if (!workflow.name.trim()) {
      message.warning('请填写工作流名称');
      nameInputRef.current?.focus();
      return;
    }
    const inputKeys = Object.keys(workflow.input_schema?.properties || {});
    const invalidInputKey = inputKeys.find((key) => !key.trim() || key.includes('.'));
    if (invalidInputKey !== undefined) {
      message.warning('输入字段 key 不能为空或包含点号');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: workflow.name.trim(),
        description: workflow.description || '',
        icon: workflow.icon || '🔀',
        execution_mode: workflow.execution_mode,
        input_schema: workflow.input_schema || emptyWorkflowInputSchema(),
        output_mapping: workflow.output_mapping || {},
        is_public: workflow.is_public,
        steps: steps.map((step, order) => ({
          application_id: step.application_id || step.application.id,
          key: step.key,
          name: step.name || step.application.application_name,
          order,
          config: step.config || {},
          input_mapping: step.input_mapping || {},
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
      {workflow.execution_mode === 'automatic' && (
        <Card
          title="工作流输入"
          className="workflow-input-schema"
          extra={<Button icon={<PlusOutlined />} onClick={addWorkflowInput}>添加输入</Button>}
        >
          <p>定义一次运行需要填写的内容；同一个输入可映射给多个无依赖应用并行处理。</p>
          {Object.entries(workflow.input_schema?.properties || {}).length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="尚未定义输入，运行时将直接启动工作流"
            >
              <Button type="primary" icon={<PlusOutlined />} onClick={addWorkflowInput}>
                添加文本输入
              </Button>
            </Empty>
          ) : (
            <div className="workflow-input-fields">
              {Object.entries(workflow.input_schema?.properties || {}).map(([fieldKey, field]) => {
                const control = field.type === 'number' || field.type === 'integer' ? 'number'
                  : field.type === 'boolean' ? 'boolean'
                    : field['x-control'] === 'textarea' ? 'textarea' : 'text';
                return (
                  <div className="workflow-input-field" key={fieldKey}>
                    <label>
                      <span>字段 key</span>
                      <Input
                        value={fieldKey}
                        aria-label={`${field.title || fieldKey}的字段 key`}
                        onChange={(event) => updateWorkflowInput(fieldKey, { key: event.target.value })}
                      />
                    </label>
                    <label>
                      <span>显示名称</span>
                      <Input
                        value={field.title || ''}
                        onChange={(event) => updateWorkflowInput(fieldKey, { title: event.target.value })}
                      />
                    </label>
                    <label>
                      <span>输入类型</span>
                      <Select
                        value={control}
                        options={[
                          { value: 'textarea', label: '长文本' },
                          { value: 'text', label: '单行文本' },
                          { value: 'number', label: '数字' },
                          { value: 'boolean', label: '开关' },
                        ]}
                        onChange={(value) => updateWorkflowInput(fieldKey, {
                          control: value as 'text' | 'textarea' | 'number' | 'boolean',
                        })}
                      />
                    </label>
                    <label className="workflow-input-field-placeholder">
                      <span>输入提示</span>
                      <Input
                        value={field['x-placeholder'] || ''}
                        onChange={(event) => updateWorkflowInput(
                          fieldKey, { placeholder: event.target.value },
                        )}
                      />
                    </label>
                    <Checkbox
                      checked={(workflow.input_schema?.required || []).includes(fieldKey)}
                      onChange={(event) => updateWorkflowInput(
                        fieldKey, { required: event.target.checked },
                      )}
                    >
                      必填
                    </Checkbox>
                    <Button
                      danger
                      type="text"
                      icon={<DeleteOutlined />}
                      aria-label={`删除输入字段 ${field.title || fieldKey}`}
                      onClick={() => removeWorkflowInput(fieldKey)}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      )}
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
                                      ...(workflowInputSourceOptions(workflow.input_schema).length
                                        ? workflowInputSourceOptions(workflow.input_schema) : [{
                                        value: `from:workflow.input.${question.key}`,
                                        label: `启动输入 · ${question.label}`,
                                      }]),
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
                    {step.application.kind !== 'chat'
                      && workflowInputFields(step.application.input_schema).length > 0 && (
                      <div className="workflow-step-mapping">
                        <strong>应用输入映射</strong>
                        {workflowInputFields(step.application.input_schema).map((target) => {
                          const binding = step.input_mapping?.[target.key];
                          const selected = binding && 'from' in binding
                            ? `from:${binding.from}`
                            : binding && 'value' in binding ? 'fixed' : 'default';
                          return (
                            <div className="workflow-mapping-row" key={target.key}>
                              <span>{target.label}</span>
                              <Select
                                value={selected}
                                options={[
                                  { value: 'default', label: '同名输入或应用默认值' },
                                  ...workflowInputSourceOptions(workflow.input_schema),
                                  ...step.depends_on.map((dependency) => ({
                                    value: `from:steps.${dependency}.output.result`,
                                    label: `节点输出 · ${steps.find((item) => (
                                      item.key === dependency
                                    ))?.name || dependency}`,
                                  })),
                                  { value: 'fixed', label: '固定值' },
                                ]}
                                onChange={(value) => {
                                  if (value === 'default') {
                                    updateStepInputMapping(step.key, target.key, undefined);
                                  } else if (value === 'fixed') {
                                    updateStepInputMapping(step.key, target.key, { value: '' });
                                  } else {
                                    updateStepInputMapping(step.key, target.key, {
                                      from: value.replace(/^from:/, ''),
                                    });
                                  }
                                }}
                              />
                              {selected === 'fixed' && (
                                <Input
                                  value={String(binding && 'value' in binding ? binding.value : '')}
                                  placeholder="固定输入值"
                                  onChange={(event) => updateStepInputMapping(
                                    step.key, target.key, { value: event.target.value },
                                  )}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}
              </div>
              <div className="workflow-step-actions">
                <Button icon={<ArrowUpOutlined />} disabled={index === 0}
                  aria-label="上移步骤" onClick={() => move(index, -1)} />
                <Button icon={<ArrowDownOutlined />} disabled={index === steps.length - 1}
                  aria-label="下移步骤" onClick={() => move(index, 1)} />
                <Button danger icon={<DeleteOutlined />} aria-label="删除步骤"
                  onClick={() => setSteps((current) => current.filter((_, i) => i !== index)
                    .map((item, order) => ({
                      ...item,
                      order,
                      depends_on: (item.depends_on || []).filter((key) => key !== step.key),
                      condition: item.condition?.source === 'dependency'
                        && item.condition?.step === step.key ? {} : item.condition,
                    })))} />
              </div>
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

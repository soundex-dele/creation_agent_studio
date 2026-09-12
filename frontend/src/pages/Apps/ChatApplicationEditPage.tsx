import { useEffect, useState } from 'react';
import {
  Button, Card, Checkbox, Form, Input, Result, Select, Space, Spin, message,
} from 'antd';
import {
  ArrowLeftOutlined, DeleteOutlined, PlusOutlined, SaveOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/services/api';
import type { ChatApplicationRuntime } from '@/types';
import './ChatApplicationEditPage.css';

type EditableApplication = ChatApplicationRuntime & { can_edit: boolean };

interface AgentOption {
  id: number;
  name: string;
  slug: string;
}

interface SkillOption {
  id: string;
  name: string;
  slug: string;
  description?: string;
}

interface ChoiceFormValue {
  value: string;
  label: string;
}

interface QuestionFormValue {
  key: string;
  label: string;
  type: 'text' | 'single_choice' | 'multi_choice' | 'number' | 'file';
  placeholder?: string;
  required?: boolean;
  options?: ChoiceFormValue[];
}

interface PromptFormValue {
  key: string;
  title: string;
  description?: string;
  icon?: string;
  prompt_template: string;
  questions?: QuestionFormValue[];
}

interface EditorValues {
  agent_id: number;
  skill_ids?: string[];
  empty_state_title?: string;
  welcome_message?: string;
  input_placeholder?: string;
  guided_entry_prompt_key?: string;
  prompts?: PromptFormValue[];
}

const unwrap = <T,>(value: T[] | { results?: T[] }): T[] =>
  Array.isArray(value) ? value : value.results ?? [];

const newKey = (prefix: string) =>
  `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

const questionTypes = [
  { value: 'text', label: '文本' },
  { value: 'single_choice', label: '单选' },
  { value: 'multi_choice', label: '多选' },
  { value: 'number', label: '数字' },
  { value: 'file', label: '文件/素材名称' },
];

const ChatApplicationEditPage = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [form] = Form.useForm<EditorValues>();
  const prompts = Form.useWatch('prompts', form) ?? [];
  const [application, setApplication] = useState<EditableApplication | null>(null);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) {
      setLoading(false);
      return;
    }
    Promise.all([
      api.get<EditableApplication>(`/apps/${id}/`),
      api.get<AgentOption[] | { results?: AgentOption[] }>('/agents/'),
      api.get<SkillOption[] | { results?: SkillOption[] }>('/apps/skills/'),
    ]).then(([app, agentResponse, skillResponse]) => {
      setApplication(app);
      setAgents(unwrap(agentResponse));
      setSkills(unwrap(skillResponse));
      form.setFieldsValue({
        agent_id: app.agent_bindings.find((item) => item.is_default)?.agent_id
          ?? app.agent_bindings[0]?.agent_id,
        skill_ids: app.skill_bindings.map((item) => item.skill_id),
        empty_state_title: app.chat_profile?.empty_state_title,
        welcome_message: app.chat_profile?.welcome_message,
        input_placeholder: app.chat_profile?.input_placeholder,
        guided_entry_prompt_key:
          typeof app.default_config.guided_entry_prompt_key === 'string'
            ? app.default_config.guided_entry_prompt_key
            : undefined,
        prompts: app.guided_prompts.map((prompt) => ({
          key: prompt.key,
          title: prompt.title,
          description: prompt.description,
          icon: prompt.icon,
          prompt_template: prompt.prompt_template,
          questions: prompt.questions.map((question) => ({
            key: question.key,
            label: question.label,
            type: question.type,
            placeholder: question.placeholder,
            required: question.required,
            options: question.options.map((option) => ({
              value: option.value,
              label: option.label,
            })),
          })),
        })),
      });
    }).catch(() => setApplication(null)).finally(() => setLoading(false));
  }, [form, id]);

  const save = async (values: EditorValues) => {
    if (!application || !id) return;
    const promptValues = values.prompts ?? [];
    const promptKeys = promptValues.map((prompt) => prompt.key);
    if (new Set(promptKeys).size !== promptKeys.length) {
      message.error('问题组标识不能重复');
      return;
    }
    if (values.guided_entry_prompt_key
        && !promptKeys.includes(values.guided_entry_prompt_key)) {
      message.error('进入页问题组已被删除，请重新选择');
      return;
    }
    for (const prompt of promptValues) {
      const questions = prompt.questions ?? [];
      const questionKeys = questions.map((question) => question.key);
      if (new Set(questionKeys).size !== questionKeys.length) {
        message.error(`“${prompt.title}”中的问题变量标识不能重复`);
        return;
      }
      for (const question of questions) {
        if (!['single_choice', 'multi_choice'].includes(question.type)) continue;
        const options = question.options ?? [];
        const optionValues = options.map((option) => option.value);
        if (options.length === 0) {
          message.error(`“${question.label}”至少需要一个选项`);
          return;
        }
        if (new Set(optionValues).size !== optionValues.length) {
          message.error(`“${question.label}”中的选项值不能重复`);
          return;
        }
      }
    }
    setSaving(true);
    try {
      const defaultConfig = { ...application.default_config };
      if (values.guided_entry_prompt_key) {
        defaultConfig.guided_entry_prompt_key = values.guided_entry_prompt_key;
      } else {
        delete defaultConfig.guided_entry_prompt_key;
      }
      await api.patch(`/apps/${id}/`, {
        default_config: defaultConfig,
        chat_profile: {
          ...application.chat_profile,
          empty_state_title: values.empty_state_title ?? '',
          welcome_message: values.welcome_message ?? '',
          input_placeholder: values.input_placeholder ?? '',
        },
        agent_bindings: [{
          agent_id: values.agent_id,
          label: agents.find((item) => item.id === values.agent_id)?.name ?? '',
          is_default: true,
          order: 0,
        }],
        skill_bindings: (values.skill_ids ?? []).map((skillId, order) => ({
          skill_id: skillId,
          mode: 'default',
          order,
        })),
        guided_prompts: promptValues.map((prompt, promptOrder) => ({
          key: prompt.key,
          title: prompt.title,
          description: prompt.description ?? '',
          icon: prompt.icon ?? '💬',
          prompt_template: prompt.prompt_template,
          action: 'preview',
          is_featured: true,
          order: promptOrder,
          questions: (prompt.questions ?? []).map((question, questionOrder) => ({
            key: question.key,
            label: question.label,
            type: question.type,
            placeholder: question.placeholder ?? '',
            required: Boolean(question.required),
            order: questionOrder,
            options: ['single_choice', 'multi_choice'].includes(question.type)
              ? (question.options ?? []).map((option, optionOrder) => ({
                value: option.value,
                label: option.label,
                order: optionOrder,
              }))
              : [],
          })),
        })),
      });
      message.success('聊天应用配置已保存');
      navigate(`/apps/${id}`);
    } catch (error: any) {
      const data = error?.response?.data;
      const detail = data?.detail
        || (data && typeof data === 'object' ? Object.values(data).flat().join('；') : '')
        || '保存失败';
      message.error(String(detail));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="chat-app-edit-loading"><Spin size="large" /></div>;
  }
  if (!application) {
    return <Result status="404" title="应用不存在" />;
  }
  if (application.kind !== 'chat') {
    return <Result status="warning" title="只有聊天应用支持此配置页" />;
  }
  if (!application.can_edit) {
    return <Result status="403" title="只有应用所有者可以编辑配置" />;
  }

  return (
    <div className="chat-app-edit-page">
      <header className="chat-app-edit-header">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/apps/${id}`)}>
          返回应用
        </Button>
        <div>
          <h1>编辑 {application.application_name}</h1>
          <p>配置进入应用时的问题、默认智能体和自动加载的 Skill。</p>
        </div>
      </header>

      <Form form={form} layout="vertical" onFinish={save} className="chat-app-edit-form">
        <Card title="聊天配置" className="chat-app-edit-card">
          <Form.Item name="agent_id" label="默认智能体" rules={[{ required: true, message: '请选择默认智能体' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="请选择智能体"
              options={agents.map((agent) => ({
                value: agent.id,
                label: `${agent.name} (${agent.slug})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="skill_ids" label="默认 Skill">
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              placeholder="选择进入对话时自动加载的 Skill"
              options={skills.map((skill) => ({
                value: skill.id,
                label: `${skill.name} (${skill.slug})`,
                title: skill.description,
              }))}
            />
          </Form.Item>
          <div className="chat-app-edit-grid">
            <Form.Item name="empty_state_title" label="空白页标题">
              <Input placeholder="例如：今天想创作什么？" />
            </Form.Item>
            <Form.Item name="input_placeholder" label="输入框提示">
              <Input placeholder="例如：描述你的创作需求…" />
            </Form.Item>
          </div>
          <Form.Item name="welcome_message" label="欢迎语">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Card>

        <Card title="问题列表" className="chat-app-edit-card">
          <Form.Item
            name="guided_entry_prompt_key"
            label="进入应用时首先显示的问题组"
            extra="不选择时进入普通聊天首页；选择后会先显示问题表单和提示词预览。"
          >
            <Select
              allowClear
              placeholder="不启用进入页问题"
              options={prompts
                .filter((prompt) => prompt?.key)
                .map((prompt) => ({ value: prompt.key, label: prompt.title || prompt.key }))}
            />
          </Form.Item>

          <Form.List name="prompts">
            {(promptFields, { add: addPrompt, remove: removePrompt }) => (
              <Space direction="vertical" size="large" className="chat-app-edit-list">
                {promptFields.map((promptField, promptIndex) => (
                  <Card
                    key={promptField.key}
                    size="small"
                    title={`问题组 ${promptIndex + 1}`}
                    extra={<Button danger type="text" icon={<DeleteOutlined />} onClick={() => removePrompt(promptField.name)}>删除</Button>}
                  >
                    <div className="chat-app-edit-grid">
                      <Form.Item
                        name={[promptField.name, 'title']}
                        label="名称"
                        rules={[{ required: true, message: '请输入问题组名称' }]}
                      >
                        <Input placeholder="例如：生成小红书文案" />
                      </Form.Item>
                      <Form.Item
                        name={[promptField.name, 'key']}
                        label="标识"
                        rules={[
                          { required: true, message: '请输入标识' },
                          { pattern: /^[A-Za-z][A-Za-z0-9_-]*$/, message: '以字母开头，只能包含字母、数字、_、-' },
                        ]}
                      >
                        <Input />
                      </Form.Item>
                    </div>
                    <div className="chat-app-edit-grid chat-app-edit-grid--icon">
                      <Form.Item name={[promptField.name, 'icon']} label="图标">
                        <Input placeholder="💬" />
                      </Form.Item>
                      <Form.Item name={[promptField.name, 'description']} label="说明">
                        <Input />
                      </Form.Item>
                    </div>
                    <Form.Item
                      name={[promptField.name, 'prompt_template']}
                      label="提示词模板"
                      extra="使用问题标识作为变量，例如：主题：{topic}"
                      rules={[{ required: true, message: '请输入提示词模板' }]}
                    >
                      <Input.TextArea rows={5} />
                    </Form.Item>

                    <Form.List name={[promptField.name, 'questions']}>
                      {(questionFields, { add: addQuestion, remove: removeQuestion }) => (
                        <div className="chat-app-question-list">
                          {questionFields.map((questionField, questionIndex) => (
                            <Card
                              key={questionField.key}
                              size="small"
                              type="inner"
                              title={`问题 ${questionIndex + 1}`}
                              extra={<Button danger type="text" size="small" icon={<DeleteOutlined />} onClick={() => removeQuestion(questionField.name)} />}
                            >
                              <div className="chat-app-edit-grid">
                                <Form.Item
                                  name={[questionField.name, 'label']}
                                  label="问题名称"
                                  rules={[{ required: true, message: '请输入问题名称' }]}
                                >
                                  <Input placeholder="例如：内容主题" />
                                </Form.Item>
                                <Form.Item
                                  name={[questionField.name, 'key']}
                                  label="变量标识"
                                  rules={[
                                    { required: true, message: '请输入变量标识' },
                                    { pattern: /^[A-Za-z][A-Za-z0-9_]*$/, message: '以字母开头，只能包含字母、数字和下划线' },
                                  ]}
                                >
                                  <Input placeholder="topic" />
                                </Form.Item>
                              </div>
                              <div className="chat-app-edit-grid">
                                <Form.Item name={[questionField.name, 'type']} label="类型" initialValue="text">
                                  <Select options={questionTypes} />
                                </Form.Item>
                                <Form.Item name={[questionField.name, 'placeholder']} label="输入提示">
                                  <Input />
                                </Form.Item>
                              </div>
                              <Form.Item name={[questionField.name, 'required']} valuePropName="checked">
                                <Checkbox>必填</Checkbox>
                              </Form.Item>

                              <Form.Item noStyle shouldUpdate>
                                {({ getFieldValue }) => {
                                  const type = getFieldValue([
                                    'prompts', promptField.name, 'questions', questionField.name, 'type',
                                  ]);
                                  if (!['single_choice', 'multi_choice'].includes(type)) return null;
                                  return (
                                    <Form.List name={[questionField.name, 'options']}>
                                      {(optionFields, { add: addOption, remove: removeOption }) => (
                                        <div className="chat-app-option-list">
                                          <div className="chat-app-option-title">选项</div>
                                          {optionFields.map((optionField) => (
                                            <Space key={optionField.key} className="chat-app-option-row" align="baseline">
                                              <Form.Item
                                                name={[optionField.name, 'label']}
                                                rules={[{ required: true, message: '请输入选项名称' }]}
                                              >
                                                <Input placeholder="显示名称" />
                                              </Form.Item>
                                              <Form.Item
                                                name={[optionField.name, 'value']}
                                                rules={[{ required: true, message: '请输入选项值' }]}
                                              >
                                                <Input placeholder="选项值" />
                                              </Form.Item>
                                              <Button danger type="text" icon={<DeleteOutlined />} onClick={() => removeOption(optionField.name)} />
                                            </Space>
                                          ))}
                                          <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => addOption({ value: newKey('option'), label: '' })}>
                                            添加选项
                                          </Button>
                                        </div>
                                      )}
                                    </Form.List>
                                  );
                                }}
                              </Form.Item>
                            </Card>
                          ))}
                          <Button
                            type="dashed"
                            block
                            icon={<PlusOutlined />}
                            onClick={() => addQuestion({ key: newKey('field'), type: 'text', required: false, options: [] })}
                          >
                            添加问题
                          </Button>
                        </div>
                      )}
                    </Form.List>
                  </Card>
                ))}
                <Button
                  type="dashed"
                  block
                  icon={<PlusOutlined />}
                  onClick={() => addPrompt({
                    key: newKey('prompt'), icon: '💬', prompt_template: '', questions: [],
                  })}
                >
                  添加问题组
                </Button>
              </Space>
            )}
          </Form.List>
        </Card>

        <div className="chat-app-edit-actions">
          <Button onClick={() => navigate(`/apps/${id}`)}>取消</Button>
          <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>
            保存配置
          </Button>
        </div>
      </Form>
    </div>
  );
};

export default ChatApplicationEditPage;

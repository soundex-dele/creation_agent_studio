import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Select,
  Spin,
  message,
} from 'antd';
import { EditOutlined, RocketOutlined } from '@ant-design/icons';
import { useParams, useSearchParams } from 'react-router-dom';

import ChatContainer from '@/components/Chat/ChatContainer';
import FormPresetPicker from '@/components/FormPresetPicker';
import { formAnswers, formErrorMessage, presetReference } from '@/lib/formPresets';
import type { FormPresetSnapshot } from '@/types';
import BrandReferencePicker from '@/components/BrandReferencePicker';
import { inheritedBrandFields, type BrandConfig, type BrandSelection } from '@/services/brandLibrary';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { guidedPromptIdentifier } from '@/lib/guidedPrompts';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { api } from '@/services/api';
import { useAppStore } from '@/stores/useAppStore';
import type {
  AppItem,
  ChatApplicationRuntime,
  GuidedPrompt,
  GuidedQuestion,
} from '@/types';
import './ChatApplicationRuntimePage.css';

type AnswerValue = string | string[] | number;

interface ComposePromptResponse {
  prompt: string;
  normalized_answers: Record<string, unknown>;
}

export default function ChatApplicationRuntimePage() {
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  const { applicationId } = useParams();
  return <ChatApplicationWorkspace key={`${organizationId}:${userId}:${applicationId}`} organizationId={organizationId} />;
}

function ChatApplicationWorkspace({ organizationId }: { organizationId: string | null }) {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const slug = searchParams.get('slug') || '';
  const { embedded, showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const restoredConversationId = searchParams.get('conversation');
  const manualWorkflowId = searchParams.get('workflowId');
  const manualRunId = searchParams.get('manualRunId');
  const workflowStepKey = searchParams.get('workflowStepKey');
  const loadApp = useAppStore((state) => state.loadApp);
  const [application, setApplication] = useState<AppItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedPromptId, setSelectedPromptId] = useState('');
  const [overrides, setOverrides] = useState<Record<string, AnswerValue>>({});
  const [generatedPrompt, setGeneratedPrompt] = useState('');
  const [composing, setComposing] = useState(false);
  const [chatStarted, setChatStarted] = useState(Boolean(restoredConversationId));
  const [conversationId, setConversationId] = useState<string | null>(restoredConversationId);
  const [draftRequestId, setDraftRequestId] = useState(0);
  const [brandSelection, setBrandSelection] = useState<BrandSelection | null>(null);
  const [preset, setPreset] = useState<FormPresetSnapshot | null>(null);
  const [useWorkflowPreset, setUseWorkflowPreset] = useState(true);
  const [useWorkflowBrand, setUseWorkflowBrand] = useState(true);
  const [contextError, setContextError] = useState('');
  const [manualContext, setManualContext] = useState<{ prompt: GuidedPrompt; form_preset: FormPresetSnapshot | null; brand_snapshot: { selection: BrandSelection } | null } | null>(null);
  const [explicitFields, setExplicitFields] = useState<string[]>([]);
  const composeVersion = useRef(0);
  const invalidatePreview = () => { composeVersion.current += 1; setGeneratedPrompt(''); };
  useEffect(() => () => { composeVersion.current += 1; }, []);

  useEffect(() => {
    let cancelled = false;
    if (!slug) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void loadApp(slug).then((loaded) => {
      if (!cancelled) setApplication(loaded);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [loadApp, slug]);

  const runtime = application?.kind === 'chat'
    ? application.runtime as ChatApplicationRuntime
    : null;
  const prompts = useMemo(() => (
    [...(runtime?.guided_prompts ?? []).map((p) => manualContext?.prompt.key === p.key ? manualContext.prompt : p)].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  ), [runtime, manualContext]);
  const brandConfig = runtime?.default_config.brand_reference as BrandConfig | undefined;
  const inheritedFields = inheritedBrandFields(brandConfig, brandSelection, explicitFields);
  const selectedPrompt = prompts.find(
    (prompt) => guidedPromptIdentifier(prompt) === selectedPromptId,
  )
    ?? prompts[0]
    ?? null;
  const answers = formAnswers(selectedPrompt, preset, overrides);
  const defaultAgent = runtime?.agent_bindings.find((binding) => binding.is_default)
    ?? runtime?.agent_bindings[0]
    ?? null;

  useEffect(() => {
    if (!selectedPrompt) return;
    setSelectedPromptId(guidedPromptIdentifier(selectedPrompt));
    setOverrides({});
    const context = manualContext?.prompt.key === selectedPrompt.key ? manualContext : null;
    setPreset(context?.form_preset || null);
    setUseWorkflowPreset(Boolean(context));
    setUseWorkflowBrand(Boolean(context));
    setGeneratedPrompt('');
    composeVersion.current += 1;
    setExplicitFields([]);
    setBrandSelection(context?.brand_snapshot?.selection || null);
  }, [selectedPrompt, manualContext]);

  useEffect(() => {
    if (!manualRunId || !workflowStepKey || !runtime) return;
    const controller = new AbortController();
    setContextError('');
    void api.get<NonNullable<typeof manualContext>>(`/apps/${slug}/workflow-form-context/`, { run_id: manualRunId, step_key: workflowStepKey }, { signal: controller.signal })
      .then((context) => {
        if (controller.signal.aborted) return;
        setManualContext(context);
        setSelectedPromptId(guidedPromptIdentifier(context.prompt));
      }).catch(() => { if (!controller.signal.aborted) setContextError('无法读取工作流模板和品牌资料，请重新打开此节点。'); });
    return () => controller.abort();
  }, [manualRunId, workflowStepKey, runtime, slug]);

  const setAnswer = (question: GuidedQuestion, value: AnswerValue | null) => {
    invalidatePreview();
    setExplicitFields((current) => [...new Set([...current, question.key])]);
    setOverrides((current) => ({
      ...current,
      [question.key]: value === null ? '' : value,
    }));
  };

  const composePrompt = async () => {
    if (!selectedPrompt || !application || (manualRunId && !manualContext)) return;
    const missing = selectedPrompt.questions.filter((question) => {
      if (inheritedFields.includes(question.key)) return false;
      if (!question.required) return false;
      const value = answers[question.key];
      return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
    });
    if (missing.length) {
      message.warning(`请填写：${missing.map((question) => question.label).join('、')}`);
      return;
    }
    if (brandSelection && !brandSelection.reference.modules.length) {
      message.warning('请选择品牌资料模块，或取消引用。');
      return;
    }
    setComposing(true);
    const version = ++composeVersion.current;
    try {
      const response = await api.post<ComposePromptResponse>(
        `/apps/${slug}/compose-prompt/`,
        { prompt_id: guidedPromptIdentifier(selectedPrompt), answers, explicit_fields: explicitFields,
          preset: useWorkflowPreset && manualContext ? null : presetReference(preset),
          ...(manualRunId && workflowStepKey ? { workflow_context: { run_id: manualRunId, step_key: workflowStepKey },
            use_workflow_preset: useWorkflowPreset, use_workflow_brand: useWorkflowBrand } : {}),
          ...(brandConfig?.enabled && brandSelection ? { brand_reference: brandSelection.reference, explicit_fields: explicitFields } : {}),
        },
      );
      if (version === composeVersion.current) setGeneratedPrompt(response.prompt);
    } catch (error: any) {
      message.error(formErrorMessage(error, '生成提示词失败'));
    } finally {
      setComposing(false);
    }
  };

  const enterChat = () => {
    if (!generatedPrompt.trim()) return;
    setChatStarted(true);
    setDraftRequestId((current) => current + 1);
  };

  const handleConversationCreated = (createdConversationId: string) => {
    setConversationId(createdConversationId);
    if (!manualWorkflowId || !manualRunId || !workflowStepKey) return;
    void api.post(`/workflows/${manualWorkflowId}/manual-session/`, {
      action: 'attach_conversation',
      run_id: manualRunId,
      step_key: workflowStepKey,
      conversation_id: createdConversationId,
    }).catch((error: any) => {
      message.error(error?.response?.data?.detail || '工作流未能保存本次对话');
    });
  };

  if (loading) {
    return <div className="chat-app-loading"><Spin size="large" /></div>;
  }
  if (!runtime || !application || !applicationId) {
    return (
      <div className="chat-app-error">
        <Alert type="error" showIcon message="聊天应用不可用" description="应用不存在或类型配置不正确。" />
      </div>
    );
  }

  return (
    <div className={`chat-app-page ${embedded ? 'chat-app-page--embedded' : ''}`}>
      {showApplicationHeader && (
        <header className="chat-app-header">
          <div className="chat-app-heading">
            <span className="chat-app-icon">{application.icon || '✦'}</span>
            <div>
              <h1>{application.name}</h1>
              <p>{application.description}</p>
            </div>
          </div>
          {chatStarted && (
            <Button icon={<EditOutlined />} onClick={() => setChatStarted(false)}>
              重新填写
            </Button>
          )}
        </header>
      )}
      {!embedded && !showApplicationHeader && chatStarted && (
        <div className="chat-app-tools">
          <Button icon={<EditOutlined />} onClick={() => setChatStarted(false)}>
            重新填写
          </Button>
        </div>
      )}

      {chatStarted ? (
        <main className="chat-app-chat">
          <ChatContainer
            conversationId={conversationId}
            createOnFirstSend
            creationContext={{
              applicationId: Number(applicationId),
              agentId: defaultAgent?.agent_id,
            }}
            defaultAgent={defaultAgent ? {
              id: defaultAgent.agent_id,
              name: defaultAgent.label || defaultAgent.agent_name,
              description: '',
            } : null}
            suggestions={[]}
            emptyTitle={runtime.chat_profile.empty_state_title}
            emptyDescription={runtime.chat_profile.welcome_message}
            inputPlaceholder={runtime.chat_profile.input_placeholder}
            draftRequest={{ id: draftRequestId, text: generatedPrompt }}
            onConversationCreated={handleConversationCreated}
          />
        </main>
      ) : (
        <main className="chat-app-builder">
          <section className="chat-app-form-card">
            {prompts.length > 1 && (
              <div className="chat-app-prompt-tabs">
                {prompts.map((prompt) => (
                  <button
                    key={guidedPromptIdentifier(prompt)}
                    className={
                      guidedPromptIdentifier(prompt) === selectedPromptId ? 'active' : ''
                    }
                    onClick={() => setSelectedPromptId(guidedPromptIdentifier(prompt))}
                  >
                    <span>{prompt.icon || '✦'}</span>{prompt.title}
                  </button>
                ))}
              </div>
            )}
            {selectedPrompt ? (
              <>
                {brandConfig?.enabled && organizationId && <BrandReferencePicker root={tenantApiRoot(organizationId)}
                  config={brandConfig} value={brandSelection} onChange={(selection) => { invalidatePreview(); setUseWorkflowBrand(false); setBrandSelection(selection); }} />}
                {contextError && <Alert type="error" message={contextError} />}
                <FormPresetPicker key={`${organizationId}:${selectedPrompt.key}`} applicationSlug={slug} prompt={selectedPrompt}
                  value={preset} answers={answers} excludedFields={inheritedFields}
                  onChange={(next) => { invalidatePreview(); setUseWorkflowPreset(false); setPreset(next); }} />
                <div className="chat-app-form-title">
                  <span>{selectedPrompt.icon || '📝'}</span>
                  <div>
                    <h2>{selectedPrompt.title}</h2>
                    {selectedPrompt.description && <p>{selectedPrompt.description}</p>}
                  </div>
                </div>
                <div className="chat-app-fields">
                  {selectedPrompt.questions.map((question) => (
                    <label className="chat-app-field" key={question.key}>
                      <span>{question.label}{question.required && <b>*</b>}</span>
                      <small>{explicitFields.includes(question.key) ? '本次覆盖' : inheritedFields.includes(question.key) ? '来自品牌' : question.key in (preset?.values || {}) ? '来自模板' : '应用默认值'}</small>
                      {question.help_text && <small>{question.help_text}</small>}
                      {inheritedFields.includes(question.key) ? <div>
                        <Alert type="info" message="使用品牌资料" description="生成提示词时读取档案中的对应资料。" />
                        <Button type="link" onClick={() => setAnswer(question, answers[question.key] ?? '')}>改为本次填写</Button>
                      </div> : question.type === 'single_choice' || question.type === 'multi_choice' ? (
                        <Select
                          mode={question.type === 'multi_choice' ? 'multiple' : undefined}
                          value={answers[question.key] || undefined}
                          placeholder={question.placeholder}
                          options={question.options.map((option) => ({
                            value: option.value,
                            label: option.label,
                            title: option.description,
                          }))}
                          onChange={(value) => setAnswer(question, value)}
                          allowClear
                        />
                      ) : question.type === 'number' ? (
                        <InputNumber
                          value={answers[question.key] as number | undefined}
                          placeholder={question.placeholder}
                          onChange={(value) => setAnswer(question, value)}
                        />
                      ) : (
                        <Input.TextArea
                          value={(answers[question.key] as string | undefined) || ''}
                          placeholder={question.placeholder}
                          autoSize={{ minRows: question.key === 'topic' ? 2 : 3, maxRows: 8 }}
                          onChange={(event) => setAnswer(question, event.target.value)}
                        />
                      )}
                      {explicitFields.includes(question.key) && <Button type="link" onClick={() => {
                        invalidatePreview(); setExplicitFields((current) => current.filter((key) => key !== question.key));
                        setOverrides((current) => { const next = { ...current }; delete next[question.key]; return next; });
                      }}>{brandSelection && inheritedBrandFields(brandConfig, brandSelection, []).includes(question.key) ? '使用品牌资料' : '恢复继承'}</Button>}
                    </label>
                  ))}
                </div>
                <Button type="primary" size="large" loading={composing} disabled={Boolean(manualRunId && !manualContext)} onClick={composePrompt}>
                  生成提示词
                </Button>
              </>
            ) : (
              <Alert type="warning" showIcon message="该应用尚未配置引导表单" />
            )}
          </section>

          {generatedPrompt && (
            <section className="chat-app-preview-card">
              <div>
                <h2>生成的提示词</h2>
                <p>你可以继续编辑，确认后进入此应用的专属对话。</p>
              </div>
              <Input.TextArea
                value={generatedPrompt}
                onChange={(event) => setGeneratedPrompt(event.target.value)}
                autoSize={{ minRows: 10, maxRows: 20 }}
              />
              <Button type="primary" size="large" icon={<RocketOutlined />} onClick={enterChat}>
                进入对话
              </Button>
            </section>
          )}
        </main>
      )}
    </div>
  );
}

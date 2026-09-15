import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Select,
  Spin,
  message,
} from 'antd';
import { ArrowLeftOutlined, EditOutlined, RocketOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import ChatContainer from '@/components/Chat/ChatContainer';
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

const initialAnswers = (prompt: GuidedPrompt | null): Record<string, AnswerValue> => (
  Object.fromEntries((prompt?.questions ?? []).flatMap((question) => (
    question.default_value === undefined || question.default_value === null
      ? []
      : [[question.key, question.default_value as AnswerValue]]
  )))
);

export default function ChatApplicationRuntimePage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const slug = searchParams.get('slug') || '';
  const { embedded, entry, showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const restoredConversationId = searchParams.get('conversation');
  const manualWorkflowId = searchParams.get('workflowId');
  const manualRunId = searchParams.get('manualRunId');
  const workflowStepKey = searchParams.get('workflowStepKey');
  const navigate = useNavigate();
  const loadApp = useAppStore((state) => state.loadApp);
  const [application, setApplication] = useState<AppItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedPromptId, setSelectedPromptId] = useState('');
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [generatedPrompt, setGeneratedPrompt] = useState('');
  const [composing, setComposing] = useState(false);
  const [chatStarted, setChatStarted] = useState(Boolean(restoredConversationId));
  const [conversationId, setConversationId] = useState<string | null>(restoredConversationId);
  const [draftRequestId, setDraftRequestId] = useState(0);

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
    [...(runtime?.guided_prompts ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  ), [runtime]);
  const selectedPrompt = prompts.find((prompt) => prompt.id === selectedPromptId)
    ?? prompts[0]
    ?? null;
  const defaultAgent = runtime?.agent_bindings.find((binding) => binding.is_default)
    ?? runtime?.agent_bindings[0]
    ?? null;

  useEffect(() => {
    if (!selectedPrompt) return;
    setSelectedPromptId(selectedPrompt.id);
    setAnswers(initialAnswers(selectedPrompt));
    setGeneratedPrompt('');
  }, [selectedPrompt]);

  const setAnswer = (question: GuidedQuestion, value: AnswerValue | null) => {
    setAnswers((current) => ({
      ...current,
      [question.key]: value === null ? '' : value,
    }));
  };

  const composePrompt = async () => {
    if (!selectedPrompt || !application) return;
    const missing = selectedPrompt.questions.filter((question) => {
      if (!question.required) return false;
      const value = answers[question.key];
      return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
    });
    if (missing.length) {
      message.warning(`请填写：${missing.map((question) => question.label).join('、')}`);
      return;
    }
    setComposing(true);
    try {
      const response = await api.post<ComposePromptResponse>(
        `/apps/${application.id}/compose-prompt/`,
        { prompt_id: selectedPrompt.id, answers },
      );
      setGeneratedPrompt(response.prompt);
    } catch (error: any) {
      const detail = error?.response?.data;
      message.error(detail?.detail || Object.values(detail || {}).flat()[0] || '生成提示词失败');
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
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
            返回应用
          </Button>
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
      {!embedded && entry === 'home' && chatStarted && (
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
                    key={prompt.id}
                    className={prompt.id === selectedPrompt?.id ? 'active' : ''}
                    onClick={() => setSelectedPromptId(prompt.id)}
                  >
                    <span>{prompt.icon || '✦'}</span>{prompt.title}
                  </button>
                ))}
              </div>
            )}
            {selectedPrompt ? (
              <>
                <div className="chat-app-form-title">
                  <span>{selectedPrompt.icon || '📝'}</span>
                  <div>
                    <h2>{selectedPrompt.title}</h2>
                    {selectedPrompt.description && <p>{selectedPrompt.description}</p>}
                  </div>
                </div>
                <div className="chat-app-fields">
                  {selectedPrompt.questions.map((question) => (
                    <label className="chat-app-field" key={question.id}>
                      <span>{question.label}{question.required && <b>*</b>}</span>
                      {question.help_text && <small>{question.help_text}</small>}
                      {question.type === 'single_choice' || question.type === 'multi_choice' ? (
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
                    </label>
                  ))}
                </div>
                <Button type="primary" size="large" loading={composing} onClick={composePrompt}>
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

import { useEffect, useMemo, useState } from 'react';
import { Input, InputNumber, Modal, Select, Spin, message } from 'antd';
import { useSearchParams } from 'react-router-dom';
import ChatContainer from '@/components/Chat/ChatContainer';
import GuidedPromptPanel from '@/components/Workspace/GuidedPromptPanel';
import WorkspaceFilesPanel from '@/components/Workspace/WorkspaceFilesPanel';
import { useWorkspaceFiles } from '@/hooks/useWorkspaceFiles';
import { api } from '@/services/api';
import { useConversationStore } from '@/stores/useConversationStore';
import type { ChatApplicationRuntime, GuidedPrompt, GuidedQuestion } from '@/types';
import type { WorkflowProcess } from '@/types/workflow';
import './ChatApplicationView.css';

interface Props {
  application: ChatApplicationRuntime;
  projectId?: number;
  workflowStepRunId?: string;
}

const ChatApplicationView: React.FC<Props> = ({ application, projectId, workflowStepRunId }) => {
  const [searchParams] = useSearchParams();
  const requestedConversationId = searchParams.get('conversation');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [activePrompt, setActivePrompt] = useState<GuidedPrompt | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [composing, setComposing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [conversationLookupComplete, setConversationLookupComplete] = useState(false);
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string } | null>(null);
  const { createConversation, fetchConversationDetail, sendMessageStream, streamingMessageId } =
    useConversationStore();
  const {
    working_directory: workingDirectory,
    entries: workspaceEntries,
    file_count: workspaceFileCount,
    truncated: workspaceListingTruncated,
    isRefreshing: isRefreshingWorkspace,
    refresh: refreshWorkspaceFiles,
    readFile: readWorkspaceFile,
  } = useWorkspaceFiles(projectId);

  const defaultAgent = application.agent_bindings.find((item) => item.is_default)
    ?? application.agent_bindings[0];
  const defaultSkills = application.skill_bindings
    .filter((item) => item.mode !== 'optional')
    .map((item) => item.skill_id);

  const guidedEntryProcess = useMemo<WorkflowProcess | null>(() => {
    const configuredKey = application.default_config.guided_entry_prompt_key;
    if (typeof configuredKey !== 'string') return null;
    const prompt = application.guided_prompts.find((item) => item.key === configuredKey);
    if (!prompt) return null;
    return {
      id: prompt.key,
      name: prompt.title,
      icon: prompt.icon,
      description: prompt.description,
      mode: 'guided',
      prompt_template: prompt.prompt_template,
      fields: prompt.questions.map((question) => ({
        id: question.key,
        label: question.label,
        type: question.type === 'single_choice'
          ? 'select'
          : question.type === 'multi_choice'
            ? 'multiselect'
            : question.type,
        options: question.options.map((option) => option.label),
        placeholder: question.placeholder,
        required: question.required,
      })),
    };
  }, [application.default_config, application.guided_prompts]);

  useEffect(() => {
    let active = true;
    setConversationLookupComplete(false);
    const restoreConversation = async () => {
      try {
        let restoredConversationId = requestedConversationId;
        if (!restoredConversationId) {
          const params = workflowStepRunId
            ? { workflow_step_run_id: workflowStepRunId }
            : { application_id: application.id, ...(projectId ? { project_id: projectId } : {}) };
          const response = await api.get<any[] | { results?: any[] }>(
            '/conversations/', params);
          const items = Array.isArray(response) ? response : response.results ?? [];
          restoredConversationId = items[0]?.id ? String(items[0].id) : null;
        }
        if (restoredConversationId) {
          // Guided applications disable ChatContainer's automatic fetch to
          // protect a newly seeded stream. History restoration therefore has
          // to hydrate the selected conversation before showing the chat.
          await fetchConversationDetail(restoredConversationId);
        }
        if (active) setConversationId(restoredConversationId);
      } catch {
        if (active) setConversationId(null);
      } finally {
        if (active) setConversationLookupComplete(true);
      }
    };
    void restoreConversation();
    return () => {
      active = false;
    };
  }, [application.id, guidedEntryProcess, projectId, workflowStepRunId,
    fetchConversationDetail, requestedConversationId]);

  useEffect(() => {
    if (!projectId) return;
    void refreshWorkspaceFiles();
    if (!streamingMessageId) return;
    const timer = window.setInterval(() => {
      void refreshWorkspaceFiles();
    }, 1200);
    return () => window.clearInterval(timer);
  }, [projectId, streamingMessageId, refreshWorkspaceFiles]);

  const suggestions = useMemo(() => application.guided_prompts.map((prompt) => ({
    icon: prompt.icon,
    label: prompt.title,
    onSelect: () => {
      if (prompt.questions.length === 0) {
        setDraftRequest({ id: Date.now(), text: prompt.prompt_template });
      } else {
        setAnswers(Object.fromEntries(prompt.questions
          .filter((question) => question.default_value !== undefined)
          .map((question) => [question.key, question.default_value])));
        setActivePrompt(prompt);
      }
    },
  })), [application.guided_prompts]);

  const updateAnswer = (question: GuidedQuestion, value: unknown) => {
    setAnswers((current) => ({ ...current, [question.key]: value }));
  };

  const compose = async () => {
    if (!activePrompt) return;
    setComposing(true);
    try {
      const result = await api.post<{ prompt: string }>(
        `/apps/${application.application_slug}/compose-prompt/`,
        { prompt_id: activePrompt.id, answers },
      );
      setDraftRequest({ id: Date.now(), text: result.prompt });
      setActivePrompt(null);
      setAnswers({});
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '问题选项校验失败');
    } finally {
      setComposing(false);
    }
  };

  const startGuidedConversation = async (prompt: string) => {
    setStarting(true);
    try {
      const conversation = await createConversation(
        application.application_name,
        defaultAgent?.agent_id,
        projectId,
        undefined,
        {
          applicationId: application.id,
          workflowStepRunId,
          agentId: defaultAgent?.agent_id,
          skillIds: defaultSkills,
        },
      );
      const id = String(conversation.id);
      await fetchConversationDetail(id);
      sendMessageStream(id, prompt);
      setConversationId(id);
    } catch {
      message.error('创建对话失败');
    } finally {
      setStarting(false);
    }
  };

  if (!conversationLookupComplete) {
    return <div style={{ display: 'grid', height: '100%', placeItems: 'center' }}><Spin /></div>;
  }

  if (guidedEntryProcess && !conversationId) {
    return (
      <GuidedPromptPanel
        process={guidedEntryProcess}
        applying={starting}
        onStart={startGuidedConversation}
      />
    );
  }

  return (
    <>
      <div className="chat-application-layout">
        <div className="chat-application-main">
          <ChatContainer
            conversationId={conversationId}
            createOnFirstSend
            onConversationCreated={setConversationId}
            projectId={projectId}
            creationContext={{
              applicationId: application.id,
              workflowStepRunId,
              agentId: defaultAgent?.agent_id,
              skillIds: defaultSkills,
            }}
            suggestions={suggestions}
            emptyTitle={application.chat_profile?.empty_state_title || application.application_name}
            emptyDescription={application.chat_profile?.welcome_message || application.application_description}
            inputPlaceholder={application.chat_profile?.input_placeholder}
            draftRequest={draftRequest}
            autoFetch={!guidedEntryProcess}
          />
        </div>

        {workspaceFileCount > 0 && (
          <WorkspaceFilesPanel
            workingDirectory={workingDirectory}
            entries={workspaceEntries}
            truncated={workspaceListingTruncated}
            isRefreshing={isRefreshingWorkspace}
            onRefresh={() => { void refreshWorkspaceFiles(); }}
            onReadFile={readWorkspaceFile}
          />
        )}
      </div>

      <Modal
        title={activePrompt?.title}
        open={Boolean(activePrompt)}
        okText="生成提示词"
        cancelText="取消"
        confirmLoading={composing}
        onOk={compose}
        onCancel={() => { setActivePrompt(null); setAnswers({}); }}
      >
        {activePrompt?.description && <p>{activePrompt.description}</p>}
        {activePrompt?.questions.map((question) => (
          <div key={question.id} style={{ marginBottom: 18 }}>
            <label style={{ display: 'block', marginBottom: 8, fontWeight: 600 }}>
              {question.label}{question.required && <span style={{ color: '#ff4d4f' }}> *</span>}
            </label>
            {question.type === 'single_choice' && (
              <Select style={{ width: '100%' }}
                value={answers[question.key] as string | undefined}
                placeholder={question.placeholder || `请选择${question.label}`}
                options={question.options.map((option) => ({ value: option.value, label: option.label }))}
                onChange={(value) => updateAnswer(question, value)} />
            )}
            {question.type === 'multi_choice' && (
              <Select mode="multiple" style={{ width: '100%' }}
                value={answers[question.key] as string[] | undefined}
                placeholder={question.placeholder || `请选择${question.label}`}
                options={question.options.map((option) => ({ value: option.value, label: option.label }))}
                onChange={(value) => updateAnswer(question, value)} />
            )}
            {question.type === 'number' && (
              <InputNumber style={{ width: '100%' }}
                value={answers[question.key] as number | undefined}
                placeholder={question.placeholder}
                onChange={(value) => updateAnswer(question, value)} />
            )}
            {(question.type === 'text' || question.type === 'file') && (
              <Input.TextArea rows={question.type === 'text' ? 3 : 1}
                value={(answers[question.key] as string | undefined) || ''}
                placeholder={question.type === 'file'
                  ? '请输入工作区中的素材名称'
                  : question.placeholder}
                onChange={(event) => updateAnswer(question, event.target.value)} />
            )}
            {question.help_text && (
              <div style={{ marginTop: 5, color: 'var(--text-secondary)' }}>
                {question.help_text}
              </div>
            )}
          </div>
        ))}
      </Modal>
    </>
  );
};

export default ChatApplicationView;

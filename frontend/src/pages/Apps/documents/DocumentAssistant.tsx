import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Space, Spin } from 'antd';
import ReactMarkdown from 'react-markdown';
import type { Editor } from '@tiptap/core';
import ChatContainer from '@/components/Chat/ChatContainer';
import { ChatConnectionContext } from '@/components/Chat/ChatConnectionContext';
import { createConversationStore } from '@/stores/useConversationStore';
import { api } from '@/services/api';
import { documentError, type DocumentAIContext } from '@/services/documents';
import type { DocumentDraft } from './DocumentDraft';

export type ApplyMode = 'insert' | 'selection' | 'replace';
export function DocumentAssistant({ base, draft, editor, apply }: {
  base: string; draft: DocumentDraft; editor: Editor;
  apply: (text: string, mode: ApplyMode, context: DocumentAIContext) => Promise<void>;
}) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [draftRequest, setDraftRequest] = useState<{ id: number; text: string } | null>(null);
  const current = useRef({ draft, editor }); current.current = { draft, editor };
  const endpoint = `${base}/${draft.document.id}`;
  const connection = useMemo(() => {
    const wrapped: typeof api = {
      ...api,
      get: (url, params, config) => api.get(/^\/conversations\/[^/]+\/$/.test(url) ? `${endpoint}/conversation` : url, params, config),
      post: async (url, data, config) => {
        const command = url.match(/\/runs\/([^/]+)\/commands$/);
        if (command) return api.post(`${endpoint}/runs/${command[1]}/commands`, data, config);
        if (/\/send_message\/$/.test(url)) {
          const { draft: value, editor: activeEditor } = current.current;
          const saved = await value.save();
          const { from, to } = activeEditor.state.selection;
          return api.post(`${endpoint}/assistant`, {
            content: (data as { content: string }).content,
            version: saved.version,
            selection: activeEditor.state.doc.textBetween(from, to, '\n'),
            selection_from: from, selection_to: to,
          }, config);
        }
        return api.post(url, data, config);
      },
    };
    return { store: createConversationStore(undefined, wrapped), api: wrapped, remote: false, online: true };
  }, [endpoint]);
  useEffect(() => {
    let active = true; setError('');
    void api.post<{ id: string }>(`${endpoint}/conversation`).then((result) => { if (active) setConversationId(result.id); }).catch((e) => { if (active) setError(documentError(e)); });
    return () => { active = false; connection.store.getState().disconnect(); };
  }, [endpoint, connection, attempt]);
  const suggest = (text: string) => setDraftRequest({ id: Date.now(), text });
  return <section className="documents-assistant" aria-label="文档 AI 助手">
    <header><h2>AI 助手</h2><span>对话仅自己可见</span></header>
    <Space wrap className="documents-ai-actions">
      {['起草', '续写', '润色选区', '总结'].map((label) => <Button key={label} size="small" onClick={() => suggest({ 起草: '请根据以下要求起草文档：', 续写: '请根据当前文档续写，只输出新增内容。', 润色选区: '请润色选区，保持原意，只输出修改后的内容。', 总结: '请总结当前文档的主要观点。' }[label]!)}>{label}</Button>)}
    </Space>
    {error ? <Alert type="error" message={error} action={<Button onClick={() => setAttempt((n) => n + 1)}>重试</Button>} /> : !conversationId ? <Spin /> : <ChatConnectionContext.Provider value={connection}>
      <ChatContainer conversationId={conversationId} composerMode="document" draftRequest={draftRequest}
        emptyTitle="一起完善这份文档" emptyDescription="正文会作为上下文发送。生成内容需你确认后才会写入。"
        inputPlaceholder="输入要求，或先选中需要润色的正文…" suggestions={[]}
        renderAssistantContent={({ message, content, isStreaming }) => {
          const context = (message.metadata as { document_context?: DocumentAIContext } | undefined)?.document_context;
          return <div className="documents-ai-result"><ReactMarkdown components={{ img: () => null }}>{content}</ReactMarkdown>
            {!isStreaming && context && draft.document.permission !== 'viewer' && <Space wrap>
              <Button size="small" onClick={() => void apply(content, 'insert', context)}>插入光标处</Button>
              <Button size="small" disabled={!context.selection} onClick={() => void apply(content, 'selection', context)}>替换选区</Button>
              <Button size="small" onClick={() => void apply(content, 'replace', context)}>替换全文</Button>
            </Space>}
          </div>;
        }} />
    </ChatConnectionContext.Provider>}
  </section>;
}

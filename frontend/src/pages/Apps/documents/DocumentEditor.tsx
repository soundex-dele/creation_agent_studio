import { useCallback, useEffect, useMemo, useReducer, useState } from 'react';
import { Alert, Button, Drawer, Grid, Input, Modal, Select, Space, Tag, message } from 'antd';
import { EditorContent, useEditor, useEditorState } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import { Markdown } from '@tiptap/markdown';
import { documentError, documentsApi, downloadText, type DocumentAIContext, type OnlineDocument } from '@/services/documents';
import { DocumentDraft } from './DocumentDraft';
import { DocumentShares } from './DocumentShares';
import { DocumentAssistant, type ApplyMode } from './DocumentAssistant';
import { documentPlainText, safeAIContent, safeLink } from './content';

export function DocumentEditor({ base, document: initial, onDraft, onSaved, onOpen, onDelete }: {
  base: string; document: OnlineDocument; onDraft: (draft: DocumentDraft | null) => void;
  onSaved: (document: OnlineDocument) => void; onOpen: (document: OnlineDocument) => void;
  onDelete: () => void;
}) {
  const client = useMemo(() => documentsApi(base), [base]);
  const draft = useMemo(() => new DocumentDraft(initial, (body, version) => client.save(initial.id, body, version)), [client, initial]);
  const [, render] = useReducer((n: number) => n + 1, 0);
  const [sharesOpen, setSharesOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState(false);
  const [modal, modalHolder] = Modal.useModal();
  const screens = Grid.useBreakpoint();
  const readonly = draft.document.permission === 'viewer';
  const editor = useEditor({
    extensions: [StarterKit.configure({ underline: false, link: { openOnClick: false, protocols: ['http', 'https', 'mailto'] } }), TableKit.configure({ table: { resizable: false } }), Markdown],
    content: initial.content,
    editable: !readonly,
    editorProps: { attributes: { 'aria-label': '文档正文', role: 'textbox', 'aria-multiline': 'true', spellcheck: 'false' },
      handleDOMEvents: {
        compositionstart: () => { draft.composition(true); return false; },
        compositionend: () => { draft.composition(false); return false; },
      },
    },
    onUpdate: ({ editor: active }) => draft.update({ content: active.getJSON() }),
  });
  const toolbar = useEditorState({ editor, selector: ({ editor: value }) => ({
    bold: value?.isActive('bold'), italic: value?.isActive('italic'), list: value?.isActive('bulletList'), ordered: value?.isActive('orderedList'), quote: value?.isActive('blockquote'), code: value?.isActive('codeBlock'), table: value?.isActive('table'), heading: [1, 2, 3].find((level) => value?.isActive('heading', { level })) || 0,
  }) });
  useEffect(() => {
    let lastVersion = initial.version;
    const unsubscribe = draft.subscribe(() => {
      render();
      if (lastVersion !== draft.document.version) { lastVersion = draft.document.version; onSaved(draft.document); }
    });
    onDraft(draft);
    return () => { unsubscribe(); onDraft(null); draft.dispose(); };
  }, [draft, initial.version, onDraft, onSaved]);
  const notifyError = (error: unknown) => { void message.error(documentError(error)); };
  const run = async (action: () => Promise<void>) => {
    setBusy(true); try { await action(); } catch (error) { notifyError(error); } finally { setBusy(false); }
  };
  const downloadDraft = () => downloadText(draft.body.title, documentPlainText(draft.body.content));
  const apply = useCallback(async (text: string, mode: ApplyMode, context: DocumentAIContext) => {
    if (!editor || readonly) return;
    try {
      if (draft.hasChanges || draft.composing || context.version !== draft.document.version) throw new Error('正文已变化。请重新选择内容并让 AI 生成新结果后再应用。');
      const latest = await client.get(initial.id);
      if (latest.permission === 'viewer') throw new Error('当前文档已变为只读。');
      if (latest.version !== context.version || draft.hasChanges) throw new Error('正文已变化，请保留草稿后重新加载，并重新生成 AI 结果。');
      if (mode === 'replace' && !await modal.confirm({ title: '用 AI 结果替换全文？', content: '替换后可立即使用撤销恢复。', okText: '替换', cancelText: '取消' })) return;
      if (draft.hasChanges || draft.composing) throw new Error('正文已变化，请重新生成 AI 结果。');
      const { from, to } = editor.state.selection;
      if (mode === 'selection' && (from === to || from !== context.selection_from || to !== context.selection_to || editor.state.doc.textBetween(from, to, '\n') !== context.selection)) throw new Error('选区已变化，请重新选中原文后重试。');
      const parsed = safeAIContent(editor.markdown!.parse(text));
      if (!parsed.content?.length) throw new Error('AI 结果没有可插入的正文。');
      editor.schema.nodeFromJSON(parsed).check();
      if (mode === 'replace') editor.chain().focus().insertContentAt({ from: 0, to: editor.state.doc.content.size }, parsed.content).run();
      else editor.chain().focus().insertContentAt(mode === 'selection' ? { from, to } : to, parsed.content).run();
      await draft.save();
    } catch (error) { notifyError(error); }
  }, [editor, readonly, draft, client, initial.id, modal]);
  if (!editor) return null;
  const tool = (label: string, action: () => void, active = false) => <Button key={label} type={active ? 'primary' : 'text'} size="small" aria-pressed={active} disabled={readonly} onMouseDown={(event) => event.preventDefault()} onClick={action}>{label}</Button>;
  const assistant = <DocumentAssistant base={base} draft={draft} editor={editor} apply={apply} />;
  return <div className={`documents-editor-layout ${aiOpen && screens.xl ? 'has-ai' : ''}`}>
    {modalHolder}
    <section className="documents-editor-main">
      <header className="documents-document-header">
        <Input aria-label="文档标题" value={draft.body.title} disabled={readonly} maxLength={200} onCompositionStart={() => draft.composition(true)} onCompositionEnd={() => draft.composition(false)} onChange={(e) => draft.update({ title: e.target.value })} />
        <div className="documents-document-meta"><span role="status" aria-live="polite">{readonly ? '只读文档' : { saved: '已保存', dirty: '尚未保存', saving: '保存中…', error: '保存失败', conflict: '版本冲突' }[draft.status]}</span><span>{documentPlainText(draft.body.content).length} 字符</span><Tag>{initial.owner_name}</Tag></div>
        <Space wrap>
          {!readonly && <Button disabled={busy || !draft.hasChanges} onClick={() => void run(async () => { await draft.save(); })}>保存</Button>}
          <Button disabled={busy} onClick={() => void run(async () => { await draft.save(); const fresh = await client.get(initial.id); downloadText(fresh.title, fresh.plain_text); })}>下载文本</Button>
          <Button disabled={busy} onClick={() => void run(async () => { await draft.save(); onOpen(await client.copy(initial.id)); })}>复制</Button>
          {draft.document.permission === 'owner' && <Button onClick={() => setSharesOpen(true)}>共享</Button>}
          <Button type={aiOpen ? 'primary' : 'default'} onClick={() => setAiOpen((value) => !value)}>AI 助手</Button>
        </Space>
      </header>
      {(draft.status === 'error' || draft.status === 'conflict') && <Alert type="error" showIcon message={draft.error} description={<Space wrap>
        {draft.status === 'error' && <Button onClick={() => void run(async () => { await draft.save(); })}>重试保存</Button>}
        <Button onClick={downloadDraft}>下载草稿</Button>
        <Button disabled={busy} onClick={() => void run(async () => { const copy = await client.copy(initial.id, { ...draft.body, title: `${draft.body.title.slice(0, 197)} 副本` }); onOpen(copy); })}>另存副本</Button>
        <Button onClick={() => void run(async () => { if (await modal.confirm({ title: '重新加载文档？', content: '当前未保存的草稿将丢弃，请先下载或另存副本。', okText: '重新加载', cancelText: '取消' })) onOpen(await client.get(initial.id)); })}>重新加载</Button>
      </Space>} />}
      <div className="documents-toolbar" role="toolbar" aria-label="正文格式">
        <Select aria-label="段落样式" size="small" disabled={readonly} value={toolbar?.heading || 0} onChange={(level: number) => level ? editor.chain().focus().toggleHeading({ level: level as 1 | 2 | 3 }).run() : editor.chain().focus().setParagraph().run()} options={[{ value: 0, label: '正文' }, { value: 1, label: '标题 1' }, { value: 2, label: '标题 2' }, { value: 3, label: '标题 3' }]} />
        {tool('粗体', () => { editor.chain().focus().toggleBold().run(); }, toolbar?.bold)}
        {tool('斜体', () => { editor.chain().focus().toggleItalic().run(); }, toolbar?.italic)}
        {tool('项目列表', () => { editor.chain().focus().toggleBulletList().run(); }, toolbar?.list)}
        {tool('编号列表', () => { editor.chain().focus().toggleOrderedList().run(); }, toolbar?.ordered)}
        {tool('引用', () => { editor.chain().focus().toggleBlockquote().run(); }, toolbar?.quote)}
        {tool('代码块', () => { editor.chain().focus().toggleCodeBlock().run(); }, toolbar?.code)}
        {tool('链接', () => { setLink(String(editor.getAttributes('link').href || '')); setLinkOpen(true); })}
        {tool('插入表格', () => { editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(); })}
        {toolbar?.table && <>{tool('添加行', () => { editor.chain().focus().addRowAfter().run(); })}{tool('添加列', () => { editor.chain().focus().addColumnAfter().run(); })}{tool('删除行', () => { editor.chain().focus().deleteRow().run(); })}{tool('删除列', () => { editor.chain().focus().deleteColumn().run(); })}{tool('删除表格', () => { editor.chain().focus().deleteTable().run(); })}</>}
        {tool('撤销', () => { editor.chain().focus().undo().run(); })}{tool('重做', () => { editor.chain().focus().redo().run(); })}
      </div>
      <div className="documents-paper-scroll"><EditorContent editor={editor} className="documents-paper" /></div>
      {draft.document.permission === 'owner' && <footer><Button danger type="text" disabled={busy} onClick={() => void run(async () => {
        if (await modal.confirm({ title: '永久删除这份文档？', content: '正文、共享授权和关联对话将被删除，无法恢复。', okText: '删除', okButtonProps: { danger: true }, cancelText: '取消' })) { await client.remove(initial.id); onDraft(null); onDelete(); }
      })}>删除文档</Button></footer>}
    </section>
    {aiOpen && (screens.xl ? assistant : <Drawer title="AI 助手" open width="min(440px, 100vw)" onClose={() => setAiOpen(false)}>{assistant}</Drawer>)}
    {sharesOpen && <DocumentShares base={base} id={initial.id} onClose={() => setSharesOpen(false)} />}
    <Modal title="设置链接" open={linkOpen} onCancel={() => setLinkOpen(false)} okText="应用" cancelText="取消" onOk={() => {
      if (link && !safeLink(link)) { void message.error('请输入 http、https 或 mailto 链接。'); return; }
      if (link) editor.chain().focus().extendMarkRange('link').setLink({ href: link }).run(); else editor.chain().focus().extendMarkRange('link').unsetLink().run();
      setLinkOpen(false);
    }}><Input aria-label="链接地址" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://example.com（留空移除链接）" /></Modal>
  </div>;
}

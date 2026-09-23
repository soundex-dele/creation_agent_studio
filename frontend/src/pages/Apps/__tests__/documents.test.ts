// @vitest-environment jsdom
import { act, createElement } from 'react';
import { readFileSync } from 'node:fs';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import { Markdown } from '@tiptap/markdown';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { DocumentBody, OnlineDocument } from '@/services/documents';
import type { DocumentAIContext } from '@/services/documents';
import type { ApplyMode } from '../documents/DocumentAssistant';
import { DocumentDraft } from '../documents/DocumentDraft';
import { documentPlainText, safeAIContent, safeLink } from '../documents/content';
import { DocumentEditor } from '../documents/DocumentEditor';
import { applicationPath } from '@/lib/applicationCatalog';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const assistant = vi.hoisted(() => ({ apply: undefined as undefined | ((text: string, mode: ApplyMode, context: DocumentAIContext) => Promise<void>) }));
vi.mock('../documents/DocumentAssistant', () => ({ DocumentAssistant: (props: { apply: typeof assistant.apply }) => { assistant.apply = props.apply; return null; } }));

const content = (text: string) => ({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] });
const document: OnlineDocument = { id: 'doc-1', title: '在线文档测试', content: content('正文'), plain_text: '正文', version: 1, owner: 1, owner_name: 'owner', permission: 'owner', created_at: '', updated_at: '' };
const saved = (body: DocumentBody, version: number): OnlineDocument => ({ ...document, ...body, version: version + 1, plain_text: documentPlainText(body.content) });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('document saving state machine', () => {
  it('debounces typing and never saves while composing Chinese input', async () => {
    vi.useFakeTimers();
    const persist = vi.fn(async (body, version) => saved(body, version));
    const draft = new DocumentDraft(document, persist);
    draft.update({ title: '草' });
    await vi.advanceTimersByTimeAsync(600);
    draft.composition(true); draft.update({ title: '草稿' });
    await vi.advanceTimersByTimeAsync(3000);
    expect(persist).not.toHaveBeenCalled();
    await expect(draft.save()).rejects.toThrow('完成当前输入');
    draft.composition(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(persist).toHaveBeenCalledTimes(1);
    expect(draft.document.title).toBe('草稿');
    expect(draft.status).toBe('saved');
    draft.dispose();
  });
  it('serializes in-flight saves and flushes later edits with the returned version', async () => {
    let finish!: (doc: OnlineDocument) => void;
    const persist = vi.fn().mockImplementationOnce(() => new Promise<OnlineDocument>((resolve) => { finish = resolve; })).mockImplementation(async (body, version) => saved(body, version));
    const draft = new DocumentDraft(document, persist);
    draft.update({ title: '第一版' });
    const saving = draft.save();
    draft.update({ title: '第二版' });
    expect(draft.save()).toBe(saving);
    finish(saved({ title: '第一版', content: document.content }, 1));
    await saving;
    expect(persist.mock.calls.map((call) => call[1])).toEqual([1, 2]);
    expect(draft.document.title).toBe('第二版');
    expect(draft.document.version).toBe(3);
    expect(draft.hasChanges).toBe(false);
    draft.dispose();
  });
  it('keeps drafts and permits retry after a network error', async () => {
    const persist = vi.fn().mockRejectedValueOnce(new Error('网络断开')).mockImplementation(async (body, version) => saved(body, version));
    const draft = new DocumentDraft(document, persist);
    draft.update({ content: content('不能丢失的正文') });
    await expect(draft.save()).rejects.toThrow('网络断开');
    expect(draft.status).toBe('error'); expect(draft.hasChanges).toBe(true);
    expect(documentPlainText(draft.body.content)).toBe('不能丢失的正文');
    await draft.save(); expect(draft.status).toBe('saved');
    draft.dispose();
  });
  it('freezes automatic retries on a version conflict and preserves edits for a copy', async () => {
    vi.useFakeTimers();
    const persist = vi.fn().mockRejectedValue({ response: { status: 409, data: { detail: '版本冲突' } } });
    const draft = new DocumentDraft(document, persist);
    draft.update({ title: '本地草稿' });
    await expect(draft.save()).rejects.toBeDefined();
    draft.update({ title: '冲突后继续编辑' });
    await vi.advanceTimersByTimeAsync(3000);
    expect(persist).toHaveBeenCalledTimes(1);
    await expect(draft.save()).rejects.toThrow('版本冲突');
    expect(draft.document.version).toBe(1); expect(draft.body.title).toBe('冲突后继续编辑');
    draft.dispose();
  });
  it('manual save flushes the debounce before navigation, dispose cancels pending work', async () => {
    vi.useFakeTimers();
    const persist = vi.fn(async (body, version) => saved(body, version));
    const draft = new DocumentDraft(document, persist);
    draft.update({ title: '切换前保存' }); await draft.save();
    expect(draft.hasChanges).toBe(false);
    draft.update({ title: '停止' }); draft.dispose();
    await vi.advanceTimersByTimeAsync(2000); expect(persist).toHaveBeenCalledTimes(1);
  });
});

describe('real Tiptap document schema', () => {
  it('round trips the exact backend fixture with current editor defaults', () => {
    const fixture = JSON.parse(readFileSync('../backend/app_center/documents/backend/tests/fixtures/editor.json', 'utf8'));
    const editor = new Editor({ extensions: [StarterKit.configure({ underline: false }), TableKit, Markdown], content: fixture });
    expect(editor.getJSON()).toEqual(fixture);
    editor.destroy();
  });
  it('parses Markdown into editable blocks, removes unsafe links and supports undo', () => {
    const editor = new Editor({ extensions: [StarterKit.configure({ underline: false }), TableKit, Markdown], content: document.content });
    const parsed = safeAIContent(editor.markdown!.parse('# 标题\n\n**重点**\n\n- 一\n- 二\n\n| A | B |\n| - | - |\n| 1 | 2 |'));
    editor.schema.nodeFromJSON(parsed).check();
    editor.commands.insertContentAt({ from: 0, to: editor.state.doc.content.size }, parsed.content!);
    expect(editor.getJSON().content!.some((item) => item.type === 'table')).toBe(true);
    expect(editor.getText()).toContain('标题');
    expect(editor.commands.undo()).toBe(true); expect(editor.getText()).toBe('正文');
    const unsafe = safeAIContent({ type: 'text', text: '安全文字', marks: [{ type: 'link', attrs: { href: 'javascript:alert(1)' } }, { type: 'bold' }] });
    expect(unsafe.marks).toEqual([{ type: 'bold' }]);
    expect(safeLink('file:///test')).toBe(false);
    expect(safeLink('https://example.com')).toBe(true);
    editor.destroy();
  });
  it('routes the bundled application to the dedicated workspace', () => {
    expect(applicationPath({ id: 'documents', applicationId: 12, rendererKey: 'documents', kind: 'custom' })).toBe('/applications/12/documents?entry=apps');
  });
});

describe('document editor integration', () => {
  let root: Root; let container: HTMLDivElement; let draft: DocumentDraft | null;
  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })));
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    const computedStyle = window.getComputedStyle.bind(window);
    vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computedStyle(element));
    Object.defineProperty(Range.prototype, 'getClientRects', { configurable: true, value: () => [new DOMRect(0, 0, 0, 0)] });
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', { configurable: true, value: () => new DOMRect(0, 0, 0, 0) });
    container = window.document.createElement('div'); window.document.body.appendChild(container); root = createRoot(container); draft = null;
    vi.mocked(api.patch).mockImplementation(async (_url, body) => saved(body as DocumentBody, (body as { version: number }).version) as never);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove();
    delete (Range.prototype as Partial<Range>).getClientRects;
    delete (Range.prototype as Partial<Range>).getBoundingClientRect;
    vi.unstubAllGlobals();
  });
  const render = async (permission: OnlineDocument['permission']) => {
    await act(async () => root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(DocumentEditor, {
      base: '/documents', document: { ...document, permission }, onDraft: (value) => { draft = value; }, onSaved: vi.fn(), onOpen: vi.fn(), onDelete: vi.fn(),
    }))));
  };
  it('renders a readonly editor without sharing or write controls for readers', async () => {
    await render('viewer');
    expect(container.querySelector('[aria-label="文档正文"]')?.getAttribute('contenteditable')).toBe('false');
    expect(container.querySelector<HTMLInputElement>('[aria-label="文档标题"]')?.disabled).toBe(true);
    expect(container.textContent).not.toContain('共享');
    expect(container.textContent).toContain('只读文档');
  });
  it('keeps conflict recovery actions and the local title visible', async () => {
    await render('owner');
    vi.mocked(api.patch).mockRejectedValue({ response: { status: 409, data: { detail: '版本冲突' } } });
    await act(async () => { draft!.update({ title: '本地未保存' }); await draft!.save().catch(() => undefined); });
    expect(container.querySelector<HTMLInputElement>('[aria-label="文档标题"]')?.value).toBe('本地未保存');
    expect(container.textContent).toContain('下载草稿'); expect(container.textContent).toContain('另存副本');
    expect(container.textContent).toContain('重新加载');
  });
  it('applies an AI result through real editor/save and rejects reuse after the version changes', async () => {
    await render('owner');
    vi.mocked(api.get).mockResolvedValue(document);
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'AI 助手')!.click());
    expect(assistant.apply).toBeDefined();
    const context = { version: 1, selection: '', selection_from: 1, selection_to: 1 };
    const callsBefore = vi.mocked(api.patch).mock.calls.length;
    await act(async () => assistant.apply!('新增正文', 'insert', context));
    expect(documentPlainText(draft!.body.content)).toContain('新增正文');
    expect(draft!.document.version).toBe(2);
    expect(api.patch).toHaveBeenCalledTimes(callsBefore + 1);
    await act(async () => assistant.apply!('过期结果', 'insert', context));
    expect(documentPlainText(draft!.body.content)).not.toContain('过期结果');
    expect(api.patch).toHaveBeenCalledTimes(callsBefore + 1);
  });
  it('rejects applying a result to a moved selection', async () => {
    await render('owner');
    vi.mocked(api.get).mockResolvedValue(document);
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'AI 助手')!.click());
    const callsBefore = vi.mocked(api.patch).mock.calls.length;
    await act(async () => assistant.apply!('不应写入', 'selection', { version: 1, selection: '正文', selection_from: 1, selection_to: 3 }));
    expect(documentPlainText(draft!.body.content)).toBe('正文');
    expect(api.patch).toHaveBeenCalledTimes(callsBefore);
  });
});

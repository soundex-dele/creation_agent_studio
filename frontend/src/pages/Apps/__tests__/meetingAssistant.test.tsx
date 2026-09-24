// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { applicationPath } from '@/lib/applicationCatalog';
import { audioFileError, meetingApi, timeLabel, type MeetingRecord } from '@/services/meetingAssistant';
import { RecordingDetail } from '../meeting/RecordingDetail';
import { UploadRecording } from '../meeting/UploadRecording';
import { MeetingWorkspace } from '../MeetingAssistantPage';
import { DocumentsWorkspace } from '../DocumentsPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('../documents/DocumentEditor', () => ({ DocumentEditor: ({ document }: { document: { title: string } }) => <div data-testid="linked-document">{document.title}</div> }));
const base = '/organizations/org/applications/12/meeting-assistant';
const fixture: MeetingRecord = {
  id: 'record-1', title: '产品访谈', kind: 'interview', recorded_on: '2026-09-24', language: 'zh',
  filename: 'interview.mp3', size: 100, duration: 120, version: 1, analysis_version: 1, status: 'completed', stale: false, error: '', run_id: 'run-1',
  created_at: '2026-09-24T10:00:00Z', updated_at: '2026-09-24T10:00:00Z',
  segments: [{ id: 's1', start: 12, end: 20, text: '小王负责准备材料', original_text: '小王负责准备材料' }],
  analysis: { topics: [{ text: '讨论发布准备', segment_ids: ['s1'] }], decisions: [], viewpoints: [], quotes: [], facts: [], outline: [] },
  actions: [{ id: 'a1', revision: 'v1', title: '准备材料', description: '原文负责人：小王', priority: 2, due_date: null, segment_ids: ['s1'], todo_id: null, confirmed_at: null, analysis_version: 1 }],
};
let root: Root;
let container: HTMLDivElement;
const settle = async () => act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
const click = async (element: HTMLElement) => act(async () => element.click());
const button = (text: string) => {
  const found = [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.replace(/\s/g, '') === text);
  expect(found, text).toBeDefined();
  return found!;
};
const changeInput = async (field: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
};
const wrap = async (element: ReturnType<typeof createElement>, entry = '/') => {
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: [entry] },
    createElement(ConfigProvider, { theme: { token: { motion: false } } }, element))));
  await settle();
};
const detail = async (record = structuredClone(fixture)) => {
  const onChange = vi.fn();
  await wrap(createElement(RecordingDetail, { client: meetingApi(base), record, onChange, onDelete: vi.fn(), onDirty: vi.fn() }));
  return onChange;
};
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 0; });
  const original = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => original(element));
  vi.mocked(api.get).mockResolvedValue(structuredClone(fixture));
  vi.mocked(api.post).mockImplementation(async (url) => url.endsWith('/access') ? { token: 'audio-token', expires_in: 3600 } : { application_id: 13, actions: fixture.actions });
  vi.mocked(api.patch).mockResolvedValue(structuredClone(fixture));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals();
});

describe('会议与访谈助手', () => {
  it('registers a dedicated route and validates uploads', () => {
    expect(applicationPath({ id: 'meeting-assistant', applicationId: 12, rendererKey: 'meeting-assistant', kind: 'custom' })).toBe('/applications/12/meeting-assistant?entry=apps');
    expect(timeLabel(3661)).toBe('01:01:01');
    expect(audioFileError(new File(['audio'], 'a.wav'))).toBe('');
    expect(audioFileError(new File(['audio'], 'a.exe'))).toContain('支持');
    expect(audioFileError(new File([], 'a.mp3'))).toContain('200 MiB');
  });

  it('requires deliberate selection and confirmation before creating a todo', async () => {
    await detail();
    await click([...document.querySelectorAll<HTMLElement>('[role="tab"]')].find(e => e.textContent?.startsWith('行动项'))!);
    expect(button('确认加入待办').disabled).toBe(true);
    expect(vi.mocked(api.post).mock.calls.filter(([url]) => url.endsWith('/confirm-actions'))).toHaveLength(0);
    await click(document.querySelector<HTMLInputElement>('input[aria-label="选择行动项：准备材料"]')!);
    await click(button('确认加入待办（1）'));
    expect(api.post).toHaveBeenCalledWith(`${base}/records/record-1/confirm-actions`, { version: 1, confirmed: true, action_ids: ['a1'], action_versions: { a1: 'v1' } });
  });

  it('jumps from an evidence timestamp to the source transcript and audio', async () => {
    await detail();
    const audio = document.querySelector('audio')!;
    Object.defineProperty(audio, 'readyState', { value: 1 });
    await click(document.querySelector<HTMLButtonElement>('button[aria-label="回听 00:00:12"]')!);
    expect(audio.currentTime).toBe(12);
    expect(document.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('逐字稿');
    expect(document.getElementById('meeting-segment-s1')?.textContent).toContain('小王负责准备材料');
  });

  it('saves a correction with version and retains the source', async () => {
    const updated = { ...fixture, version: 2, stale: true };
    vi.mocked(api.patch).mockResolvedValue(updated);
    const onChange = await detail();
    await click([...document.querySelectorAll<HTMLElement>('[role="tab"]')].find(e => e.textContent === '逐字稿')!);
    await click(document.querySelector<HTMLButtonElement>('button[aria-label="校对 00:00:12"]')!);
    expect(document.body.textContent).toContain('原始转录：小王负责准备材料');
    await changeInput(document.querySelector('textarea')!, '小李负责准备材料');
    await click(button('保存校对'));
    expect(api.patch).toHaveBeenCalledWith(`${base}/records/record-1/transcript`, { version: 1, segments: [{ id: 's1', text: '小李负责准备材料' }] });
    expect(onChange).toHaveBeenCalledWith(updated);
  });

  it('blocks stale summaries from export and confirmation', async () => {
    await detail({ ...fixture, version: 2, stale: true });
    expect(document.body.textContent).toContain('以下分析来自旧版本');
    expect(button('会议纪要').disabled).toBe(true);
    expect(button('访谈素材包').disabled).toBe(true);
    await click([...document.querySelectorAll<HTMLElement>('[role="tab"]')].find(e => e.textContent?.startsWith('行动项'))!);
    expect(document.querySelector<HTMLInputElement>('input[aria-label="选择行动项：准备材料"]')!.disabled).toBe(true);
  });

  it('exports a document idempotently and offers its deep link', async () => {
    vi.mocked(api.post).mockImplementation(async url => url.endsWith('/access') ? { token: 't', expires_in: 3600 } : { document_id: 'doc-1', application_id: 55 });
    await detail();
    await click(button('访谈素材包'));
    expect(document.querySelector('a[href="/applications/55/documents?document=doc-1"]')).not.toBeNull();
    await click(button('访谈素材包'));
    const calls = vi.mocked(api.post).mock.calls.filter(([url]) => url.endsWith('/documents'));
    expect(calls).toHaveLength(2);
    expect(calls[0][2]?.headers).toEqual(calls[1][2]?.headers);
  });

  it('opens the exported document in the documents workspace without creating another one', async () => {
    vi.mocked(api.get).mockImplementation(async url => url.endsWith('/doc-1')
      ? { id: 'doc-1', title: '产品访谈 · 访谈素材', plain_text: '原话', version: 1 }
      : { count: 0, results: [] });
    const router = createMemoryRouter([{ path: '/documents', element: <DocumentsWorkspace base="/documents-api" /> }],
      { initialEntries: ['/documents?document=doc-1'] });
    await act(async () => root.render(<ConfigProvider><RouterProvider router={router} /></ConfigProvider>));
    await settle();
    expect(document.querySelector('[data-testid="linked-document"]')?.textContent).toBe('产品访谈 · 访谈素材');
    expect(api.get).toHaveBeenCalledWith('/documents-api/doc-1');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('keeps failed confirmation actionable without reporting success', async () => {
    vi.mocked(api.post).mockImplementation(async url => {
      if (url.endsWith('/confirm-actions')) throw new Error('待办应用不可用');
      return { token: 't', expires_in: 3600 };
    });
    await detail();
    await click([...document.querySelectorAll<HTMLElement>('[role="tab"]')].find(e => e.textContent?.startsWith('行动项'))!);
    await click(document.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
    await click(button('确认加入待办（1）'));
    expect(document.body.textContent).toContain('待办应用不可用');
    expect(document.body.textContent).not.toContain('已加入待办。');
    expect(button('确认加入待办（1）').disabled).toBe(false);
  });

  it('opens a queued record from its URL after refresh', async () => {
    vi.mocked(api.get).mockImplementation(async url => url.endsWith('/records') ? { count: 1, results: [fixture] } : { ...fixture, status: 'queued', segments: [], analysis: {}, actions: [], analysis_version: 0 });
    await wrap(createElement(MeetingWorkspace, { base }), '/?record=record-1');
    expect(document.body.textContent).toContain('排队中');
    expect(button('取消处理').disabled).toBe(false);
    expect(api.get).toHaveBeenCalledWith(`${base}/records/record-1`, undefined, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it('shows upload progress and passes the selected recording to the caller', async () => {
    let resolveUpload: (record: MeetingRecord) => void = () => {};
    vi.mocked(api.post).mockImplementation((_url, _data, config) => {
      config?.onUploadProgress?.({ loaded: 20, total: 100, bytes: 20, lengthComputable: true });
      return new Promise<MeetingRecord>(resolve => { resolveUpload = resolve; });
    });
    const onCreated = vi.fn();
    await wrap(createElement(UploadRecording, { client: meetingApi(base), onClose: vi.fn(), onCreated }));
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(fileInput, 'files', { value: [new File(['audio'], 'recording.wav')] });
    await act(async () => fileInput.dispatchEvent(new Event('change', { bubbles: true })));
    await act(async () => document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(document.body.textContent).toContain('正在上传');
    expect(button('取消').disabled).toBe(true);
    await act(async () => resolveUpload(fixture));
    expect(onCreated).toHaveBeenCalledWith(fixture);
  });
});

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { repoApi, type RepoContent, type RepoCopyDocument, type RepoDocument } from '@/services/repoExplainer';
import RepoContentEditor from '../repo/RepoContentEditor';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
let root: Root;
let container: HTMLDivElement;
let saved: RepoContent;
const handed = vi.fn();
const dirty = vi.fn();
const destinations = [{ id: 1, name: '动画制作', slug: 'animation-studio' }, { id: 2, name: '文案转剪映', slug: 'copy-to-jianying' }];
const makeDoc = (kind: RepoCopyDocument['kind']): RepoCopyDocument => ({
  schema_version: 2, kind, title: '工具介绍', cover: '封面', alternatives: ['备选标题'], aspect: '16:9', duration: 60,
  skill: { slug: kind === 'video' ? 'write-short-video-copy' : 'write-image-text-copy', sha256: 'a'.repeat(64) },
  paragraphs: [{ heading: '', text: '原始文案', feature_ids: ['f1'], evidence_ids: ['e1'], needs_review: true }],
  publish_copy: '配文', notes: [], needs_review: true,
});
const render = () => act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}>
  <RepoContentEditor initial={structuredClone(saved)} client={repoApi('/repo')} projectId="p" destinations={destinations} onDirty={dirty} onHandoff={handed} />
</ConfigProvider>));
const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label);
const changeText = (value: string) => act(async () => {
  const input = container.querySelector<HTMLTextAreaElement>('[aria-label="文案正文 1"]')!;
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
});
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  const doc = makeDoc('video');
  saved = { id: 'c', analysis_id: 'a', title: doc.title, revision: 1, draft: doc, versions: [{ id: 'v1', revision: 1, document: structuredClone(doc) }] };
  vi.mocked(api.put).mockImplementation(async (_url, body) => {
    const data = body as { document: RepoDocument; revision: number };
    expect(data.revision).toBe(saved.revision);
    saved = { ...saved, revision: saved.revision + 1, draft: data.document,
      versions: [{ id: 'v2', revision: saved.revision + 1, document: data.document }, ...saved.versions] };
    return structuredClone(saved);
  });
  vi.mocked(api.post).mockResolvedValue({ id: 'handoff', status: '作品草稿已创建', url: '/target' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('copy-only editor and production handoff', () => {
  it.each([['导入动画制作', 1], ['导入文案转剪映', 2]])('saves edited video copy and freezes its version before %s', async (label, target) => {
    await render();
    expect(container.textContent).toContain('write-short-video-copy');
    expect(button('添加分镜')).toBeUndefined();
    expect(container.textContent).not.toContain('画面建议');
    await changeText('修改后的完整视频文案');
    await act(async () => button(String(label))!.click());
    expect(api.put).toHaveBeenCalledWith('/repo/projects/p/contents/c', expect.objectContaining({
      revision: 1, document: expect.objectContaining({ kind: 'video', paragraphs: [expect.objectContaining({ text: '修改后的完整视频文案' })] }),
    }));
    expect(api.post).toHaveBeenCalledWith('/repo/projects/p/handoffs', { version_id: 'v2', target_id: target }, expect.anything());
    expect(handed).toHaveBeenCalledOnce();
    expect(saved.versions[1].document).toMatchObject({ paragraphs: [{ text: '原始文案' }] });
  });

  it('edits and autosaves image-text copy with no production entry', async () => {
    saved.draft = makeDoc('image_text'); saved.versions[0].document = structuredClone(saved.draft);
    await render();
    expect(container.textContent).toContain('write-image-text-copy');
    expect(container.textContent).toContain('上图文字');
    expect(button('导入动画制作')).toBeUndefined();
    expect(button('导入文案转剪映')).toBeUndefined();
    expect(button('导出Markdown')).toBeDefined();
    await changeText('图文作品的上图文字');
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(saved.draft).toMatchObject({ kind: 'image_text', paragraphs: [{ text: '图文作品的上图文字' }] });
    expect(api.post).not.toHaveBeenCalled();
  });

  it('preserves local copy on conflict and hands off only after resolving it', async () => {
    await render();
    const latest = { ...saved, revision: 3, draft: { ...makeDoc('video'), title: '服务器标题' } };
    vi.mocked(api.put).mockRejectedValueOnce({ response: { data: { detail: '服务器已有新版本', current: latest } } });
    await changeText('需要保留的本地内容');
    await act(async () => button('导入动画制作')!.click());
    expect(container.querySelector<HTMLTextAreaElement>('[aria-label="文案正文 1"]')!.value).toBe('需要保留的本地内容');
    expect(api.post).not.toHaveBeenCalled();
    expect(button('导入动画制作')!.disabled).toBe(true);
    saved = latest;
    await act(async () => button('保留本地内容另存新版本')!.click());
    expect(saved.revision).toBe(4);
    expect(saved.draft).toMatchObject({ paragraphs: [{ text: '需要保留的本地内容' }] });
  });
});

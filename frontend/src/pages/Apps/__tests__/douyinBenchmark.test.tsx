// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { douyinApi, metric, type DouyinTask } from '@/services/douyinBenchmark';
import { applicationPath } from '@/lib/applicationCatalog';
import { DouyinHome } from '../DouyinBenchmarkPage';
import { DouyinWorkspace } from '../douyin/DouyinWorkspace';
import { AnalysisResult } from '../douyin/AnalysisResult';
import { ScriptEditor } from '../douyin/ScriptEditor';
import { RewritePanel } from '../douyin/RewritePanel';
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const account = { id: 'a1', source_url: 'https://www.douyin.com/user/test', name: '知识账号', group: '', notes: '', profile: {}, updated_at: '2026-09-29' };
const work = { id: 'w1', title: '如何读书', likes: 0, comments: null, collects: null, shares: null, ratio: null, published_at: null, duration: 60, url: 'https://www.douyin.com/?modal_id=7536599534051626299', video_url: 'https://v3.douyinvod.com/real-file.mp4', cover: '', kind: 'video' };
const script = { title: '读书的新角度', cover: '从问题开始', narration: '今天讨论一个问题。', scenes: [{ time: '0–5秒', visual: '固定机位', spoken: '今天讨论一个问题。' }], checklist: ['准备提词器'] };
const task: DouyinTask = { id: 't1', kind: 'breakdown', work_id: 'w1', run_id: 'r1', status: 'succeeded', stage: 'completed', error: '', created_at: '2026-09-29', progress: {}, sources: [], output: { visual_status: 'pending', visual_note: '未配置视觉模型，已保留转写和关键帧', segments: [{ id: 's1', start: 0, end: 5, text: '你有没有遇到过这种情况？' }], claims: [{ type: 'observation', text: '以提问开场', refs: ['s1'] }] } };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  const computed = window.getComputedStyle;
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computed(element));
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/accounts')) return { count: 1, results: [account] };
    if (url.endsWith('/connection')) return { connected: false, message: '采集登录状态已失效' };
    if (url.endsWith('/collector-config')) return { configured: true, user_agent: 'Chrome saved UA', has_cookies: true, screen: '1920x1080', language: 'zh-CN', timezone: 'Asia/Shanghai', updated_at: null };
    if (url.endsWith('/brands')) return [];
    if (url.endsWith('/works')) return { items: [work], sample_size: 1, median_likes: null, explanation: '样本不足10条', batch: { ...task, kind: 'collect', output: { actual: 1, complete: true } } };
    if (url.endsWith('/tasks')) return { count: 1, results: [task] };
    if (url.endsWith('/tasks/t1')) return task;
    if (url.endsWith('/versions')) return [{ id: 'v1', revision: 1, content: script, created_at: '2026-09-29' }];
    return account;
  });
  vi.mocked(api.post).mockResolvedValue(task);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(node: React.ReactNode) { await act(async () => root.render(<MemoryRouter>{node}</MemoryRouter>)); }
async function click(text: string) {
  const candidates = [...document.querySelectorAll<HTMLElement>('button,[role="tab"]')];
  const element = candidates.find((el) => el.textContent === text) ?? candidates.find((el) => el.textContent?.includes(text));
  expect(element, text).toBeDefined(); await act(async () => element!.click());
}
async function setText(label: string, value: string) {
  const element = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!;
  expect(element).not.toBeNull();
  const proto = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(element, value); element.dispatchEvent(new Event('input', { bubbles: true })); });
}

describe('Douyin benchmark workflow', () => {
  it('exports the selected historical account analysis rather than the latest task', async () => {
    const old: DouyinTask = { ...task, id: 'historical-account', kind: 'account', created_at: '2026-09-20T08:00:00Z' };
    const latest = { ...old, id: 'latest-account', created_at: '2026-10-08T08:00:00Z' };
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => {
      if (url.endsWith('/tasks')) return Promise.resolve({ count: 2, results: [latest, old] });
      if (url.endsWith('/tasks/historical-account')) return Promise.resolve(old);
      if (url.endsWith('/download')) return Promise.resolve(new Blob(['历史分析']));
      return original(url, ...args);
    });
    const createUrl = vi.fn().mockReturnValue('blob:account');
    vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: createUrl, revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    expect(container.textContent).not.toContain('导出 Markdown');
    await act(async () => container.querySelector('.douyin-history .ant-select-selector')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find(el => el.textContent?.includes(new Date(old.created_at).toLocaleString('zh-CN')));
    expect(option).toBeDefined();
    await act(async () => option!.click());
    await click('导出 Markdown');
    expect(api.get).toHaveBeenLastCalledWith('/dy/accounts/a1/tasks/historical-account/download', undefined, { responseType: 'blob' });
    expect(createUrl).toHaveBeenCalledTimes(1);
  });
  it('starts text-only replication from a library video', async () => {
    const transcript = { ...task, id: 'transcript-1', kind: 'transcribe', output: { text: '原始文案。' }, copy_context: { work_title: '如何读书' } };
    vi.mocked(api.post).mockResolvedValue(transcript);
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/tasks/transcript-1') ? Promise.resolve(transcript) : original(url, ...args));
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库');
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('.douyin-work-actions button')].find(button => button.textContent === '爆款复刻')!.click());
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks', { kind: 'transcribe', work_id: 'w1' }, expect.anything());
    expect((container.querySelector('[aria-label="口播原文"]') as HTMLTextAreaElement).value).toBe('原始文案。');
    expect(container.textContent).toContain('来源作品：如何读书');
  });
  it('shows transcription progress, cancels, and offers explicit retry without rewriting', async () => {
    let transcript: DouyinTask = { ...task, id: 'transcript-1', kind: 'transcribe', status: 'running', stage: '转写口播', progress: { current: 2, total: 10 }, output: {} };
    vi.mocked(api.post).mockImplementation(async url => {
      if (url.endsWith('/cancel')) transcript = { ...transcript, status: 'cancelled' };
      return transcript;
    });
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/tasks/transcript-1') ? Promise.resolve(transcript) : original(url, ...args));
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库');
    await act(async () => [...container.querySelectorAll<HTMLButtonElement>('.douyin-work-actions button')].find(button => button.textContent === '爆款复刻')!.click());
    expect(container.textContent).toContain('转写口播');
    expect(container.querySelector('[aria-label="口播原文"]')).toBeNull();
    await click('取消任务');
    expect(api.post).toHaveBeenLastCalledWith('/dy/accounts/a1/tasks/transcript-1/cancel');
    expect(container.textContent).toContain('任务已取消');
    await click('重试转写');
    expect(api.post).toHaveBeenLastCalledWith('/dy/accounts/a1/tasks', { kind: 'transcribe', work_id: 'w1', force: true }, expect.anything());
    expect(vi.mocked(api.post).mock.calls.some(([, body]) => (body as { kind?: string })?.kind === 'rewrite')).toBe(false);
  });
  it.each(['talking_head', 'screencast', 'animation', 'live_action', 'mixed'])('passes the selected %s format to topic generation', async format => {
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库'); await click('转写并拆解'); await click('用这份拆解创作');
    await act(async () => container.querySelector<HTMLInputElement>(`input[name="production-format"][value="${format}"]`)!.click());
    await setText('positioning', '知识分享'); await setText('theme', '高效读书');
    await click('生成 3 个选题方向');
    expect(api.post).toHaveBeenLastCalledWith('/dy/accounts/a1/tasks', expect.objectContaining({ kind: 'topics', source_task_id: 't1', production_format: format }), expect.anything());
    expect(container.querySelector<HTMLInputElement>(`input[value="${format}"]`)?.checked).toBe(true);
  });

  it('registers its route and distinguishes unavailable metrics from zero', () => {
    expect(applicationPath({ id: 'douyin-benchmark', applicationId: 42, rendererKey: 'douyin-benchmark', kind: 'custom' })).toBe('/applications/42/douyin-benchmark?entry=apps');
    expect(metric(null)).toBe('未获取'); expect(metric(0)).toBe('0');
  });
  it('shows login failure while keeping existing accounts accessible', async () => {
    await render(<DouyinHome base="/dy" />);
    expect(container.textContent).toContain('采集登录状态已失效'); expect(container.textContent).toContain('知识账号');
  });
  it('keeps the account destination selected in its workspace and returns through the sidebar', async () => {
    await render(<DouyinHome base="/dy" />);
    await act(async () => container.querySelector<HTMLButtonElement>('.douyin-account-card')!.click());
    expect(container.querySelector('h1')?.textContent).toBe('账号研究');
    expect(container.querySelector('.douyin-nav [aria-current="page"]')?.textContent).toBe('对标账号');
    await click('作品库');
    expect(container.textContent).toContain('如何读书');
    await act(async () => container.querySelector<HTMLAnchorElement>('.douyin-nav [aria-current="page"]')!.click());
    expect(container.textContent).toContain('我的对标账号');
    expect(container.querySelector('h1')?.textContent).toBe('对标账号');
  });
  it('adds an account and sends an idempotency key', async () => {
    vi.mocked(api.post).mockResolvedValue({ ...account, task });
    await render(<DouyinHome base="/dy" />); await click('添加对标账号');
    await setText('主页链接或分享文本', account.source_url); await click('添加并采集');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts', expect.objectContaining({ source: account.source_url, count: 50 }), expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
  });
  it.each(['missing', 'throwing', 'absent'])('adds and retries an account when crypto is %s', async (mode) => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : {
      randomUUID: () => { throw new Error('Insecure context'); },
    });
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络连接中断')).mockResolvedValue({ ...account, task });
    await render(<DouyinHome base="/dy" />);
    await click('添加对标账号');
    await setText('主页链接或分享文本', account.source_url);
    await click('添加并采集');
    expect(document.body.textContent).toContain('网络连接中断');
    const first = vi.mocked(api.post).mock.calls[0][2]?.headers?.['Idempotency-Key'];
    expect(first).toEqual(expect.any(String));
    await click('添加并采集');
    expect(api.post).toHaveBeenNthCalledWith(2, '/dy/accounts', expect.objectContaining({ source: account.source_url }), { headers: { 'Idempotency-Key': first } });
    expect(container.querySelector('h1')?.textContent).toBe('账号研究');
    await click('添加对标账号');
    await setText('主页链接或分享文本', account.source_url);
    await click('添加并采集');
    expect(vi.mocked(api.post).mock.calls[2][2]?.headers?.['Idempotency-Key']).not.toBe(first);
  });
  it('renders missing counts and launches video breakdown from the work list', async () => {
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库'); expect(container.textContent).toContain('未获取');
    await click('转写并拆解');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks', { kind: 'breakdown', work_id: 'w1' }, expect.anything());
    expect(container.textContent).toContain('以提问开场');
  });
  it('keeps work results when refresh fails', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('采集服务不可用'));
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库'); await click('刷新作品数据');
    expect(container.textContent).toContain('如何读书'); expect(container.textContent).toContain('采集服务不可用');
  });
  it('opens timestamped evidence and identifies missing visual analysis', async () => {
    await render(<AnalysisResult client={douyinApi('/dy')} accountId="a1" task={task} />);
    expect(container.textContent).toContain('未配置视觉模型');
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="查看出处 s1"]')!.click());
    expect(document.body.textContent).toContain('0.0–5.0秒'); expect(document.body.textContent).toContain('你有没有遇到过这种情况？');
  });
  it('saves a new script version without overwriting the prior one', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 'v2', revision: 2, content: { ...script, narration: '改成我的表达。' }, created_at: '2026-09-29' });
    await render(<ScriptEditor client={douyinApi('/dy')} accountId="a1" taskId="t1" />);
    await setText('完整口播稿', '改成我的表达。');
    expect([...container.querySelectorAll('button')].find(button => button.textContent === '导入动画制作')?.disabled).toBe(true);
    await click('保存新版本');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks/t1/versions', { revision: 1, content: { ...script, narration: '改成我的表达。' } });
    expect(container.textContent).toContain('已保存新版本');
  });
  it('shows the account empty state', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/accounts') ? Promise.resolve({ count: 0, results: [] }) : original(url, ...args));
    await render(<DouyinHome base="/dy" />); expect(container.textContent).toContain('添加第一个账号');
  });
});


describe('text replication editor', () => {
  const context = { work_title: '如何读书', source_task_id: 'transcript-1', source_text: '已校正的原文', rewrite_requirements: '简洁自然' };
  const rewrite: DouyinTask = { ...task, id: 'rewrite-1', kind: 'rewrite', output: { text: '改写结果' }, copy_context: context };

  function versions() {
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/versions') ? Promise.resolve([{ id: 'copy-v1', revision: 1, content: { text: '改写结果' }, created_at: '2026-09-30' }]) : original(url, ...args));
  }

  it('requires corrected nonempty text and submits optional instructions without scenes', async () => {
    const onRun = vi.fn().mockResolvedValue(undefined);
    await render(<RewritePanel client={douyinApi('/dy')} accountId="a1" task={{ ...task, kind: 'transcribe', output: { text: '', transcript_note: '未识别到口播，请手工补全原文。' } }} busy={false} onRun={onRun} />);
    expect([...container.querySelectorAll('button')].find(b => b.textContent === '生成改写文案')?.disabled).toBe(true);
    await setText('口播原文', '校正后的文案'); await setText('改写要求', '开头更直接'); await click('生成改写文案');
    expect(onRun).toHaveBeenLastCalledWith({ kind: 'rewrite', work_id: 'w1', source_task_id: 't1', source_text: '校正后的文案', rewrite_requirements: '开头更直接' });
    await click('重新转写');
    expect(onRun).toHaveBeenLastCalledWith({ kind: 'transcribe', work_id: 'w1', force: true });
    expect(container.textContent).not.toContain('分镜与拍摄');
  });

  it('restores frozen source and edits, copies, saves and exports a new text version', async () => {
    versions();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    vi.mocked(api.post).mockResolvedValue({ id: 'copy-v2', revision: 2, content: { text: '手工修改的结果' }, created_at: '2026-09-30' });
    await render(<RewritePanel client={douyinApi('/dy')} accountId="a1" task={rewrite} busy={false} onRun={vi.fn()} />);
    expect((container.querySelector('[aria-label="口播原文"]') as HTMLTextAreaElement).value).toBe(context.source_text);
    expect((container.querySelector('[aria-label="改写要求"]') as HTMLTextAreaElement).value).toBe(context.rewrite_requirements);
    await setText('改写正文', '手工修改的结果'); await click('复制文案');
    expect(writeText).toHaveBeenCalledWith('手工修改的结果');
    expect([...container.querySelectorAll('button')].find(b => b.textContent === '导出文案 Markdown')?.disabled).toBe(true);
    await click('保存文案新版本');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks/rewrite-1/versions', { revision: 1, content: { text: '手工修改的结果' } });
    expect(container.textContent).toContain('已保存新版本');
    const createUrl = vi.fn().mockReturnValue('blob:copy');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.mocked(api.get).mockResolvedValue(new Blob(['手工修改的结果']));
    await click('导出文案 Markdown');
    expect(api.get).toHaveBeenLastCalledWith('/dy/accounts/a1/tasks/rewrite-1/versions/copy-v2/download', undefined, { responseType: 'blob' });
  });

  it('retains unsaved text after version conflict and supports retry with frozen source', async () => {
    versions();
    vi.mocked(api.post).mockRejectedValue(new Error('脚本已被更新，请重新加载后保存。'));
    await render(<RewritePanel client={douyinApi('/dy')} accountId="a1" task={rewrite} busy={false} onRun={vi.fn()} />);
    await setText('改写正文', '保留我的修改'); await click('保存文案新版本');
    expect((container.querySelector('[aria-label="改写正文"]') as HTMLTextAreaElement).value).toBe('保留我的修改');
    expect(container.textContent).toContain('已被更新');
    const onRun = vi.fn().mockResolvedValue(undefined);
    await render(<RewritePanel key="failed" client={douyinApi('/dy')} accountId="a1" task={{ ...rewrite, status: 'failed' }} busy={false} onRun={onRun} />);
    await click('重试改写');
    expect(onRun).toHaveBeenCalledWith({ kind: 'rewrite', work_id: 'w1', source_task_id: 'transcript-1', source_text: context.source_text, rewrite_requirements: context.rewrite_requirements });
  });

  it('does not strand the editor in loading state after version fetch failure', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('版本加载失败'));
    await render(<RewritePanel client={douyinApi('/dy')} accountId="a1" task={rewrite} busy={false} onRun={vi.fn()} />);
    expect(container.textContent).toContain('版本加载失败');
    expect(container.textContent).toContain('重新加载文案');
    expect(container.textContent).not.toContain('正在加载文案');
  });
});

describe('personal collector settings', () => {
  it('keeps saved cookies blank and saves replacement credentials', async () => {
    vi.mocked(api.put).mockResolvedValue({ configured: true });
    await render(<DouyinHome base="/dy" />); await click('采集设置');
    expect((document.querySelector('[aria-label="采集 Cookie"]') as HTMLTextAreaElement).value).toBe('');
    expect(document.body.textContent).toContain('已保存，留空保留原值');
    await setText('采集 User-Agent', 'new Chrome UA'); await setText('采集 Cookie', 'UIFID_TEMP=personal-cookie');
    await click('保存配置');
    expect(api.put).toHaveBeenCalledWith('/dy/collector-config', expect.objectContaining({ user_agent: 'new Chrome UA', cookies: 'UIFID_TEMP=personal-cookie' }));
    expect(document.querySelector('[aria-label="采集 Cookie"]')).toBeNull();
    await click('采集设置');
    expect((document.querySelector('[aria-label="采集 Cookie"]') as HTMLTextAreaElement).value).toBe('');
  });
  it('clears only the personal collector configuration', async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);
    await render(<DouyinHome base="/dy" />); await click('采集设置'); await click('清除已保存配置');
    expect(api.delete).toHaveBeenCalledWith('/dy/collector-config');
    expect(document.querySelector('[aria-label="采集 Cookie"]')).toBeNull();
  });
  it('keeps the form open on a configuration error', async () => {
    vi.mocked(api.put).mockRejectedValue(new Error('Cookie 格式错误'));
    await render(<DouyinHome base="/dy" />); await click('采集设置'); await click('保存配置');
    expect(document.body.textContent).toContain('Cookie 格式错误');
    expect(document.querySelector('[aria-label="采集 Cookie"]')).not.toBeNull();
  });
});


it('opens DTK media for playback and keeps the Douyin source page separate', async () => {
  await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={() => {}} />);
  await click('作品库');
  const links = [...container.querySelectorAll('a')];
  expect(links.find((link) => link.textContent === '播放视频')?.getAttribute('href')).toBe('https://v3.douyinvod.com/real-file.mp4');
  expect(links.find((link) => link.textContent === '抖音来源页')?.getAttribute('href')).toBe('https://www.douyin.com/?modal_id=7536599534051626299');
});

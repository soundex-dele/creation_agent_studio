// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { openApplicationWindowWhenReady } from '../applicationPresentation';

afterEach(() => vi.restoreAllMocks());

function reserveWindow() {
  const popup = { opener: window as Window | null, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
  vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
  return popup;
}

it('reserves a detached window before creating a resource and leaves the source page alone', async () => {
  const popup = reserveWindow();
  let finish!: (path: string) => void;
  const pending = openApplicationWindowWhenReady(() => new Promise(resolve => { finish = resolve; }));
  expect(window.open).toHaveBeenCalledWith('about:blank', '_blank');
  expect(popup.opener).toBeNull();
  expect(popup.location.replace).not.toHaveBeenCalled();
  finish('/chat?conversation=42&embedded=1');
  await expect(pending).resolves.toBe(true);
  expect(popup.location.replace).toHaveBeenCalledWith('/chat?conversation=42&entry=apps&standalone=1');
  expect(popup.close).not.toHaveBeenCalled();
});

it('does not create a resource when the browser blocks the window', async () => {
  vi.spyOn(window, 'open').mockReturnValue(null);
  const create = vi.fn();
  await expect(openApplicationWindowWhenReady(create)).rejects.toThrow('新窗口被浏览器拦截');
  expect(create).not.toHaveBeenCalled();
});

it('closes the reserved window when creation fails', async () => {
  const popup = reserveWindow();
  await expect(openApplicationWindowWhenReady(async () => { throw new Error('创建失败'); })).rejects.toThrow('创建失败');
  expect(popup.close).toHaveBeenCalledOnce();
  expect(popup.location.replace).not.toHaveBeenCalled();
});

it('closes the reserved window when its originating context is no longer valid', async () => {
  const popup = reserveWindow();
  await expect(openApplicationWindowWhenReady(async () => null)).resolves.toBe(false);
  expect(popup.close).toHaveBeenCalledOnce();
  expect(popup.location.replace).not.toHaveBeenCalled();
});

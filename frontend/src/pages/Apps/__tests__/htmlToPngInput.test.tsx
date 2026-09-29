// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import HtmlToPngInput from '../HtmlToPngInput';

vi.mock('../FolderPickerModal', () => ({ default: ({ open, onSelect }: { open: boolean; onSelect: (path: string) => void }) => open ? <button onClick={() => onSelect('/covers')}>选取测试目录</button> : null }));
let root: Root;
let host: HTMLDivElement;
const onStart = vi.fn();
const click = async (text: string) => {
  const button = [...host.querySelectorAll('button')].find(item => item.textContent === text);
  expect(button, text).toBeDefined();
  await act(async () => button!.click());
};
const input = async (id: string, value: string) => {
  const element = host.querySelector<HTMLInputElement>(`#${id}`)!;
  expect(element).not.toBeNull();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  });
};
beforeEach(async () => {
  onStart.mockReset();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn() }));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><HtmlToPngInput loading={false} onStart={onStart} /></ConfigProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

it('deduplicates selected directories and retains all existing default conversion parameters', async () => {
  for (let i = 0; i < 2; i++) { await click('选择目录'); await click('选取测试目录'); }
  expect(host.querySelectorAll('.conversion-directory')).toHaveLength(1);
  expect(host.querySelector('details')?.open).toBe(false);
  await click('开始转换');
  expect(onStart).toHaveBeenCalledWith({ directories: ['/covers'], orientation: 'horizontal', device_scale_factor: 2,
    selector: '.cover', wait_until: 'networkidle', full_page: false, transparent: false, no_web_fonts: false });
});

it('submits edited dimensions and advanced options without losing values when collapsed', async () => {
  await click('手动添加');
  await input('conversion-directory-0', '  /custom  ');
  await input('conversion-width', '1080');
  await input('conversion-height', '1440');
  await input('conversion-scale', '3');
  const details = host.querySelector('details')!;
  await act(async () => { details.open = true; });
  await input('conversion-selector', '.article');
  for (const label of ['截取整页', '透明背景', '移除网络字体']) {
    const checkbox = [...host.querySelectorAll('label')].find(item => item.textContent === label)!.querySelector('input')!;
    await act(async () => checkbox.click());
  }
  expect(host.querySelector<HTMLInputElement>('#conversion-selector')?.disabled).toBe(true);
  await act(async () => { details.open = false; });
  await click('开始转换');
  expect(onStart).toHaveBeenCalledWith({ directories: ['/custom'], orientation: 'horizontal', width: 1080, height: 1440,
    device_scale_factor: 3, selector: '.article', wait_until: 'networkidle', full_page: true, transparent: true, no_web_fonts: true });
});

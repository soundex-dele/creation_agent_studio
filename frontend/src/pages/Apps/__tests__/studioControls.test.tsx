// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StudioFilePicker, StudioSelect } from '../animation/StudioControls';

let host: HTMLDivElement; let root: Root;
beforeEach(() => {
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });

describe('studio form controls', () => {
  it('opens with the keyboard, filters long option lists and applies a selection', async () => {
    function Example() {
      const [value, setValue] = useState('0');
      return <label>音色<StudioSelect value={value} onChange={event => setValue(event.target.value)}>
        {Array.from({ length: 8 }, (_, i) => <option key={i} value={i}>音色 {i}</option>)}
      </StudioSelect></label>;
    }
    await act(async () => root.render(<Example />));
    const input = host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
    expect(input.labels?.[0].textContent).toContain('音色');
    await act(async () => { input.focus(); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', keyCode: 40, bubbles: true })); });
    expect(input.getAttribute('aria-expanded')).toBe('true');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '音色 7');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(document.querySelectorAll('.studio-select-popup [data-option-value]')).toHaveLength(1);
    await act(async () => document.querySelector<HTMLElement>('[data-option-value="7"]')!.click());
    expect(host.querySelector<HTMLElement>('.studio-select-field')?.dataset.value).toBe('7');
    expect(input.getAttribute('aria-expanded')).toBe('false');
  });

  it('keeps locked controls disabled and flattens fragment options', async () => {
    const change = vi.fn();
    await act(async () => root.render(<label>字体<StudioSelect disabled value="font" onChange={change}><><option value="font">字体一</option></></StudioSelect></label>));
    expect(host.querySelector<HTMLInputElement>('input')?.disabled).toBe(true);
    expect(host.textContent).toContain('字体一');
    await act(async () => host.querySelector('.ant-select-selector')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    expect(document.querySelector('.studio-select-popup')).toBeNull();
    expect(change).not.toHaveBeenCalled();
  });

  it('shows file name and pending state, reports failures and allows choosing the same file again', async () => {
    let reject!: (error: Error) => void;
    const select = vi.fn().mockImplementationOnce(() => new Promise<void>((_, fail) => { reject = fail; })).mockResolvedValue(undefined);
    const report = vi.fn();
    await act(async () => root.render(<StudioFilePicker title="上传图片" hint="PNG / JPG" accept=".png,.jpg" onSelect={select} onError={report} />));
    const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
    expect(input.accept).toBe('.png,.jpg');
    const file = new File(['image'], '很长的素材名称.png', { type: 'image/png' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
    expect(input.disabled).toBe(true);
    expect(host.querySelector('[role="status"]')?.textContent).toContain('正在处理：很长的素材名称.png');
    expect(input.value).toBe('');
    await act(async () => reject(new Error('上传失败')));
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ message: '上传失败' }));
    expect(input.disabled).toBe(false);
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
    expect(select).toHaveBeenCalledTimes(2);
    expect(select).toHaveBeenLastCalledWith(file);
    expect(host.textContent).toContain('重新选择');
    Object.defineProperty(input, 'files', { value: [], configurable: true });
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
    expect(select).toHaveBeenCalledTimes(2);
  });
});

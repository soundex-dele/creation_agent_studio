import { Children, Fragment, isValidElement, useId, useState, type ReactNode } from 'react';
import { Select, Spin } from 'antd';
import { Check, ChevronDown, FileCheck2, UploadCloud } from 'lucide-react';

type Option = { value: string; label: ReactNode; search: string; disabled?: boolean };
type OptionProps = { value?: string | number; children?: ReactNode; disabled?: boolean };
const text = (children: ReactNode): string => Children.toArray(children).map(child => isValidElement<OptionProps>(child) ? text(child.props.children) : String(child)).join('');
function optionsFrom(children: ReactNode): Option[] {
  const options: Option[] = [];
  Children.forEach(children, child => {
    if (!isValidElement<OptionProps>(child)) return;
    if (child.type === Fragment) options.push(...optionsFrom(child.props.children));
    if (child.type === 'option') options.push({ value: String(child.props.value ?? text(child.props.children)), label: child.props.children,
      search: text(child.props.children), disabled: child.props.disabled });
  });
  return options;
}

export function StudioSelect({ value, children, disabled, onChange }: {
  value?: string | number; children: ReactNode; disabled?: boolean;
  onChange: (event: { target: { value: string } }) => void;
}) {
  const id = useId();
  const options = optionsFrom(children);
  const selected = value === undefined ? options[0]?.value : String(value);
  return <span className="studio-select-field" data-value={selected || ''}>
    <Select id={id} className="studio-select" value={selected} disabled={disabled} options={options}
      onChange={next => onChange({ target: { value: next } })} showSearch={options.length > 6} optionFilterProp="search"
      virtual={false} listHeight={264} classNames={{ popup: { root: 'studio-select-popup' } }}
      suffixIcon={<ChevronDown size={16} aria-hidden="true" />} menuItemSelectedIcon={<Check size={16} aria-hidden="true" />}
      notFoundContent="暂无可选项" optionRender={option => <span data-option-value={String(option.value)}>{option.label}</span>} />
  </span>;
}

export function StudioFilePicker({ title, hint, accept, disabled, onSelect, onError }: {
  title: string; hint: string; accept: string; disabled?: boolean;
  onSelect: (file: File) => Promise<void>; onError: (error: unknown) => void;
}) {
  const id = useId(); const [filename, setFilename] = useState(''); const [loading, setLoading] = useState(false);
  return <label className="studio-file-picker" aria-busy={loading}>
    <input type="file" accept={accept} disabled={disabled || loading} aria-label={title} aria-describedby={id}
      onChange={event => {
        const file = event.target.files?.[0]; event.target.value = '';
        if (!file) return;
        setFilename(file.name); setLoading(true);
        void Promise.resolve().then(() => onSelect(file)).catch(onError).finally(() => setLoading(false));
      }} />
    <span className="studio-file-icon" aria-hidden="true">{loading ? <Spin size="small" /> : filename ? <FileCheck2 size={24} /> : <UploadCloud size={24} />}</span>
    <span className="studio-file-copy"><strong>{title}</strong><span id={id}>{hint}</span>
      <span className="studio-file-status" role="status">{loading ? `正在处理：${filename}` : filename ? `已选择：${filename}` : '点击选择本地文件'}</span></span>
    <span className="studio-file-action" aria-hidden="true">{loading ? '处理中…' : filename ? '重新选择' : '选择文件'}</span>
  </label>;
}

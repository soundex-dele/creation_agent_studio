import { Input, InputNumber, Select, Switch } from 'antd';
import type { WorkflowRunInputField } from '@/types';

export function fixedWorkflowValue(field: Pick<WorkflowRunInputField, 'type' | 'options'>): unknown {
  if (field.type === 'boolean') return false;
  if (field.type === 'array') return [];
  if (field.options?.length) return field.options[0].value;
  if (field.type === 'number' || field.type === 'integer') return 0;
  return '';
}

export default function WorkflowFixedValueInput({ field, value, onChange }: {
  field: WorkflowRunInputField; value: unknown; onChange: (value: unknown) => void;
}) {
  if (field.type === 'boolean') return <Switch aria-label={field.label} checked={value === true} onChange={onChange} />;
  if (field.type === 'array') return <Select aria-label={field.label}
    mode={field.options?.length ? 'multiple' : 'tags'} value={Array.isArray(value) ? value : []}
    options={field.options} onChange={onChange} placeholder="逐项输入后按回车" />;
  if (field.options?.length) return <Select aria-label={field.label} value={value}
    options={field.options} onChange={onChange} />;
  if (field.type === 'number' || field.type === 'integer') return <InputNumber aria-label={field.label}
    value={typeof value === 'number' ? value : null} min={field.minimum} max={field.maximum}
    precision={field.type === 'integer' ? 0 : undefined} onChange={(next) => onChange(next ?? 0)} />;
  return <Input.TextArea aria-label={field.label} autoSize={{ minRows: 1, maxRows: 8 }}
    value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} placeholder="固定输入值" />;
}

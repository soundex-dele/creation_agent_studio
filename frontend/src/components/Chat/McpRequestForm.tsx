import React, { useState } from 'react';
import { Button, Alert } from 'antd';
import type { AgentQuestion } from '@/entities/run';
import './AgentActivityPanel.css';

interface Schema { type?: string; title?: string; description?: string; default?: unknown; enum?: unknown[]; properties?: Record<string, Schema>; required?: string[]; items?: Schema; }

function initialValues(schema: Schema): Record<string, unknown> {
  return Object.fromEntries(Object.entries(schema.properties ?? {}).flatMap(([name, field]) => {
    if (field.default !== undefined) return [[name, field.default]];
    if (field.type === 'boolean' && schema.required?.includes(name)) return [[name, false]];
    if (field.type === 'object' && schema.required?.includes(name)) return [[name, initialValues(field)]];
    return [];
  }));
}

function Field({ name, schema, value, onChange, required = false, depth = 0 }: {
  name: string; schema: Schema; value: unknown; onChange: (value: unknown) => void; required?: boolean; depth?: number;
}) {
  if (depth > 5) return <p>表单层级过深，请联系工具提供方。</p>;
  if (schema.type === 'object') return <fieldset><legend>{schema.title || name}</legend>
    {Object.entries(schema.properties ?? {}).map(([key, field]) => <Field key={key} name={key} schema={field}
      value={(value as Record<string, unknown> | undefined)?.[key]} required={schema.required?.includes(key)} depth={depth + 1}
      onChange={next => onChange({ ...(value as Record<string, unknown> ?? {}), [key]: next })} />)}
  </fieldset>;
  return <label><span>{schema.title || name}{required ? ' *' : ''}</span>
    {schema.description && <small>{schema.description}</small>}
    {schema.enum ? <select required={required} value={value === undefined ? '' : String(schema.enum.indexOf(value))}
      onChange={event => onChange(schema.enum![Number(event.target.value)])}>
      <option value="" disabled>请选择</option>{schema.enum.map((option, index) => <option key={index} value={index}>{String(option)}</option>)}
    </select> : schema.type === 'boolean' ? <input type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} />
      : schema.type === 'array' && schema.items?.enum ? <select multiple required={required}
        value={Array.isArray(value) ? value.map(entry => String(schema.items!.enum!.indexOf(entry))) : []}
        onChange={event => onChange(Array.from(event.target.selectedOptions, option => schema.items!.enum![Number(option.value)]))}>
        {schema.items.enum.map((option, index) => <option key={index} value={index}>{String(option)}</option>)}
      </select> : schema.type === 'array' ? <textarea value={Array.isArray(value) ? value.join('\n') : ''} required={required}
        placeholder="每行一项" onChange={event => onChange(event.target.value.split('\n').filter(Boolean).map(entry =>
          ['number', 'integer'].includes(schema.items?.type ?? '') ? Number(entry) : entry))} />
        : <input type={['number', 'integer'].includes(schema.type ?? '') ? 'number' : 'text'} required={required}
          step={schema.type === 'integer' ? 1 : 'any'} value={value == null ? '' : String(value)}
          onChange={event => onChange(['number', 'integer'].includes(schema.type ?? '') && event.target.value !== ''
            ? Number(event.target.value) : event.target.value)} />}
  </label>;
}

export default function McpRequestForm({ question, onAnswer }: {
  question: AgentQuestion;
  onAnswer: (answer: { action?: 'accept' | 'decline' | 'cancel'; content?: Record<string, unknown> }) => Promise<void>;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(question.formSchema ?? {}));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (action: 'accept' | 'decline' | 'cancel') => {
    setBusy(true); setError('');
    try { await onAnswer({ action, content: values }); }
    catch (failure) { setError((failure as Error).message || '提交失败，请检查表单内容'); }
    finally { setBusy(false); }
  };
  const schema = (question.formSchema ?? {}) as Schema;
  const url = question.url && /^https?:\/\//i.test(question.url) ? question.url : undefined;
  return <form className="agent-mcp-form" onSubmit={event => { event.preventDefault(); void submit('accept'); }}>
    {url && <a href={url} target="_blank" rel="noopener noreferrer">打开工具授权页面</a>}
    {Object.entries(schema.properties ?? {}).map(([name, field]) => <Field key={name} name={name} schema={field}
      value={values[name]} required={schema.required?.includes(name)} onChange={value => setValues(current => ({ ...current, [name]: value }))} />)}
    {error && <Alert type="error" message={error} />}
    <div className="agent-question-actions">
      <Button onClick={() => void submit('decline')} disabled={busy}>拒绝请求</Button>
      <Button onClick={() => void submit('cancel')} disabled={busy}>取消请求</Button>
      <Button type="primary" htmlType="submit" loading={busy}>{url ? '已完成，继续' : '提交'}</Button>
    </div>
  </form>;
}

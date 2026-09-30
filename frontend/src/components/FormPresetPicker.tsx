import { useEffect, useId, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, List, Modal, Popconfirm, Select, Space, Typography } from 'antd';
import { api } from '@/services/api';
import { formErrorMessage, presetSavePolicy, type FormAnswers } from '@/lib/formPresets';
import type { FormPreset, FormPresetSnapshot, GuidedPrompt } from '@/types';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import './FormPresetPicker.css';

type PersonalPreset = FormPreset & { prompt_key: string };
interface Props {
  applicationSlug: string;
  prompt: GuidedPrompt;
  value: FormPresetSnapshot | null;
  onChange: (preset: FormPresetSnapshot | null) => void;
  answers?: FormAnswers;
  excludedFields?: string[];
  keepSnapshot?: boolean;
}

export default function FormPresetPicker(props: Props) {
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  return <FormPresetWorkspace key={`${organizationId}:${userId}:${props.applicationSlug}:${props.prompt.key}`} {...props} />;
}

function FormPresetWorkspace({ applicationSlug, prompt, value, onChange, answers = {}, excludedFields = [], keepSnapshot = false }: Props) {
  const pickerId = useId();
  const [personal, setPersonal] = useState<PersonalPreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [manage, setManage] = useState(false);
  const [editor, setEditor] = useState<{ id?: string; name: string; description: string; values: FormAnswers; keys: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const base = `/apps/${applicationSlug}/form-presets/`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setPersonal([]);
    void api.get<PersonalPreset[]>(base, { prompt_key: prompt.key }, { signal: controller.signal })
      .then((items) => { if (!controller.signal.aborted) setPersonal(Array.isArray(items) ? items : []); })
      .catch((e) => { if (!controller.signal.aborted) setError(formErrorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, prompt.key, revision]);
  const builtins = [...(prompt.presets || [])].sort((a, b) => (a.order || 0) - (b.order || 0));
  const key = (kind: string, id: string) => `${kind}:${id}`;
  const options = [
    { label: '不使用模板', value: '' },
    { label: '内置模板', options: builtins.map((p) => ({ label: p.name, value: key('builtin', p.id) })) },
    { label: '我的模板', options: personal.map((p) => ({ label: p.name, value: key('personal', p.id) })) },
    ...(value && !(value.kind === 'builtin' ? builtins : personal).some((p) => p.id === value.id)
      ? [{ label: `${value.name}（已保存的内容）`, value: key(value.kind, value.id) }] : []),
  ];
  const selectable = prompt.questions.filter((q) => presetSavePolicy(q) !== 'never');
  const openEditor = (preset?: PersonalPreset) => {
    setError(''); setManage(false);
    const values = preset?.values || answers;
    setEditor({ id: preset?.id, name: preset?.name || '', description: preset?.description || '', values: { ...values },
      keys: selectable.filter((q) => preset ? q.key in values : presetSavePolicy(q) === 'preference' && !excludedFields.includes(q.key) && values[q.key] !== undefined && values[q.key] !== '').map((q) => q.key) });
  };
  const save = async () => {
    if (!editor) return;
    if (!editor.name.trim()) { setError('请填写模板名称。'); return; }
    setSaving(true); setError('');
    try {
      const payload = { name: editor.name.trim(), description: editor.description, prompt_key: prompt.key,
        values: Object.fromEntries(editor.keys.map((k) => [k, editor.values[k] ?? ''])) };
      const saved = editor.id ? await api.patch<PersonalPreset>(`${base}${editor.id}/`, payload)
        : await api.post<PersonalPreset>(base, payload);
      if (!keepSnapshot && saved?.id && value?.kind === 'personal' && value.id === saved.id) {
        onChange({ ...saved, kind: 'personal' });
      }
      setEditor(null); setRevision((n) => n + 1);
    } catch (e) { setError(formErrorMessage(e)); }
    finally { setSaving(false); }
  };
  return <section className="form-preset-picker" aria-label="表单模板">
    <label htmlFor={pickerId}>预设模板</label>
    <Select id={pickerId} aria-label="预设模板" style={{ width: '100%' }} loading={loading} value={value ? key(value.kind, value.id) : ''} options={options}
      onSelect={(selected) => {
        if (!selected) { onChange(null); return; }
        const separator = selected.indexOf(':');
        const kind = selected.slice(0, separator);
        const id = selected.slice(separator + 1);
        const p = (kind === 'builtin' ? builtins : personal).find((item) => item.id === id);
        if (p) onChange({ ...p, kind: kind as FormPresetSnapshot['kind'], prompt_key: prompt.key });
      }} />
    {value?.description && <Typography.Text type="secondary">{value.description}</Typography.Text>}
    <Space className="form-preset-actions" size={12} wrap><Button onClick={() => openEditor()}>另存为模板</Button><Button onClick={() => { setError(''); setManage(true); }}>管理我的模板</Button></Space>
    <Typography.Text type="secondary">本次填写优先，其次是品牌资料、模板和默认值。</Typography.Text>
    {error && !editor && !manage && <Alert type="error" message={error} action={<Button onClick={() => setRevision((n) => n + 1)}>重试</Button>} />}
    {manage && <Modal title="我的模板" open onCancel={() => setManage(false)} footer={null} destroyOnHidden>
      {error && <Alert type="error" message={error} />}
      <List dataSource={personal} loading={loading} locale={{ emptyText: '还没有个人模板，可从当前表单另存。' }} renderItem={(p) => <List.Item actions={[
        <Button key="edit" onClick={() => openEditor(p)}>编辑</Button>,
        <Popconfirm key="delete" title="删除此模板？已保存的工作流内容不会改变。" onConfirm={async () => {
          try {
            await api.delete(`${base}${p.id}/`);
            if (!keepSnapshot && value?.kind === 'personal' && value.id === p.id) onChange(null);
            setRevision((n) => n + 1);
          }
          catch (e) { setError(formErrorMessage(e)); }
        }}><Button danger>删除</Button></Popconfirm>,
      ]}><List.Item.Meta title={p.name} description={p.description} /></List.Item>} />
    </Modal>}
    {editor && <Modal title={editor.id ? '编辑个人模板' : '另存为个人模板'} open onCancel={() => { if (!saving) setEditor(null); }} onOk={() => void save()} confirmLoading={saving} okText="保存" cancelText="取消" destroyOnHidden>
      {editor && <div className="form-preset-editor">
        <label>模板名称<Input maxLength={200} value={editor.name} onChange={(e) => setEditor({ ...editor, name: e.target.value })} /></label>
        <label>说明<Input.TextArea value={editor.description} onChange={(e) => setEditor({ ...editor, description: e.target.value })} /></label>
        <Typography.Text type="secondary">勾选需要复用的参数。主题和正文默认不保存；品牌继承值和文件不保存。</Typography.Text>
        {selectable.map((q) => {
          const excluded = !editor.id && excludedFields.includes(q.key);
          const selected = editor.keys.includes(q.key);
          const update = (v: string | string[] | number | null) => setEditor({ ...editor, values: { ...editor.values, [q.key]: v ?? '' } });
          return <div key={q.key}>
            <Checkbox disabled={excluded} checked={selected} onChange={(e) => setEditor({ ...editor, keys: e.target.checked ? [...editor.keys, q.key] : editor.keys.filter((k) => k !== q.key) })}>{q.label}{excluded ? '（来自品牌，不保存）' : ''}</Checkbox>
            {selected && (q.type === 'single_choice' || q.type === 'multi_choice' ? <Select aria-label={`模板参数：${q.label}`} style={{ width: '100%' }} value={editor.values[q.key]} mode={q.type === 'multi_choice' ? 'multiple' : undefined} options={q.options} onChange={update} />
              : q.type === 'number' ? <InputNumber aria-label={`模板参数：${q.label}`} value={editor.values[q.key] as number} onChange={update} />
                : <Input.TextArea aria-label={`模板参数：${q.label}`} value={editor.values[q.key] as string} rows={3} onChange={(e) => update(e.target.value)} />)}
          </div>;
        })}
        {error && <Alert type="error" message={error} />}
      </div>}
    </Modal>}
  </section>;
}

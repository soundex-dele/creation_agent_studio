import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Select, Spin } from 'antd';
import { type CopyBody, type Data, type Library, type Preferences, type RentalApi, type RentalRecord, type Resource, type Version, downloadBlob, localTime, rentalError, string, strings, utcTime } from '@/services/rentalGrowth';
import { fields, meta, options, statusLabels, type Field } from './config';

export function FieldInput({ field, value, onChange, library, zone }: { field: Field; value: unknown; onChange: (value: unknown) => void; library: Library; zone: string }) {
  const id = `rental-${field.key}`;
  const choices = field.resource ? library[field.resource].filter(r => field.resource !== 'publications' || r.status === 'published').map(r => ({ value: r.id, label: `${r.title}${r.archived ? '（归档）' : ''}` })) : options(field.options || {});
  const common = { id, 'aria-label': field.label };
  let input;
  if (field.type === 'number') input = <InputNumber {...common} min={0} value={typeof value === 'number' ? value : null} onChange={onChange} />;
  else if (field.type === 'select' || field.type === 'multi' || field.type === 'tags') input = <Select {...common} allowClear showSearch optionFilterProp="label" mode={field.type === 'multi' ? 'multiple' : field.type === 'tags' ? 'tags' : undefined} options={choices} value={field.type === 'select' ? string(value) || undefined : strings(value)} onChange={v => onChange(v ?? null)} tokenSeparators={field.type === 'tags' ? [',', '，'] : undefined} />;
  else if (field.type === 'photos' || field.type === 'conditions' || field.type === 'long') input = <Input.TextArea {...common} rows={field.type === 'long' ? 3 : 5} maxLength={20000} value={string(value)} onChange={e => onChange(e.target.value)} />;
  else if (field.type === 'time') input = <Input {...common} type="datetime-local" required={field.required} value={string(value)} onChange={e => onChange(e.target.value)} />;
  else input = <Input {...common} type={field.type === 'date' ? 'date' : 'text'} maxLength={3000} required={field.required} value={string(value)} onChange={e => onChange(e.target.value)} />;
  return <div className={`rental-field ${['long', 'photos', 'conditions'].includes(field.type || '') ? 'rental-field--wide' : ''}`}><label htmlFor={id}>{field.label}{field.required ? ' *' : ''}</label>{input}{(field.help || field.type === 'time') && <small>{field.help || `时区：${zone}`}</small>}</div>;
}

export interface EditorState { kind: Resource; row?: RentalRecord; initial?: Data; data?: Data }
function editable(data: Data, kind: Resource, zone: string) {
  const output = { ...data };
  fields[kind].forEach(field => {
    const value = data[field.key];
    if (field.type === 'time') output[field.key] = value ? localTime(String(value), zone) : '';
    if (field.type === 'photos') output[field.key] = Array.isArray(value) ? value.map((p: { label: string; note: string }) => `${p.label} | ${p.note || ''}`).join('\n') : '';
    if (field.type === 'conditions') output[field.key] = Object.entries(value as Data || {}).map(([key, state]) => `${key}=${({ yes: '是', no: '否', unknown: '待确认' })[String(state)] || '待确认'}`).join('\n');
  });
  return output;
}

export function RecordEditor({ editor, api, library, preferences, onClose, onSaved }: { editor: EditorState; api: RentalApi; library: Library; preferences: Preferences; onClose: () => void; onSaved: (row: RentalRecord) => void }) {
  const { kind, row } = editor;
  const [title, setTitle] = useState(row?.title || string(editor.initial?.title));
  const [status, setStatus] = useState(row?.status || string(editor.initial?.status) || meta[kind].statuses[0]);
  const [data, setData] = useState<Data>(() => editable({ ...row?.data, ...editor.data }, kind, preferences.timezone));
  const [lead, setLead] = useState(row?.lead_id || string(editor.initial?.lead_id));
  const [version, setVersion] = useState(row?.version_id || string(editor.initial?.version_id));
  const [markRented, setMarkRented] = useState(false);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const saving = useRef(false);
  async function save() {
    if (saving.current) return;
    saving.current = true; setBusy(true); setError('');
    try {
      const payload = { ...data };
      for (const field of fields[kind]) {
        const value = payload[field.key];
        if (field.type === 'time') payload[field.key] = utcTime(string(value), preferences.timezone);
        if (field.type === 'date') payload[field.key] = value || null;
        if (field.type === 'photos') payload[field.key] = string(value).split('\n').filter(line => line.trim()).map(line => { const [label, ...rest] = line.split('|'); return { label: label.trim(), note: rest.join('|').trim() }; });
        if (field.type === 'conditions') {
          const conditions: Record<string, string> = {};
          string(value).split('\n').filter(line => line.trim()).forEach(line => {
            const [key, state] = line.split(/[=＝]/).map(s => s.trim());
            if (!key || !['是', '否', '待确认'].includes(state)) throw new Error('自定义条件格式：名称=是／否／待确认。');
            conditions[key] = ({ 是: 'yes', 否: 'no', 待确认: 'unknown' } as Record<string, string>)[state];
          }); payload[field.key] = conditions;
        }
        if (field.type === 'select' && !field.resource && payload[field.key] == null) delete payload[field.key];
      }
      const values: Data = { title, status, data: payload, ...(kind === 'leads' ? { mark_property_rented: markRented } : {}) };
      if (kind === 'followups' || kind === 'viewings') values.lead_id = lead;
      if (kind === 'publications') values.version_id = version;
      const result = row ? await api.update(kind, row, values) : await api.create(kind, values);
      onSaved(result);
    } catch (e) { setError(rentalError(e)); } finally { saving.current = false; setBusy(false); }
  }
  return <Modal open width={820} rootClassName="rental-modal" title={`${row ? '编辑' : '新增'}${meta[kind].label}`} maskClosable={false} onCancel={onClose} closable={!busy} keyboard={!busy} footer={<><Button onClick={onClose} disabled={busy}>取消</Button><Button type="primary" htmlType="submit" form="rental-record-form" loading={busy}>保存</Button></>}>
    <form id="rental-record-form" onSubmit={e => { e.preventDefault(); void save(); }}>
      {error && <Alert role="alert" type="error" message={error} />}
      <div className="rental-form-grid">
        <div className="rental-field"><label htmlFor="rental-title">{kind === 'leads' ? '客户称呼' : '名称'} *</label><Input id="rental-title" aria-label="名称" autoFocus required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} /></div>
        <div className="rental-field"><label htmlFor="rental-status">状态</label><Select id="rental-status" value={status} options={meta[kind].statuses.map(value => ({ value, label: statusLabels[value] }))} onChange={setStatus} /></div>
        {(kind === 'followups' || kind === 'viewings') && <div className="rental-field rental-field--wide"><label htmlFor="rental-lead">关联客户 *</label><Select id="rental-lead" showSearch optionFilterProp="label" value={lead || undefined} options={library.leads.map(r => ({ value: r.id, label: r.title }))} onChange={setLead} /></div>}
        {kind === 'publications' && <div className="rental-field rental-field--wide"><label htmlFor="rental-version">使用的文案版本 *</label><Select id="rental-version" disabled={row?.status === 'published'} value={version || undefined} options={[...library.contents.filter(r => r.latest_version).map(r => ({ value: r.latest_version!.id, label: `${r.title} · v${r.latest_version!.number}` })), ...(version && !library.contents.some(r => r.latest_version?.id === version) ? [{ value: version, label: `已选历史版本 ${row?.latest_version?.number || ''}` }] : [])]} onChange={setVersion} /><small>复制文案不会标记已发布。请手动填写实际发布时间。</small></div>}
        {fields[kind].map(field => <FieldInput key={field.key} field={field} value={data[field.key]} onChange={value => setData(old => ({ ...old, [field.key]: value }))} library={library} zone={preferences.timezone} />)}
      </div>
      {kind === 'leads' && status === 'won' && <Checkbox checked={markRented} onChange={e => setMarkRented(e.target.checked)}>同时将成交房源标记为已出租</Checkbox>}
      {kind === 'properties' && <p className="rental-muted">可先保存草稿。生成推广内容前需补齐城市、片区、月租、出租方式和户型。</p>}
    </form>
  </Modal>;
}

export function CopyEditor({ row, api, onClose, onSaved, onPublish }: { row: RentalRecord; api: RentalApi; onClose: () => void; onSaved: () => void; onPublish: (version: Version) => void }) {
  const [versions, setVersions] = useState<Version[]>([]); const [selected, setSelected] = useState('');
  const [body, setBody] = useState<CopyBody | null>(null); const [dirty, setDirty] = useState(false);
  const [revision, setRevision] = useState(row.revision); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { let alive = true; api.versions(row.id).then(items => { if (alive) { setVersions(items); setSelected(items[0]?.id || ''); setBody(items[0]?.body || null); } }).catch(e => { if (alive) setError(rentalError(e)); }); return () => { alive = false; }; }, [api, row.id]);
  function photoLabel(ref: string) {
    if (!ref) return '建议补拍';
    const [propertyId, index] = ref.split(':');
    const property = versions.find(v => v.id === selected)?.snapshot.properties?.find(p => p.id === propertyId);
    const photos = property?.data.photos as { label: string }[] | undefined;
    return `${property?.title || '房源'} · ${photos?.[Number(index) - 1]?.label || '照片'} ${index}`;
  }
  function change(value: Partial<CopyBody>) { setBody(old => old ? { ...old, ...value } : old); setDirty(true); setNotice(''); }
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); try { await fn(); } catch (e) { setError(rentalError(e)); } finally { setBusy(false); } }
  return <Modal open width={900} rootClassName="rental-modal" title="编辑文案与排版方案" maskClosable={false} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
    {error && <Alert type="error" message={error} />}{notice && <Alert type="success" message={notice} />}
    {!!row.changes?.length && <Alert type="warning" message={row.changes.join('；')} description="请根据最新房源核对所有文案，保存新版本后再发布。" />}
    {!body ? <Spin /> : <>
      <div className="rental-field"><label htmlFor="rental-copy-version">历史版本</label><Select id="rental-copy-version" disabled={dirty || busy} value={selected} options={versions.map(v => ({ value: v.id, label: `版本 ${v.number}` }))} onChange={id => { setSelected(id); setBody(versions.find(v => v.id === id)!.body); }} /></div>
      <div className="rental-field"><label htmlFor="rental-copy-titles">候选标题（每行一个）</label><Input.TextArea id="rental-copy-titles" rows={3} value={body.titles.join('\n')} onChange={e => change({ titles: e.target.value.split('\n') })} /></div>
      <div className="rental-field"><label htmlFor="rental-copy-cover">封面短句</label><Input.TextArea id="rental-copy-cover" value={body.cover} onChange={e => change({ cover: e.target.value })} /></div>
      <div className="rental-field"><label htmlFor="rental-copy-body">发布正文</label><Input.TextArea id="rental-copy-body" rows={10} value={body.body} onChange={e => change({ body: e.target.value })} /></div>
      <div className="rental-field"><label htmlFor="rental-copy-tags">话题</label><Select id="rental-copy-tags" mode="tags" value={body.tags} onChange={tags => change({ tags })} /></div>
      {(body.script || ['douyin', 'channels'].includes(string(row.data.platform))) && <div className="rental-field"><label htmlFor="rental-copy-script">口播稿</label><Input.TextArea id="rental-copy-script" rows={7} value={body.script} onChange={e => change({ script: e.target.value })} /></div>}
      <h3>实拍图排版建议</h3>
      {body.pages.map((p, i) => <div className="rental-photo-plan" key={i}><strong>第 {i + 1} 页 · {photoLabel(p.photo_ref)}</strong><label htmlFor={`rental-caption-${i}`}>上图文字</label><Input.TextArea id={`rental-caption-${i}`} value={p.caption} onChange={e => change({ pages: body.pages.map((old, n) => n === i ? { ...old, caption: e.target.value } : old) })} /><label htmlFor={`rental-layout-${i}`}>排版与裁切</label><Input.TextArea id={`rental-layout-${i}`} value={p.layout} onChange={e => change({ pages: body.pages.map((old, n) => n === i ? { ...old, layout: e.target.value } : old) })} /></div>)}
      <div className="rental-field"><label htmlFor="rental-copy-shots">镜头／配图建议（每行一条）</label><Input.TextArea id="rental-copy-shots" rows={4} value={body.shots.join('\n')} onChange={e => change({ shots: e.target.value.split('\n').filter(Boolean) })} /></div>
      <div className="rental-field"><label htmlFor="rental-copy-checks">待核实信息（不会复制到正文）</label><Input.TextArea id="rental-copy-checks" value={body.checks.join('\n')} onChange={e => change({ checks: e.target.value.split('\n').filter(Boolean) })} /></div>
      <div className="rental-actions">
        <Button type="primary" loading={busy} onClick={() => void action(async () => { const version = await api.saveVersion({ ...row, revision }, body); setRevision(v => v + 1); setVersions(old => [version, ...old]); setSelected(version.id); setBody(version.body); setDirty(false); setNotice('已保存新版本，历史版本保留。'); onSaved(); })}>保存新版本</Button>
        <Button onClick={() => void action(async () => { await navigator.clipboard.writeText(`${body.titles[0]}\n\n${body.body}\n\n${body.tags.join(' ')}`); setNotice('已复制文案，请自行发布。'); })}>复制文案</Button>
        <Button onClick={() => void action(async () => { await navigator.clipboard.writeText(body.pages.map((p, i) => `第${i + 1}页 ${p.photo_ref || '建议补拍'}\n${p.caption}\n${p.layout}`).join('\n\n') + '\n' + body.shots.join('\n')); setNotice('已复制排版方案。'); })}>复制排版方案</Button>
        {body.script && <Button onClick={() => void action(async () => { await navigator.clipboard.writeText(body.script); setNotice('已复制口播稿。'); })}>复制口播稿</Button>}
        <Button disabled={dirty || busy} onClick={() => void action(async () => downloadBlob(await api.download(selected), `租房文案-v${versions.find(v => v.id === selected)?.number}.md`))}>导出 Markdown</Button>
        <Button disabled={dirty || busy} onClick={() => onPublish(versions.find(v => v.id === selected)!)}>安排发布</Button>
      </div>
      {dirty && <p className="rental-muted">有未保存修改。保存后可以导出或安排发布。</p>}
    </>}
  </Modal>;
}

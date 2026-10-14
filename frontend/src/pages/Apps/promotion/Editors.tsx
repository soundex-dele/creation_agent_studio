import { useEffect, useId, useState, type ReactNode } from 'react';
import { Alert, Button, Input, InputNumber, Modal, Tag } from 'antd';
import { bodyLabels, materialTypes, materialType, sourceIds, platforms, directions, statuses, string, promotionError, type Data, type PromotionRecord, type Resource, type PromotionApi, type CopyBody, type Version, type Destination } from '@/services/projectPromotion';

export type Library = Record<Resource, PromotionRecord[]>;
export function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return <div className="promotion-field"><label htmlFor={id}>{label}</label>{children(id)}</div>;
}
export function Choice({ id, value, options, onChange, empty, disabled }: { id: string; value: string; options: Record<string, string>; onChange: (value: string) => void; empty?: string; disabled?: boolean }) {
  return <select id={id} value={value} onChange={e => onChange(e.target.value)} disabled={disabled}>{empty && <option value="">{empty}</option>}{Object.entries(options).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>;
}
export function MaterialPicker({ label, materials, value, onChange }: { label: string; materials: PromotionRecord[]; value: string[]; onChange: (ids: string[]) => void }) {
  const [search, setSearch] = useState('');
  const visible = materials.filter(row => (!row.archived || value.includes(row.id)) && (!search || row.title.toLowerCase().includes(search.toLowerCase())));
  return <fieldset className="promotion-material-picker"><legend>{label}（已选 {value.length} / 20）</legend>
    <Field label={`${label}搜索`}>{id => <Input id={id} value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索素材名称" />}</Field>
    <p className="promotion-muted">可组合多份素材。仅已确认且未归档的素材可用于策划和确认选题。</p>
    <div className="promotion-material-options">{visible.map(row => <label className="promotion-material-option" key={row.id}><input type="checkbox" checked={value.includes(row.id)} disabled={!value.includes(row.id) && (value.length >= 20 || row.archived || row.status !== 'confirmed')} onChange={e => onChange(e.target.checked ? [...value, row.id] : value.filter(id => id !== row.id))} /><span>{row.title}<small>{materialTypes[materialType(row)]} · {row.archived ? '已归档' : row.status === 'confirmed' ? '已确认' : '待审核'}</small></span></label>)}</div>
    {!visible.length && <p className="promotion-muted">没有可选素材，请先在项目素材库添加并确认。</p>}
  </fieldset>;
}
export function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
const names = { cases: '项目素材', topics: '选题', channels: '渠道任务', feedback: '反馈' };
export const caseFields: Record<string, string> = { summary: '素材摘要', facts: '事实资料', audience: '相关用户', problem: '遇到什么问题', solution: '如何解决', steps: '操作过程', implemented: '已实现能力', evidence: '补充说明／实际产出（可选）', conditions: '使用条件与限制', extensions: '可扩展方向（尚未实现）', development_notes: '开发记录／已有资料原文' };

export function RecordEditor({ kind, row, initial = {}, library, api, onClose, onSaved }: {
  kind: Resource; row?: PromotionRecord; initial?: Data; library: Library; api: PromotionApi; onClose: () => void; onSaved: () => void;
}) {
  const [value, setValue] = useState<Data>(() => ({ title: row?.title || '', status: row?.status || (kind === 'feedback' ? 'recorded' : 'draft'), case_ids: row ? sourceIds(row) : [], topic_id: row?.topic_id, channel_id: row?.channel_id, platform: row?.platform || 'wechat', ...initial }));
  const [data, setData] = useState<Data>(() => row?.data || (kind === 'cases' ? { material_type: 'feature', case_type: 'demo', category: 'general', assets: [] } : kind === 'topics' ? { direction: 'demo' } : kind === 'feedback' ? { observed_on: today() } : {}));
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const update = (key: string, val: unknown) => setData(old => ({ ...old, [key]: val }));
  const field = (key: string, label: string, rows = 3) => <Field key={key} label={label}>{id => <Input.TextArea id={id} rows={rows} maxLength={key === 'development_notes' ? 30000 : ['summary', 'audience'].includes(key) ? 2000 : ['angle', 'thesis'].includes(key) ? 5000 : 10000} value={string(data[key])} onChange={e => update(key, e.target.value)} />}</Field>;
  const assets = (Array.isArray(data.assets) ? data.assets : []) as Data[];
  async function save() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const payload: Data = { title: value.title, status: value.status, data };
      for (const key of kind === 'topics' ? ['case_ids'] : kind === 'channels' ? ['topic_id', 'platform'] : kind === 'feedback' ? ['channel_id'] : []) payload[key] = value[key] || null;
      if (row) await api.update(kind, row, payload); else await api.create(kind, payload);
      onSaved(); onClose();
    } catch (e) { setError(promotionError(e)); } finally { setBusy(false); }
  }
  const availableStatuses = kind === 'channels' ? ['draft', 'ready', 'published', 'paused'] : kind === 'feedback' ? ['recorded'] : ['draft', 'confirmed'];
  return <Modal open title={`${row ? '编辑' : '新增'}${names[kind]}`} rootClassName="promotion-modal" width={760} onCancel={onClose} onOk={() => void save()} okText="保存" confirmLoading={busy}>
    {error && <Alert type="error" role="alert" message={error} />}
    <Field label="名称">{id => <Input id={id} maxLength={200} value={string(value.title)} onChange={e => setValue({ ...value, title: e.target.value })} />}</Field>
    <div className="promotion-form-grid"><Field label="状态">{id => <Choice id={id} value={string(value.status)} options={Object.fromEntries(availableStatuses.map(k => [k, k === 'draft' && kind !== 'channels' ? '待审核草稿' : statuses[k]]))} onChange={status => setValue({ ...value, status })} />}</Field>
      {kind === 'cases' && <><Field label="素材类型">{id => <Choice id={id} value={string(data.material_type) || 'case'} options={materialTypes} onChange={v => update('material_type', v)} />}</Field>{(!data.material_type || data.material_type === 'case') && <Field label="案例类型">{id => <Choice id={id} value={string(data.case_type)} options={{ demo: '演示案例', customer: '真实客户案例（已核实）' }} onChange={v => update('case_type', v)} />}</Field>}</>}
      {kind === 'topics' && <Field label="介绍角度">{id => <Choice id={id} value={string(data.direction)} options={directions} onChange={v => update('direction', v)} />}</Field>}
      {kind === 'channels' && <><Field label="关联选题">{id => <Choice id={id} disabled={!!row} value={string(value.topic_id)} empty="请选择选题" options={Object.fromEntries(library.topics.filter(r => !r.archived || r.id === row?.topic_id).map(r => [r.id, r.title]))} onChange={v => setValue({ ...value, topic_id: v })} />}</Field><Field label="发布渠道">{id => <Choice id={id} disabled={!!row} value={string(value.platform)} options={platforms} onChange={v => setValue({ ...value, platform: v })} />}</Field><Field label="计划日期">{id => <Input id={id} type="date" value={string(data.planned_date)} onChange={e => update('planned_date', e.target.value || null)} />}</Field><Field label="实际发布时间（本地时间）">{id => {
        const dt = data.published_at ? new Date(string(data.published_at)) : null;
        const local = dt && !Number.isNaN(dt.getTime()) ? new Date(dt.getTime() - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 16) : '';
        return <Input id={id} type="datetime-local" value={local} onChange={e => update('published_at', e.target.value ? new Date(e.target.value).toISOString() : null)} />;
      }}</Field><Field label="发布链接">{id => <Input id={id} value={string(data.publication_url)} onChange={e => update('publication_url', e.target.value)} />}</Field></>}
      {kind === 'feedback' && <><Field label="来源">{id => <Choice id={id} disabled={!!row} value={string(value.channel_id)} empty="未知来源／不归因" options={Object.fromEntries(library.channels.filter(r => r.status === 'published').map(r => [r.id, `${platforms[r.platform || '']} · ${r.title}`]))} onChange={v => setValue({ ...value, channel_id: v || null })} />}</Field><Field label="观察日期">{id => <Input id={id} type="date" value={string(data.observed_on)} onChange={e => update('observed_on', e.target.value)} />}</Field>{Object.entries({ views: '累计阅读／播放', interactions: '累计互动', inquiries: '累计私信咨询' }).map(([key, label]) => <Field key={key} label={`${label}（可留空）`}>{id => <InputNumber id={id} min={0} precision={0} value={typeof data[key] === 'number' ? data[key] as number : null} onChange={v => update(key, v)} />}</Field>)}</>}
    </div>
    {kind === 'topics' && <MaterialPicker label="关联素材" materials={library.cases} value={(value.case_ids || []) as string[]} onChange={case_ids => setValue({ ...value, case_ids })} />}
    {kind === 'cases' && <><p className="promotion-muted">素材保存项目事实；面向谁、讲什么观点，在选题中组织。{data.material_type === 'case' || !data.material_type ? '案例确认需填写相关用户、问题、方案、已实现能力。' : '确认需填写素材摘要和事实资料。文档声明与已实现能力请明确区分。'}</p>{Object.entries(caseFields).filter(([key]) => key !== 'evidence' || !row?.source_snapshot?.evidence).filter(([key]) => !['problem', 'solution'].includes(key) || !data.material_type || data.material_type === 'case').map(([key, label]) => field(key, label))}<h3>素材与资料链接</h3><p className="promotion-muted">关联截图、视频、文档或网盘链接，并注明内容。链接不会被自动读取。</p>{assets.map((asset, index) => <div className="promotion-asset" key={index}>
      <Field label={`素材 ${index + 1} 名称`}>{id => <Input id={id} value={string(asset.label)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, label: e.target.value } : a))} />}</Field>
      <Field label="类型">{id => <Choice id={id} value={string(asset.kind)} options={{ image: '截图', video: '演示视频', document: '文档', link: '其他资料' }} onChange={v => update('assets', assets.map((a, i) => i === index ? { ...a, kind: v } : a))} />}</Field>
      <Field label="HTTP(S) 链接">{id => <Input id={id} value={string(asset.url)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, url: e.target.value } : a))} />}</Field>
      <Field label="素材说明">{id => <Input id={id} value={string(asset.note)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, note: e.target.value } : a))} />}</Field>
      <Button onClick={() => update('assets', assets.filter((_, i) => i !== index))}>移除此素材</Button></div>)}<Button disabled={assets.length >= 40} onClick={() => update('assets', [...assets, { label: '', kind: 'link', url: '', note: '' }])}>添加素材链接</Button></>}
    {kind === 'topics' && <>{field('audience', '目标读者')}{field('angle', '切入点与资料要求')}{field('thesis', '核心观点')}{field('outline', '内容结构')}</>}
    {kind === 'feedback' && <><p className="promotion-muted">每次记录当天累计值；未知留空。请只摘录匿名问题，不粘贴客户身份与联系方式。</p>{field('questions', '私信中反复出现的问题')}{field('notes', '观察备注')}</>}
  </Modal>;
}

export function VersionEditor({ row: initial, api, destinations, onClose, onSaved }: { row: PromotionRecord; api: PromotionApi; destinations: Destination[]; onClose: () => void; onSaved: () => void }) {
  const [row, setRow] = useState(initial); const [versions, setVersions] = useState<Version[]>([]); const [selected, setSelected] = useState('');
  const empty: CopyBody = { title: initial.title, body: '', cover: '', pages: '', script: '', materials: '', shots: '', checks: '', formatted_html: '' };
  const [body, setBody] = useState<CopyBody>(empty); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [dirty, setDirty] = useState(false); const [handoff, setHandoff] = useState('');
  useEffect(() => { let alive = true; api.versions(initial.id).then(items => { if (alive) { setVersions(items); if (items[0]) { setSelected(items[0].id); setBody(items[0].body); } } }).catch(e => { if (alive) setError(promotionError(e)); }); return () => { alive = false; }; }, [api, initial.id]);
  async function action(fn: () => Promise<void>) {
    if (busy) return; setBusy(true); setError('');
    try { await fn(); onSaved(); } catch (e) { setError(promotionError(e)); } finally { setBusy(false); }
  }
  async function save() {
    const version = await api.saveVersion(row, body, selected || undefined); setVersions(old => [version, ...old]); setSelected(version.id); setDirty(false); setRow(await api.record('channels', row.id));
  }
  const chosen = versions.find(v => v.id === selected);
  const materials = (chosen?.snapshot.cases || (chosen?.snapshot.case ? [chosen.snapshot.case] : [])) as Data[];
  async function download(format: string) {
    const blob = await api.download(row, selected, format); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `宣传文案-${row.platform}-v${chosen?.number}.${format}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <Modal open title={`${platforms[row.platform || '']} · 文案版本`} rootClassName="promotion-modal" width={880} onCancel={onClose} footer={<><Button onClick={onClose}>关闭</Button><Button type="primary" loading={busy} onClick={() => void action(save)}>保存为新版本</Button></>}>
    {error && <Alert type="error" role="alert" message={error} action={<Button onClick={() => void action(async () => { setRow(await api.record('channels', row.id)); setVersions(await api.versions(row.id)); })}>刷新记录，保留编辑内容</Button>} />}
    <p className="promotion-muted">每次保存新增一个版本。确认后的发布版本独立保留；重新生成不会覆盖。</p>
    <Field label="查看历史版本">{id => <Choice id={id} disabled={dirty} value={selected} empty="尚无版本" options={Object.fromEntries(versions.map(v => [v.id, `版本 ${v.number}${v.id === row.confirmed_version_id ? ' · 已确认' : ''}`]))} onChange={v => { setSelected(v); const item = versions.find(x => x.id === v); if (item) setBody(item.body); }} />}</Field>
    {dirty && <p role="status">有未保存修改，保存为新版本后可切换、确认或交接。</p>}
    <div className="promotion-actions"><Button disabled={!selected || dirty || busy || row.status === 'published'} onClick={() => void action(async () => setRow(await api.confirm(row, selected)))}>确认此版本待发布</Button><Button disabled={busy || !body.body} onClick={() => void action(async () => { await navigator.clipboard.writeText(Object.entries(bodyLabels).filter(([k]) => k !== 'formatted_html' && body[k as keyof CopyBody]).map(([k, label]) => `${label}\n${body[k as keyof CopyBody]}`).join('\n\n')); })}>复制文案与清单</Button><Button disabled={!selected || dirty || busy} onClick={() => void action(() => download('md'))}>下载 Markdown</Button>{body.formatted_html && <Button disabled={!selected || dirty || busy} onClick={() => void action(() => download('html'))}>下载 HTML</Button>}</div>
    {row.confirmed_version_id && <Tag color="green">已有确认版本</Tag>}
    {Object.entries(bodyLabels).map(([key, label]) => <Field key={key} label={label}>{id => <Input.TextArea id={id} rows={key === 'body' ? 12 : key === 'title' ? 1 : 3} value={body[key as keyof CopyBody]} onChange={e => { setBody({ ...body, [key]: e.target.value }); setDirty(true); }} />}</Field>)}
    {chosen && <details><summary>本版本的关联素材</summary>{materials.map((material, index) => <p key={index}>{string(material.title)} · 修订 {string(material.revision)}</p>)}</details>}
    <h3>继续使用已有创作应用</h3><p className="promotion-muted">带入当前已保存版本，核对目标应用表单后生成，再从宣传助手的交接记录回存结果。</p><div className="promotion-actions">{destinations.map(d => <Button key={d.id} disabled={!selected || dirty || busy} onClick={() => void action(async () => { const h = await api.handoff(row, selected, d.id); setHandoff(h.url); })}>{d.name}</Button>)}</div>
    {!destinations.length && <p className="promotion-muted">当前没有可访问的创作应用。可在应用中心安装图文、短视频、公众号写作或排版应用。</p>}
    {handoff && <p><a href={handoff}>打开带稿创作页面</a></p>}
  </Modal>;
}

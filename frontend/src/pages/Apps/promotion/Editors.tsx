import { useId, useState, type ReactNode } from 'react';
import { Alert, Button, Input, Modal } from 'antd';
import { materialTypes, materialType, sourceIds, directions, statuses, string, promotionError, type Data, type PromotionRecord, type Resource, type PromotionApi } from '@/services/projectPromotion';

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
const names = { cases: '项目素材', topics: '选题' };
export const caseFields: Record<string, string> = { summary: '素材摘要', facts: '事实资料', audience: '相关用户', problem: '遇到什么问题', solution: '如何解决', steps: '操作过程', implemented: '已实现能力', evidence: '补充说明／实际产出（可选）', conditions: '使用条件与限制', extensions: '可扩展方向（尚未实现）', development_notes: '开发记录／已有资料原文' };

export function RecordEditor({ kind, row, initial = {}, library, api, onClose, onSaved }: {
  kind: Resource; row?: PromotionRecord; initial?: Data; library: Library; api: PromotionApi; onClose: () => void; onSaved: () => void;
}) {
  const [value, setValue] = useState<Data>(() => ({ title: row?.title || '', status: row?.status || 'draft', case_ids: row ? sourceIds(row) : [], ...initial }));
  const [data, setData] = useState<Data>(() => row?.data || (kind === 'cases' ? { material_type: 'feature', case_type: 'demo', category: 'general', assets: [] } : { direction: 'demo' }));
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const update = (key: string, val: unknown) => setData(old => ({ ...old, [key]: val }));
  const field = (key: string, label: string, rows = 3) => <Field key={key} label={label}>{id => <Input.TextArea id={id} rows={rows} maxLength={key === 'development_notes' ? 30000 : ['summary', 'audience'].includes(key) ? 2000 : ['angle', 'thesis'].includes(key) ? 5000 : 10000} value={string(data[key])} onChange={e => update(key, e.target.value)} />}</Field>;
  const assets = (Array.isArray(data.assets) ? data.assets : []) as Data[];
  async function save() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const payload: Data = { title: value.title, status: value.status, data };
      if (kind === 'topics') payload.case_ids = value.case_ids;
      if (row) await api.update(kind, row, payload); else await api.create(kind, payload);
      onSaved(); onClose();
    } catch (e) { setError(promotionError(e)); } finally { setBusy(false); }
  }
  const availableStatuses = ['draft', 'confirmed'];
  return <Modal open title={`${row ? '编辑' : '新增'}${names[kind]}`} rootClassName="promotion-modal" width={760} onCancel={onClose} onOk={() => void save()} okText="保存" confirmLoading={busy}>
    {error && <Alert type="error" role="alert" message={error} />}
    <Field label="名称">{id => <Input id={id} maxLength={200} value={string(value.title)} onChange={e => setValue({ ...value, title: e.target.value })} />}</Field>
    <div className="promotion-form-grid"><Field label="状态">{id => <Choice id={id} value={string(value.status)} options={Object.fromEntries(availableStatuses.map(k => [k, k === 'draft' ? '待审核草稿' : statuses[k]]))} onChange={status => setValue({ ...value, status })} />}</Field>
      {kind === 'cases' && <><Field label="素材类型">{id => <Choice id={id} value={string(data.material_type) || 'case'} options={materialTypes} onChange={v => update('material_type', v)} />}</Field>{(!data.material_type || data.material_type === 'case') && <Field label="案例类型">{id => <Choice id={id} value={string(data.case_type)} options={{ demo: '演示案例', customer: '真实客户案例（已核实）' }} onChange={v => update('case_type', v)} />}</Field>}</>}
      {kind === 'topics' && <Field label="介绍角度">{id => <Choice id={id} value={string(data.direction)} options={directions} onChange={v => update('direction', v)} />}</Field>}
    </div>
    {kind === 'topics' && <MaterialPicker label="关联素材" materials={library.cases} value={(value.case_ids || []) as string[]} onChange={case_ids => setValue({ ...value, case_ids })} />}
    {kind === 'cases' && <><p className="promotion-muted">素材保存项目事实；面向谁、讲什么观点，在选题中组织。{data.material_type === 'case' || !data.material_type ? '案例确认需填写相关用户、问题、方案、已实现能力。' : '确认需填写素材摘要和事实资料。文档声明与已实现能力请明确区分。'}</p>{Object.entries(caseFields).filter(([key]) => key !== 'evidence' || !row?.source_snapshot?.evidence).filter(([key]) => !['problem', 'solution'].includes(key) || !data.material_type || data.material_type === 'case').map(([key, label]) => field(key, label))}<h3>素材与资料链接</h3><p className="promotion-muted">关联截图、视频、文档或网盘链接，并注明内容。链接不会被自动读取。</p>{assets.map((asset, index) => <div className="promotion-asset" key={index}>
      <Field label={`素材 ${index + 1} 名称`}>{id => <Input id={id} value={string(asset.label)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, label: e.target.value } : a))} />}</Field>
      <Field label="类型">{id => <Choice id={id} value={string(asset.kind)} options={{ image: '截图', video: '演示视频', document: '文档', link: '其他资料' }} onChange={v => update('assets', assets.map((a, i) => i === index ? { ...a, kind: v } : a))} />}</Field>
      <Field label="HTTP(S) 链接">{id => <Input id={id} value={string(asset.url)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, url: e.target.value } : a))} />}</Field>
      <Field label="素材说明">{id => <Input id={id} value={string(asset.note)} onChange={e => update('assets', assets.map((a, i) => i === index ? { ...a, note: e.target.value } : a))} />}</Field>
      <Button onClick={() => update('assets', assets.filter((_, i) => i !== index))}>移除此素材</Button></div>)}<Button disabled={assets.length >= 40} onClick={() => update('assets', [...assets, { label: '', kind: 'link', url: '', note: '' }])}>添加素材链接</Button></>}
    {kind === 'topics' && <>{field('audience', '目标读者')}{field('angle', '切入点与资料要求')}{field('thesis', '核心观点')}{field('outline', '内容结构')}</>}
  </Modal>;
}

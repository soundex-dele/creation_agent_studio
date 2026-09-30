import { useEffect, useState, type ReactNode } from 'react';
import { Alert, Button, Empty, Input, Modal, Pagination, Select, Spin, Switch } from 'antd';
import { documentError } from '@/services/documents';
import type { ResearchClient, Page, RecordBase } from '@/services/douyinResearch';

export function useRows<T>(client: ResearchClient, resource: string, filters: Record<string, unknown> = {}) {
  const [data, setData] = useState<Page<T>>({ count: 0, results: [] });
  const [page, setPage] = useState(1); const [tick, setTick] = useState(0); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const filterKey = JSON.stringify(filters);
  useEffect(() => { setPage(1); }, [filterKey, resource]);
  useEffect(() => {
    let alive = true; setLoading(true); setError('');
    void client.list<T>(resource, { ...JSON.parse(filterKey), page }).then(value => { if (alive) setData(value); }).catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, resource, page, tick, filterKey]);
  return { ...data, page, setPage, loading, error, reload: () => setTick(v => v + 1) };
}

export async function allRows<T>(client: ResearchClient, resource: string): Promise<T[]> {
  const rows: T[] = []; let page = 1;
  for (;;) {
    const data = await client.list<T>(resource, { page });
    rows.push(...data.results);
    if (!data.results.length || rows.length >= data.count) return rows;
    page += 1;
  }
}

export function Status({ loading, error, empty }: { loading: boolean; error: string; empty: boolean }) {
  return error ? <Alert type="error" showIcon message={error} /> : loading ? <div role="status"><Spin /> 正在加载…</div> : empty ? <Empty description="暂无数据，添加资料或开始采集后查看。" /> : null;
}

export function Pager({ rows }: { rows: { page: number; count: number; setPage: (page: number) => void } }) {
  return <Pagination current={rows.page} total={rows.count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={rows.setPage} />;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="douyin-research-field"><span>{label}</span>{children}</label>;
}

export interface EditorField { key: string; label: string; kind?: 'text' | 'long' | 'tags' | 'switch' | 'select' | 'multi' | 'number'; options?: { value: string | number; label: string }[]; min?: number; max?: number }
export function RecordEditor({ title, fields, initial, onClose, onSave }: { title: string; fields: EditorField[]; initial: object; onClose: () => void; onSave: (values: Record<string, unknown>) => Promise<unknown> }) {
  const [values, setValues] = useState<Record<string, unknown>>({ ...initial }); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  return <Modal className="douyin-modal" title={title} open onCancel={() => !busy && onClose()} confirmLoading={busy} okText="保存" onOk={() => {
    setBusy(true); setError(''); void onSave(values).then(onClose).catch(e => setError(documentError(e))).finally(() => setBusy(false));
  }}><div className="douyin-form">{fields.map(field => <Field key={field.key} label={field.label}>
    {field.kind === 'switch' ? <Switch aria-label={field.label} checked={Boolean(values[field.key])} onChange={value => setValues({ ...values, [field.key]: value })} />
      : field.kind === 'select' || field.kind === 'multi' ? <Select aria-label={field.label} allowClear mode={field.kind === 'multi' ? 'multiple' : undefined} value={values[field.key] as string | string[] | number | undefined} options={field.options} onChange={value => setValues({ ...values, [field.key]: value ?? (field.kind === 'multi' ? [] : null) })} />
      : field.kind === 'long' ? <Input.TextArea aria-label={field.label} rows={4} maxLength={20000} value={String(values[field.key] || '')} onChange={e => setValues({ ...values, [field.key]: e.target.value })} />
      : <Input aria-label={field.label} type={field.kind === 'number' ? 'number' : 'text'} min={field.min} max={field.max} maxLength={field.kind === 'tags' ? 800 : 300} value={field.kind === 'tags' ? (values[field.key] as string[] || []).join(', ') : String(values[field.key] ?? '')} onChange={e => setValues({ ...values, [field.key]: field.kind === 'tags' ? e.target.value.split(/[,，]/).map(v => v.trim()).filter(Boolean) : field.kind === 'number' ? Number(e.target.value) : e.target.value })} />}
  </Field>)}{error && <Alert type="error" message={error} />}</div></Modal>;
}

export function DeleteRecord({ client, resource, record, done }: { client: ResearchClient; resource: string; record: RecordBase; done: () => void }) {
  const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  return <><Button danger type="text" onClick={() => setOpen(true)}>删除</Button><Modal title="删除这条记录？" open={open} confirmLoading={busy} okText="删除" okButtonProps={{ danger: true }} onCancel={() => !busy && setOpen(false)} onOk={() => {
    setBusy(true); void client.remove(resource, record.id).then(() => { setOpen(false); done(); }).catch(e => setError(documentError(e))).finally(() => setBusy(false));
  }}><p>删除后此记录将不再显示。</p>{error && <Alert type="error" message={error} />}</Modal></>;
}

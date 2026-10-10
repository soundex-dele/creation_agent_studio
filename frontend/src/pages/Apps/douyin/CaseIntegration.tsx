import { useEffect, useState } from 'react';
import { Alert, Button, Input, Modal, Pagination, Select, Spin, Tag } from 'antd';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';
import { casesApi, type CasePreview, type CaseReference } from '@/services/cases';
import type { DouyinClient } from '@/services/douyinBenchmark';
import type { TemplateCategory, TemplateSummary } from '@/types/template';
import { documentError } from '@/services/documents';
import './CaseIntegration.css';

export function SaveCaseButton({ client, workId, taskId, caseId }: { client: Pick<DouyinClient, 'casePreview' | 'saveCase'>; workId: string; taskId?: string; caseId?: number | null }) {
  const navigate = useApplicationNavigate();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<CasePreview | null>(null);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [saved, setSaved] = useState<number | null>(caseId || null);
  useEffect(() => { setSaved(caseId || null); }, [caseId, workId]);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true); setError(''); setPreview(null);
    void Promise.all([client.casePreview(workId, taskId), casesApi.categories()]).then(([value, rows]) => {
      if (alive) { setPreview(value); setCategories(rows); setSaved(value.case_id); }
    }).catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, workId, taskId, open, reload]);
  async function save() {
    if (!preview) return;
    setBusy(true); setError('');
    try {
      const result = await client.saveCase(workId, {
        action: preview.case_id ? 'update' : 'save',
        ...(preview.task_id ? { task_id: preview.task_id } : {}),
        ...(!preview.case_id ? { title: preview.title, summary: preview.summary, tags: preview.tags,
          ...(preview.category ? { category: preview.category } : {}) } : {}),
      });
      setSaved(result.case_id); setOpen(false);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <span className="case-inline-actions">
    <Button onClick={() => setOpen(true)}>{saved ? '更新来源内容' : '存入案例库'}</Button>
    {saved && <Button onClick={() => navigate(`/apps/case-library/${saved}`)}>查看案例</Button>}
    <Modal title={preview?.case_id ? '更新案例来源内容' : '存入案例库'} open={open} onCancel={() => !busy && setOpen(false)}
      confirmLoading={busy} okText={preview?.case_id ? '更新来源内容' : '保存案例'}
      okButtonProps={{ disabled: loading || !preview || !preview.title.trim() }} onOk={() => void save()}>
      <div className="case-integration-form">
        <Alert type="info" message={preview?.case_id ? '已有案例。更新会替换原文与拆解，保留你填写的标题、分类、摘要和标签。' : '保存为个人案例，仅本人可见；不会自动发布或启动 AI 任务。'} />
        {error && <Alert type="error" message={error} action={<Button onClick={() => setReload(v => v + 1)}>重新加载</Button>} />}
        {loading && <Spin />}
        {preview && <>
          {preview.case_id ? <Button onClick={() => navigate(`/apps/case-library/${preview.case_id}`)}>查看已有案例</Button> : <>
            <label className="case-integration-field">案例标题<Input aria-label="案例标题" maxLength={200} value={preview.title} onChange={e => setPreview({ ...preview, title: e.target.value })} /></label>
            <label className="case-integration-field">案例分类<Select aria-label="案例分类" allowClear placeholder="默认：抖音作品案例" value={preview.category || undefined} options={categories.map(c => ({ value: c.id, label: c.name }))} onChange={value => setPreview({ ...preview, category: value || null })} /></label>
            <label className="case-integration-field">案例摘要<Input.TextArea aria-label="案例摘要" maxLength={10000} rows={3} value={preview.summary} onChange={e => setPreview({ ...preview, summary: e.target.value })} /></label>
            <label className="case-integration-field">案例标签<Select aria-label="案例标签" mode="tags" value={preview.tags} onChange={tags => setPreview({ ...preview, tags: tags.slice(0, 20).map(t => t.slice(0, 40)) })} /></label>
          </>}
          <details><summary>将保存的正文与拆解（{preview.source_content.length} 字）</summary>
            <div className="case-source-preview"><p>{preview.source_content || '暂无正文，仅保存作品来源信息。'}</p>
              {preview.analysis_sections.map((s, i) => <article key={i}><strong>{s.title}</strong><p>{s.content}</p>{s.evidence_quote && <blockquote>{s.evidence_quote}</blockquote>}</article>)}
              {!preview.analysis_sections.length && <p>暂无拆解，可在完成拆解后更新。</p>}
            </div>
          </details>
        </>}
      </div>
    </Modal>
  </span>;
}

export function CasePicker({ selected, onChange }: { selected: CaseReference[]; onChange: (rows: CaseReference[]) => void }) {
  const [query, setQuery] = useState(''); const [page, setPage] = useState(1);
  const [rows, setRows] = useState<TemplateSummary[]>([]); const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [retry, setRetry] = useState(0);
  useEffect(() => {
    let alive = true; setLoading(true);
    const timer = window.setTimeout(() => {
      void casesApi.list({ search: query, page, usable: true }).then(data => { if (alive) { setRows(data.results); setCount(data.count); setError(''); } })
        .catch(e => { if (alive) { setRows([]); setError(documentError(e)); } }).finally(() => { if (alive) setLoading(false); });
    }, 250);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [query, page, retry]);
  return <div className="case-integration-form">
    <label className="case-integration-field">参考案例（最多 3 个）<Input.Search aria-label="搜索参考案例" placeholder="搜索案例标题、作者或平台" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></label>
    <div className="case-inline-actions">{selected.map(row => <Tag key={row.id} closable onClose={() => onChange(selected.filter(c => c.id !== row.id))}>{row.title}</Tag>)}</div>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRetry(v => v + 1)}>重试</Button>} />}
    {loading ? <Spin /> : <div className="case-picker-results">{rows.map(row => <div key={row.id} className="case-picker-row"><span>{row.title}<small>{row.source_platform} · {row.source_author || '作者未注明'}</small></span><Button disabled={selected.length >= 3 || selected.some(c => c.id === row.id)} onClick={() => onChange([...selected, { id: row.id, title: row.title }])}>{selected.some(c => c.id === row.id) ? '已选择' : '选择案例'}</Button></div>)}{!rows.length && !error && <p>暂无匹配案例。</p>}</div>}
    <Pagination size="small" current={page} total={count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
  </div>;
}

export function CaseReferences({ cases }: { cases?: CaseReference[] }) {
  const navigate = useApplicationNavigate();
  if (!cases?.length) return null;
  return <div className="case-integration-form"><p>本次参考案例（使用任务创建时的内容快照）：</p><div className="case-inline-actions">{cases.map(row => <Button key={row.id} onClick={() => navigate(`/apps/case-library/${row.id}`)}>{row.title}</Button>)}</div></div>;
}

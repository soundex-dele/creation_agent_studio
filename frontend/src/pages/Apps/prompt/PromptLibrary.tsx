import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, Modal, Pagination, Select, Spin, Tag } from 'antd';
import { Copy, Heart, Pencil, Trash2 } from 'lucide-react';
import { promptError, scenes, type PromptClient, type SessionSummary } from '@/services/promptMaster';

export function PromptLibrary({ client, open }: { client: PromptClient; open: (id: string) => void }) {
  const [search, setSearch] = useState(''); const [scene, setScene] = useState(''); const [favorite, setFavorite] = useState(false);
  const [page, setPage] = useState(1); const [count, setCount] = useState(0); const [rows, setRows] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0);
  const [rename, setRename] = useState<SessionSummary | null>(null); const [title, setTitle] = useState('');
  const [remove, setRemove] = useState<SessionSummary | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    const timer = setTimeout(() => {
      void client.list(search, scene, favorite, page).then((result) => { if (active) { setRows(result.results); setCount(result.count); setError(''); } })
        .catch((e) => { if (active) setError(promptError(e)); }).finally(() => { if (active) setLoading(false); });
    }, 200);
    return () => { active = false; clearTimeout(timer); };
  }, [client, search, scene, favorite, page, refresh]);
  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); setRefresh((v) => v + 1); } catch (e) { setError(promptError(e)); }
    finally { setBusy(false); }
  };
  return <section className="pm-library" aria-label="我的提示词"><div className="pm-section-heading"><div><h2>积累每一次好想法</h2><p className="pm-muted">需求、问答和每个修改版本，仅自己可见。</p></div><Tag>{count} 个会话</Tag></div>
    <div className="pm-library-filters"><Input.Search aria-label="搜索标题" placeholder="搜索提示词标题" value={search} allowClear onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
      <Select aria-label="筛选场景" value={scene} options={[{ value: '', label: '全部场景' }, ...Object.entries(scenes).filter(([key]) => key !== 'auto').map(([value, label]) => ({ value, label }))]} onChange={(value) => { setScene(value); setPage(1); }} />
      <Checkbox checked={favorite} onChange={(e) => { setFavorite(e.target.checked); setPage(1); }}>只看收藏</Checkbox></div>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRefresh((v) => v + 1)}>刷新列表</Button>} />}
    {loading ? <div className="pm-loading" role="status"><Spin /><p>正在查找提示词…</p></div> : rows.length ? <div className="pm-history-grid">{rows.map((row) => <article className="pm-history-card" key={row.id}>
      <div className="pm-section-heading"><Tag>{scenes[row.scene === 'auto' ? row.detected_scene : row.scene]}</Tag><span className="pm-muted">{row.mode === 'optimize' ? '优化' : '生成'}</span></div>
      <button className="pm-history-open" onClick={() => open(row.id)}><h3>{row.title}</h3><span>打开需求与结果 →</span></button>
      <p className="pm-muted">{new Date(row.updated_at).toLocaleString('zh-CN')}</p>
      <div className="pm-actions"><Button disabled={busy} aria-label={row.favorite ? '取消收藏' : '收藏提示词'} icon={<Heart size={16} fill={row.favorite ? 'currentColor' : 'none'} aria-hidden="true" />} onClick={() => void run(() => client.update(row.id, row.revision, { favorite: !row.favorite }))} />
        <Button disabled={busy} icon={<Pencil size={15} aria-hidden="true" />} onClick={() => { setRename(row); setTitle(row.title); }}>改名</Button>
        <Button disabled={busy} icon={<Copy size={15} aria-hidden="true" />} onClick={() => void run(async () => { const copied = await client.copy(row.id); open(copied.id); })}>复制新任务</Button>
        <Button danger disabled={busy} aria-label={`删除 ${row.title}`} icon={<Trash2 size={15} aria-hidden="true" />} onClick={() => setRemove(row)} /></div>
    </article>)}</div> : <Empty description={search || scene || favorite ? '没有匹配的提示词，试试其他筛选条件。' : '还没有提示词，从一个想法开始吧。'} />}
    <Pagination current={page} pageSize={20} total={count} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
    <Modal title="重命名提示词" open={!!rename} onCancel={() => !busy && setRename(null)} confirmLoading={busy} okText="保存" cancelText="取消" okButtonProps={{ disabled: !title.trim() }}
      onOk={() => void run(async () => { if (rename) { await client.update(rename.id, rename.revision, { title: title.trim() }); setRename(null); } })}>
      <label htmlFor="pm-rename">标题</label><Input id="pm-rename" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />{error && <Alert type="error" message={error} />}</Modal>
    <Modal title="删除这个会话？" open={!!remove} confirmLoading={busy} okText="删除" cancelText="保留" okButtonProps={{ danger: true }} onCancel={() => !busy && setRemove(null)}
      onOk={() => void run(async () => { if (remove) { await client.remove(remove.id, remove.revision); setRemove(null); if (rows.length === 1 && page > 1) setPage(page - 1); } })}>
      <p>「{remove?.title}」及其问答、结果将从历史列表移除。进行中的任务会取消。</p>{error && <Alert type="error" message={error} />}</Modal>
  </section>;
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Button, Checkbox, Collapse, Drawer, Empty, Grid, Input, Modal, Pagination, Popconfirm, Progress, Select, Space, Spin, Tabs, Tag, message } from 'antd';
import { Download, FileText, Search, Upload } from 'lucide-react';
import { documentError } from '@/services/documents';
import { citationLocation, claimLabels, isResearchActive, researchKinds, saveResearchBlob,
  type researchApi, type ResearchSource, type ResearchResult, type ResearchProject, type ResearchKind, type ResearchCitation, type ResearchIntegrations } from '@/services/researchAssistant';
import { ImportPicker } from './ImportPicker';

type Client = ReturnType<typeof researchApi>;
type UploadItem = { id: string; file: File; progress: number; status: string; error?: string };
const statusLabels: Record<string, string> = { queued: '排队中', running: '生成中', cancelling: '正在取消', cancelled: '已取消', failed: '失败', succeeded: '已完成', pending: '待解析', indexing: '解析中', ready: '已就绪' };

export function ResearchWorkspace({ client, projectId, resultId, citationId, navigate, onChange }: {
  client: Client; projectId: string; resultId: string | null; citationId: string | null;
  navigate: (project: string | null, result?: string | null, citation?: string | null) => void; onChange: () => void;
}) {
  const [project, setProject] = useState<ResearchProject | null>(null);
  const screens = Grid.useBreakpoint();
  const [title, setTitle] = useState(''); const [objective, setObjective] = useState('');
  const [sources, setSources] = useState<ResearchSource[]>([]); const [selected, setSelected] = useState<string[]>([]);
  const [history, setHistory] = useState<ResearchResult[]>([]); const [historyPage, setHistoryPage] = useState(1); const [historyCount, setHistoryCount] = useState(0);
  const [result, setResult] = useState<ResearchResult | null>(null); const [resultLoading, setResultLoading] = useState(false);
  const [kind, setKind] = useState<ResearchKind>('report'); const [instruction, setInstruction] = useState('');
  const [integrations, setIntegrations] = useState<ResearchIntegrations | null>(null);
  const [citation, setCitation] = useState<ResearchCitation | null>(null); const [citationError, setCitationError] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false); const [articleTitle, setArticleTitle] = useState(''); const [article, setArticle] = useState('');
  const [importOpen, setImportOpen] = useState(false); const [exportOpen, setExportOpen] = useState(false); const [exportApp, setExportApp] = useState<number>();
  const [uploads, setUploads] = useState<UploadItem[]>([]); const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null); const seenReady = useRef(new Set<string>()); const mounted = useRef(true);
  const sourceRequest = useRef(0); const historyRequest = useRef(0);
  const generationKey = useRef<{ hash: string; key: string }>(); const exportKey = useRef<{ hash: string; key: string }>();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const refreshSources = useCallback(async () => {
    const sequence = ++sourceRequest.current;
    const rows = await client.sources(projectId); if (!mounted.current || sequence !== sourceRequest.current) return;
    setSources(rows);
    const ready = rows.filter((s) => s.status === 'ready').map((s) => s.id);
    const added = ready.filter((id) => !seenReady.current.has(id));
    setSelected((old) => [...old.filter((id) => ready.includes(id)), ...added.filter((id) => !old.includes(id))]);
    ready.forEach((id) => seenReady.current.add(id));
  }, [client, projectId]);
  const refreshHistory = useCallback(async () => {
    const sequence = ++historyRequest.current;
    const data = await client.results(projectId, historyPage); if (!mounted.current || sequence !== historyRequest.current) return;
    setHistory(data.results); setHistoryCount(data.count);
  }, [client, projectId, historyPage]);
  useEffect(() => {
    let active = true;
    void Promise.all([client.project(projectId), client.integrations()]).then(([p, i]) => {
      if (active) { setProject(p); setTitle(p.title); setObjective(p.objective); setIntegrations(i); }
    }).catch((e) => { if (active) setError(documentError(e)); });
    return () => { active = false; };
  }, [client, projectId]);
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await Promise.all([refreshSources(), refreshHistory()]); }
      catch (e) { if (active) setError(documentError(e)); }
      finally { if (active) timer = setTimeout(() => void poll(), 4000); }
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [refreshSources, refreshHistory]);
  useEffect(() => {
    setResult(null); if (!resultId) return;
    let active = true; let timer: ReturnType<typeof setTimeout>; setResultLoading(true);
    const poll = async () => {
      try { const row = await client.result(projectId, resultId); if (!active) return; setResult(row); if (isResearchActive(row.status)) timer = setTimeout(() => void poll(), 2500); }
      catch (e) { if (active) setError(documentError(e)); }
      finally { if (active) setResultLoading(false); }
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [client, projectId, resultId]);
  useEffect(() => {
    setCitation(null); setCitationError(''); if (!citationId || !resultId) return;
    let active = true;
    void client.citation(projectId, resultId, citationId).then((row) => { if (active) setCitation(row); }).catch((e) => { if (active) setCitationError(documentError(e)); });
    return () => { active = false; };
  }, [client, projectId, resultId, citationId]);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { if (mounted.current) setError(documentError(e)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const save = async () => { const p = await client.save(projectId, { title, objective }); if (mounted.current) { setProject(p); onChange(); } };
  const generate = (retry?: ResearchResult) => action(async () => {
    await save();
    const body = { source_ids: retry?.source_ids || selected, kind: retry?.kind || kind, instruction: retry ? retry.instruction : instruction };
    const hash = JSON.stringify({ ...body, objective });
    if (!generationKey.current || generationKey.current.hash !== hash) generationKey.current = { hash, key: crypto.randomUUID() };
    const row = await client.generate(projectId, body, generationKey.current.key);
    generationKey.current = undefined;
    if (mounted.current) { navigate(projectId, row.id); setHistoryPage(1); await refreshHistory(); }
  });
  const uploadFiles = async (items: UploadItem[]) => {
    setUploading(true);
    for (const item of items) {
      if (!mounted.current) break;
      const update = (values: Partial<UploadItem>) => { if (mounted.current) setUploads((old) => old.map((row) => row.id === item.id ? { ...row, ...values } : row)); };
      update({ status: 'uploading', error: undefined });
      try {
        const body = new FormData(); body.append('file', item.file);
        const row = await client.addSource(projectId, body, (progress) => update({ progress }));
        if (row.reused && mounted.current) void message.info(`${item.file.name} 已存在，已复用资料。`);
        update({ progress: 100, status: row.reused ? 'reused' : 'done' }); await refreshSources();
      } catch (e) { update({ status: 'failed', error: documentError(e) }); }
    }
    if (mounted.current) setUploading(false);
  };
  const citations = useMemo(() => new Map(result?.output?.citations.map((c) => [c.id, c]) || []), [result]);
  const sourcePanel = <section className="research-sources" aria-label="研究资料">
    <header><h2>研究资料 <small>{sources.length}/{integrations?.limits.max_sources || 20}</small></h2><Tag>仅自己可见</Tag></header>
    <input ref={inputRef} type="file" hidden multiple accept=".pdf,.docx,.txt,.md,.markdown" onChange={(e) => {
      const files = Array.from(e.target.files || []); e.target.value = '';
      const items = files.map((file) => ({ id: crypto.randomUUID(), file, progress: 0, status: 'pending' }));
      setUploads((old) => [...old, ...items]); void uploadFiles(items);
    }} />
    <Button block type="primary" icon={<Upload size={16} aria-hidden="true" />} disabled={uploading} onClick={() => inputRef.current?.click()}>上传多份资料</Button>
    <p className="research-hint">文字 PDF、DOCX、TXT、Markdown · 单文件 {Math.round((integrations?.limits.max_file_bytes || 52428800) / 1048576)} MiB</p>
    <Space wrap><Button disabled={busy} onClick={() => setPasteOpen(true)}>粘贴文章</Button><Button disabled={!integrations?.applications.length || busy} onClick={() => setImportOpen(true)}>从文档／网盘导入</Button></Space>
    {integrations && !integrations.applications.length && <p className="research-hint">暂无可访问的在线文档或网盘应用。</p>}
    <p className="research-hint">勾选本次研究资料。未就绪资料不参与生成。</p>
    {uploads.some((u) => u.status !== 'done' && u.status !== 'reused') && <ul className="research-upload-list" aria-label="上传队列">{uploads.filter((u) => !['done', 'reused'].includes(u.status)).map((u) => <li key={u.id}>
      <strong>{u.file.name}</strong><Progress percent={u.progress} size="small" status={u.status === 'failed' ? 'exception' : 'active'} />
      {u.status === 'failed' && <><p>{u.error}</p><Button size="small" disabled={uploading} onClick={() => void uploadFiles([u])}>重试上传</Button></>}
    </li>)}</ul>}
    {!sources.length ? <Empty description="添加资料，开始有依据的研究" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <ul className="research-source-list">{sources.map((s) => <li key={s.id}>
      <Checkbox checked={selected.includes(s.id)} disabled={s.status !== 'ready'} onChange={(e) => setSelected((old) => e.target.checked ? [...old, s.id] : old.filter((id) => id !== s.id))}>{s.title}</Checkbox>
      <div className="research-source-meta"><Tag color={s.status === 'failed' ? 'error' : s.status === 'ready' ? 'success' : 'processing'}>{statusLabels[s.status]}</Tag><small>{s.origin.type === 'document' ? `在线文档 v${s.origin.version}` : s.origin.type === 'drive' ? '网盘快照' : '上传资料'}</small></div>
      {['pending', 'indexing'].includes(s.status) && <Progress size="small" percent={s.metadata.index_progress || 0} />}
      {s.error && <p className="research-source-error">{s.error_code === 'no_extractable_text' ? '未找到文字；扫描件请先 OCR 后上传。' : s.error}</p>}
      <Space size={0}><Button size="small" type="text" disabled={busy} onClick={() => void action(async () => saveResearchBlob(await client.original(projectId, s.id), s.filename))}>原文件</Button>
        {s.status === 'failed' && <Button size="small" disabled={busy} onClick={() => void action(async () => { await client.retrySource(projectId, s.id); await refreshSources(); })}>重试解析</Button>}
        <Popconfirm title="移出本次研究？" description="历史成果与引用仍会保留。" onConfirm={() => action(async () => { await client.removeSource(projectId, s.id); await refreshSources(); })}><Button type="text" size="small" disabled={busy}>移出</Button></Popconfirm>
      </Space>
    </li>)}</ul>}
  </section>;
  const resultPanel = <section className="research-results" aria-label="研究成果">
    <div className="research-project-form"><label htmlFor="research-title">项目名称</label><Input id="research-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      <label htmlFor="research-objective">研究目标</label><Input.TextArea id="research-objective" value={objective} rows={3} maxLength={8000} placeholder="例如：比较三份报告对行业增长的判断，整理支持和反对的依据。" onChange={(e) => setObjective(e.target.value)} />
      <Space wrap><Button disabled={busy || !title.trim()} onClick={() => void action(save)}>保存项目</Button><Popconfirm title="删除研究项目及全部原始资料？" description="历史出处链接将不可用，已导出的成果不受影响。" onConfirm={() => action(async () => { await client.remove(projectId); onChange(); navigate(null); })}><Button danger disabled={busy}>删除项目</Button></Popconfirm></Space>
    </div>
    <div className="research-generation"><label htmlFor="research-kind">成果类型</label><Select id="research-kind" value={kind} onChange={setKind} options={Object.entries(researchKinds).map(([value, label]) => ({ value, label }))} />
      <label htmlFor="research-instruction">补充关注点</label><Input.TextArea id="research-instruction" value={instruction} rows={2} maxLength={8000} placeholder="可选：重点关注的数据、观点或写作方向" onChange={(e) => setInstruction(e.target.value)} />
      <Button type="primary" icon={<Search size={16} aria-hidden="true" />} loading={busy} disabled={!selected.length || !title.trim() || !objective.trim()} onClick={() => void generate()}>基于 {selected.length} 份资料生成</Button>
    </div>
    <section className="research-history" aria-label="历史成果"><h2>历史成果</h2><div className="research-history-items">{history.map((r) => <Button key={r.id} type={resultId === r.id ? 'primary' : 'default'} onClick={() => navigate(projectId, r.id)}>{researchKinds[r.kind]} · {statusLabels[r.status] || r.status}<small>{new Date(r.created_at).toLocaleString('zh-CN')}</small></Button>)}</div>
      <Pagination size="small" current={historyPage} total={historyCount} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setHistoryPage} />
    </section>
    {resultLoading ? <Spin /> : !result ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择成果类型开始研究，或打开历史成果" /> : <article className="research-output">
      <header><h2>{result.output?.title || researchKinds[result.kind]}</h2><Tag>{statusLabels[result.status] || result.status}</Tag></header>
      <p className="research-hint">本次目标：{result.objective}</p>
      {isResearchActive(result.status) && <div role="status"><Spin size="small" /> {result.progress?.stage || '等待研究任务开始'} {result.progress ? `${result.progress.current}/${result.progress.total}` : ''}<Button disabled={busy || result.status === 'cancelling'} onClick={() => void action(async () => { await client.cancel(projectId, result.id); setResult(await client.result(projectId, result.id)); })}>取消生成</Button></div>}
      {['failed', 'cancelled'].includes(result.status) && <Alert type={result.status === 'failed' ? 'error' : 'info'} message={result.error || '任务已取消'} action={<Button disabled={busy} onClick={() => void generate(result)}>重新生成</Button>} />}
      {result.output && <>
        <Space wrap className="research-output-actions"><Button disabled={busy} onClick={() => void action(async () => { const blob = await client.download(projectId, result.id); await navigator.clipboard.writeText(await blob.text()); void message.success('已复制含出处的 Markdown'); })}>复制</Button>
          <Button icon={<Download size={15} aria-hidden="true" />} disabled={busy} onClick={() => void action(async () => saveResearchBlob(await client.download(projectId, result.id), `${result.output!.title}.md`))}>下载 Markdown</Button>
          <Button disabled={!integrations?.applications.length || busy} onClick={() => { setExportApp(integrations?.applications[0]?.id); setExportOpen(true); }}>保存到文档／网盘</Button></Space>
        {result.output.sections.map((section) => <section key={section.heading}><h3>{section.heading}</h3>{section.items.some((item) => item.source_id)
          ? <div className="research-comparison-scroll"><table className="research-comparison"><thead><tr><th scope="col">资料</th><th scope="col">观点与依据</th><th scope="col">出处</th></tr></thead><tbody>{section.items.map((item, index) => <tr key={index}><th scope="row">{item.source_title}</th><td><Tag>{claimLabels[item.type]}</Tag>{item.text}</td><td>{item.evidence_ids.map((id) => <Button key={id} type="link" size="small" aria-label={`查看出处 ${citations.get(id)?.number}`} onClick={() => navigate(projectId, result.id, id)}>[{citations.get(id)?.number}]</Button>)}</td></tr>)}</tbody></table></div>
          : section.items.map((item, index) => <div className="research-claim" key={index}><Tag>{claimLabels[item.type]}</Tag><p>{item.text}</p><span className="research-citations">{item.evidence_ids.map((id) => <Button key={id} type="link" size="small" aria-label={`查看出处 ${citations.get(id)?.number}`} onClick={() => navigate(projectId, result.id, id)}>[{citations.get(id)?.number}]</Button>)}</span></div>)}</section>)}
        <h3>参考资料</h3><ol className="research-references">{result.output.citations.map((c) => <li key={c.id}><Button type="link" onClick={() => navigate(projectId, result.id, c.id)}>{c.title} · {citationLocation(c)}</Button></li>)}</ol>
        <Collapse items={[{ key: 'coverage', label: '资料覆盖情况', children: <ul>{result.output.coverage.map((c) => <li key={c.source_id}>{c.title}：检查 {c.chunks_reviewed}/{c.chunks_total} 个片段，发现 {c.evidence_found} 条证据，综合使用 {c.evidence_selected} 条候选证据。</li>)}</ul> }]} />
        <p className="research-hint">引用已核对原文位置；引用有效不等同于事实已经独立验证。</p>
      </>}
    </article>}
  </section>;
  return <div className="research-workspace">
    {error && <Alert className="research-error" type="error" message={error} closable onClose={() => setError('')} />}
    {!project ? !error && <Spin /> : screens.lg ? <div className="research-desktop">{sourcePanel}{resultPanel}</div> : <Tabs items={[{ key: 'results', label: '研究成果', children: resultPanel }, { key: 'sources', label: `资料 (${sources.length})`, children: sourcePanel }]} />}
    <Modal title="粘贴文章" open={pasteOpen} onCancel={() => !busy && setPasteOpen(false)} confirmLoading={busy} okText="添加资料" okButtonProps={{ disabled: !article.trim() || !articleTitle.trim() }} onOk={() => void action(async () => { await client.addSource(projectId, { title: articleTitle, text: article }); setPasteOpen(false); setArticle(''); setArticleTitle(''); await refreshSources(); })}>
      {error && <Alert type="error" message={error} />}<label htmlFor="research-article-title">文章标题</label><Input id="research-article-title" value={articleTitle} maxLength={200} onChange={(e) => setArticleTitle(e.target.value)} />
      <label htmlFor="research-article">文章正文</label><Input.TextArea id="research-article" value={article} rows={12} onChange={(e) => setArticle(e.target.value)} />
    </Modal>
    {importOpen && integrations && <ImportPicker client={client} integrations={integrations.applications} onClose={() => setImportOpen(false)} onImport={async (integration, entries) => {
      const failures: string[] = [];
      for (const entry of entries) { try { await client.addSource(projectId, { origin_type: integration.target, origin_id: entry.id, application_id: integration.id }); } catch (e) { failures.push(`${entry.title}：${documentError(e)}`); } }
      await refreshSources(); if (failures.length) throw new Error(failures.join('；'));
    }} />}
    <Modal title="保存研究成果" open={exportOpen} confirmLoading={busy} onCancel={() => !busy && setExportOpen(false)} okButtonProps={{ disabled: !exportApp }} onOk={() => void action(async () => {
      const integration = integrations?.applications.find((i) => i.id === exportApp); if (!integration || !result) return;
      const hash = `${result.id}:${integration.id}`; if (exportKey.current?.hash !== hash) exportKey.current = { hash, key: crypto.randomUUID() };
      const saved = await client.export(projectId, result.id, integration, exportKey.current.key); setExportOpen(false); exportKey.current = undefined;
      void message.success(saved.target === 'document' ? '已保存为新的私有在线文档，可在在线文档中分享。' : '已保存到网盘根目录。');
    })}>{error && <Alert type="error" message={error} />}<p>创建独立副本，保留出处列表及回溯链接。网盘保存为 Markdown 文件。</p><Select aria-label="保存目标应用" style={{ width: '100%' }} value={exportApp} onChange={setExportApp} options={integrations?.applications.map((i) => ({ value: i.id, label: i.name }))} /></Modal>
    <Drawer title="原文出处" open={!!citationId} onClose={() => navigate(projectId, resultId)} width={520}>
      {citationError ? <Alert type="error" message={citationError} /> : !citation ? <Spin /> : <div className="research-citation-detail"><h2>{citation.title}</h2><Tag>{citationLocation(citation)}</Tag><blockquote>{citation.quote}</blockquote><h3>所在原文片段</h3><p className="research-context">{highlightQuote(citation.context || '', citation.quote)}</p>
        <Button disabled={busy} icon={<FileText size={16} aria-hidden="true" />} onClick={() => void action(async () => saveResearchBlob(await client.original(projectId, citation.source_id), citation.filename || citation.title))}>下载导入时的原文件</Button>
        {citation.origin?.type === 'document' && <p><Link to={`/applications/${citation.origin.application_id}/documents?document=${citation.origin.id}`}>打开原始在线文档（当前版本）</Link></p>}
        <p className="research-hint">此处展示生成时使用的资料版本。</p></div>}
    </Drawer>
  </div>;
}

export function highlightQuote(context: string, quote: string) {
  const index = context.indexOf(quote);
  if (index < 0 || !quote) return context;
  return <>{context.slice(0, index)}<mark>{quote}</mark>{context.slice(index + quote.length)}</>;
}

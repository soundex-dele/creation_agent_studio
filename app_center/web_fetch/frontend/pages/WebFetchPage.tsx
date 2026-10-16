import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Pagination, Spin, Tabs } from 'antd';
import { ArrowLeft, Copy, Download, Globe, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { createIdempotencyKey } from '@platform/idempotency';
import { createApplicationRuntimeClient } from '@platform/runtime';
import { useOrganizationStore } from '@platform/organization';
import { useAuthStore } from '@platform/auth';
import { tenantApiRoot } from '@platform/tenant';
import { resolveApplicationPresentation } from '@platform/presentation';
import { downloadArtifact, errorMessage, fetchApi, readDocument, safeLink, statusLabel, terminal,
  type FetchHistory, type FetchRun, type WebDocument } from '../services/webFetch';
import './WebFetchPage.css';

export function WebFetchWorkspace({ organizationId, applicationId, initialRunId, onSelect, showHeader = true }: {
  organizationId: string; applicationId: string; initialRunId?: string; onSelect?: (id: string) => void; showHeader?: boolean;
}) {
  const client = useMemo(() => fetchApi(`${tenantApiRoot(organizationId)}/applications/${applicationId}/web-fetch`), [organizationId, applicationId]);
  const runtime = useMemo(() => createApplicationRuntimeClient({ organizationId, applicationId }), [organizationId, applicationId]);
  const [url, setUrl] = useState('');
  const [selected, setSelected] = useState<FetchRun>();
  const [history, setHistory] = useState<FetchHistory>({ count: 0, results: [] });
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [stage, setStage] = useState('');
  const [tab, setTab] = useState('preview');
  const [document, setDocument] = useState<{ runId: string; value: WebDocument }>();
  const [documentError, setDocumentError] = useState('');
  const [documentRevision, setDocumentRevision] = useState(0);
  const [copyFallback, setCopyFallback] = useState('');
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const copyRef = useRef<HTMLTextAreaElement>(null);
  const pending = useRef<{ url: string; key: string }>();
  const submitting = useRef(false);
  const initialized = useRef(false);
  const sequence = useRef(0);
  const active = Boolean(selected && !terminal(selected.status));
  const choose = useCallback((run: FetchRun) => {
    setSelected(run); setStage(''); setConnectionError(''); setCopyFallback(''); setCopied(false); onSelect?.(run.id);
  }, [onSelect]);
  useEffect(() => () => { ++sequence.current; }, []);
  useEffect(() => {
    let alive = true; setLoading(true); setHistoryError('');
    const initialSequence = sequence.current;
    void client.list(page).then(async result => {
      if (!alive) return;
      setHistory(result);
      if (!initialized.current) {
        const first = initialRunId ? await client.get(initialRunId) : result.results[0];
        if (alive) {
          initialized.current = true;
          if (first && sequence.current === initialSequence) choose(first);
        }
      }
    }).catch(e => { if (alive) setHistoryError(errorMessage(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, page, revision, initialRunId, choose]);

  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId || !active) return;
    let alive = true; let fetching = false;
    const reload = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const run = await client.get(selectedId);
        if (alive) { setSelected(run); if (terminal(run.status)) setRevision(value => value + 1); }
      } catch (e) { if (alive) setConnectionError(errorMessage(e)); }
      finally { fetching = false; }
    };
    const stream = runtime.subscribeRun(selectedId, {
      onEvent: async event => {
        if (!alive) return;
        if (event.type === 'progress.updated') setStage(String(event.payload.stage || ''));
        if (event.type.startsWith('run.') || event.type === 'artifact.created') await reload();
      },
      onSnapshot: reload,
      onError: () => { if (alive) setConnectionError('实时连接中断，正在自动刷新任务状态。'); },
      onConnectionChange: connected => { if (alive && connected) setConnectionError(''); },
    });
    const timer = setInterval(() => void reload(), 5000);
    return () => { alive = false; stream.abort(); clearInterval(timer); };
  }, [client, runtime, selectedId, active]);

  const documentArtifactId = selected?.status === 'succeeded' ? selected.artifacts.find(item => item.kind === 'web-document')?.id : undefined;
  useEffect(() => {
    setDocument(undefined); setDocumentError('');
    if (!selectedId || !documentArtifactId) return;
    let alive = true;
    const controller = new AbortController();
    void runtime.getArtifactAccess(selectedId, documentArtifactId)
      .then(access => readDocument(access, controller.signal))
      .then(value => { if (alive) setDocument({ runId: selectedId, value }); })
      .catch(e => { if (alive) setDocumentError(errorMessage(e)); });
    return () => { alive = false; controller.abort(); };
  }, [runtime, selectedId, documentArtifactId, documentRevision]);
  useEffect(() => { if (copyFallback) { copyRef.current?.focus(); copyRef.current?.select(); } }, [copyFallback]);

  const start = async (override?: string) => {
    if (submitting.current) return;
    const value = (override ?? url).trim();
    if (!safeLink(value)) { setError('请输入完整的 HTTP/HTTPS 网页地址。'); inputRef.current?.focus(); return; }
    submitting.current = true; setBusy(true); setError(''); setOpening(false);
    const token = ++sequence.current;
    if (pending.current?.url !== value) pending.current = { url: value, key: createIdempotencyKey() };
    try {
      const run = await client.start(value, pending.current.key);
      if (token === sequence.current) {
        choose(run); pending.current = undefined; initialized.current = true; setPage(1); setRevision(n => n + 1);
      }
    } catch (e) { if (token === sequence.current) setError(errorMessage(e)); }
    finally { submitting.current = false; if (token === sequence.current) setBusy(false); }
  };
  const open = async (id: string) => {
    const token = ++sequence.current; setOpening(true); setError('');
    try { const run = await client.get(id); if (token === sequence.current) choose(run); }
    catch (e) { if (token === sequence.current) setError(errorMessage(e)); }
    finally { if (token === sequence.current) setOpening(false); }
  };
  const cancel = async () => {
    if (!selected) return;
    const id = selected.id; setBusy(true); setError('');
    try {
      await runtime.sendCommand(id, { type: 'cancel', idempotency_key: createIdempotencyKey() });
      const run = await client.get(id);
      setSelected(previous => previous?.id === id ? run : previous); setRevision(n => n + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };
  const doc = document && document.runId === selectedId ? document.value : undefined;
  const json = doc ? JSON.stringify(doc, null, 2) : '';
  const copy = async () => {
    const text = tab === 'json' ? json : doc?.markdown || '';
    if (!text) return;
    setCopied(false);
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(text); setCopied(true); setCopyFallback('');
    } catch { setCopyFallback(text); }
  };
  const download = async (kind: string) => {
    if (!selected) return;
    const artifact = selected.artifacts.find(item => item.kind === kind);
    if (!artifact) return;
    try {
      const access = await runtime.getArtifactAccess(selected.id, artifact.id);
      await downloadArtifact(access, kind === 'web-document' ? 'article.json' : 'article.md');
    } catch (e) { setError(errorMessage(e)); }
  };

  return <div className="web-fetch-page app-scroll-page"><div className="web-fetch-container">
    {showHeader && <Link to="/apps" className="web-fetch-back"><ArrowLeft size={16} aria-hidden="true" />返回应用</Link>}
    <header className="web-fetch-heading"><Globe size={28} aria-hidden="true" /><div><h1>网页爬取</h1><p>把公开网页和公众号文章，保存为可阅读、可复用的正文。</p></div></header>
    <section className="web-fetch-card">
      <form onSubmit={event => { event.preventDefault(); void start(); }}>
        <label htmlFor="web-fetch-url">网页地址</label>
        <div className="web-fetch-input-row"><input ref={inputRef} id="web-fetch-url" type="text" inputMode="url" autoComplete="url" maxLength={8192} value={url} placeholder="https://…" onChange={event => { setUrl(event.target.value); if (pending.current?.url !== event.target.value.trim()) pending.current = undefined; }} />
          <Button type="primary" htmlType="submit" size="large" loading={busy} disabled={active || opening}>开始抓取</Button></div>
        <p className="web-fetch-hint">每次一个网址 · 保留图片和视频链接 · 需要登录或验证码的页面暂不支持</p>
      </form>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
    </section>
    <section className="web-fetch-card" aria-label="抓取结果" aria-busy={active || opening}>
      <div className="web-fetch-section-header"><h2>抓取结果</h2><span role="status">{selected ? statusLabel(selected.status, stage) : '等待输入网址'}</span>
        {active && <Button disabled={busy || selected?.status === 'cancelling'} onClick={() => void cancel()}>取消抓取</Button>}</div>
      {connectionError && <Alert type="warning" message={connectionError} />}
      {selected && <p className="web-fetch-source"><a href={safeLink(selected.input.url)} target="_blank" rel="noopener noreferrer">{selected.input.url}</a></p>}
      {opening || active ? <div className="web-fetch-empty"><Spin /><p>{opening ? '正在打开历史结果' : '任务会在后台继续，离开页面后可以从历史记录恢复。'}</p></div>
        : !selected ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="正文预览、Markdown 和 JSON 会显示在这里" />
          : selected.status !== 'succeeded' ? <Alert type={selected.status === 'failed' ? 'error' : 'info'} message={selected.error_message || '抓取已取消'} />
            : documentError ? <Alert type="error" message={documentError} action={<Button onClick={() => setDocumentRevision(n => n + 1)}>重新加载</Button>} />
              : !documentArtifactId ? <Alert type="warning" message="结果文件不可用，请重新抓取。" />
                : !doc ? <Spin /> : <>
                  <h3 className="web-fetch-title">{doc.title || '未提供标题'}</h3>
                  <dl className="web-fetch-metadata"><div><dt>作者</dt><dd>{doc.author || '未提供'}</dd></div><div><dt>来源</dt><dd>{doc.siteName || new URL(doc.url).hostname}</dd></div><div><dt>发布时间</dt><dd>{doc.publishedAt || '未提供'}</dd></div></dl>
                  {doc.warnings.map((warning, index) => <Alert key={index} type="warning" message={warning} />)}
                  <Tabs activeKey={tab} onChange={value => { setTab(value); setCopied(false); setCopyFallback(''); }} items={[
                    { key: 'preview', label: '正文', children: <article className="web-fetch-article"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} urlTransform={safeLink} components={{
                      a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
                      img: ({ src, alt }) => src ? <a href={src} target="_blank" rel="noopener noreferrer">图片：{alt || '查看原图'}</a> : null,
                      table: ({ children }) => <div className="web-fetch-table"><table>{children}</table></div>,
                    }}>{doc.markdown}</ReactMarkdown></article> },
                    { key: 'markdown', label: 'Markdown', children: <pre className="web-fetch-code" tabIndex={0}>{doc.markdown}</pre> },
                    { key: 'json', label: 'JSON', children: <pre className="web-fetch-code" tabIndex={0}>{json}</pre> },
                  ]} />
                  <div className="web-fetch-actions"><Button icon={<Copy size={16} aria-hidden="true" />} onClick={() => void copy()}>{tab === 'json' ? '复制 JSON' : '复制 Markdown'}</Button>
                    <Button icon={<Download size={16} aria-hidden="true" />} onClick={() => void download('web-markdown')}>下载 Markdown</Button><Button onClick={() => void download('web-document')}>下载 JSON</Button>
                    <span role="status">{copied ? '已复制' : ''}</span></div>
                  {copyFallback && <div className="web-fetch-copy"><label htmlFor="web-fetch-copy">浏览器不支持自动复制，请选择下方文字复制</label><textarea id="web-fetch-copy" ref={copyRef} value={copyFallback} readOnly rows={6} /></div>}
                </>}
      {selected && !active && <Button className="web-fetch-retry" disabled={busy || opening} icon={<RefreshCw size={16} aria-hidden="true" />} onClick={() => void start(selected.input.url)}>重新抓取</Button>}
    </section>
    <section className="web-fetch-card" aria-label="我的抓取历史"><div className="web-fetch-section-header"><h2>我的抓取历史 <span>{history.count}</span></h2><Button onClick={() => setRevision(n => n + 1)}>刷新</Button></div>
      {historyError ? <Alert type="error" message={historyError} action={<Button onClick={() => setRevision(n => n + 1)}>重试</Button>} /> : loading ? <Spin />
        : history.results.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="抓取记录仅自己可见" />
          : <ul className="web-fetch-history">{history.results.map(run => <li key={run.id}><button disabled={busy} aria-current={run.id === selectedId ? 'true' : undefined} onClick={() => void open(run.id)}><strong>{String(run.output_summary.title || run.input.url)}</strong><span>{run.input.url}</span><small>{statusLabel(run.status)} · {run.created_at ? new Date(run.created_at).toLocaleString('zh-CN') : ''}</small></button></li>)}</ul>}
      <Pagination current={page} total={history.count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
    </section>
  </div></div>;
}

export default function WebFetchPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  const [params, setParams] = useSearchParams();
  const initialRunId = useRef(params.get('run') || undefined);
  const onSelect = useCallback((id: string) => { setParams(current => { const next = new URLSearchParams(current); next.set('run', id); return next; }, { replace: true }); }, [setParams]);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <WebFetchWorkspace key={`${organizationId}:${applicationId}:${userId}`} organizationId={organizationId} applicationId={applicationId} initialRunId={initialRunId.current} onSelect={onSelect} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}

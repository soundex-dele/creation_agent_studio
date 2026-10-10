import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Checkbox, Drawer, Empty, Input, Select, Spin, Tag } from 'antd';
import type { ResearchClient } from '@/services/douyinResearch';
import { knowledgeDocumentLink, type KnowledgeCard, type KnowledgeShare, type OrganizationKnowledgeSnapshot } from '@/services/douyinKnowledge';
import type { KnowledgeBaseSummary } from '@/types/knowledge';
import { documentError } from '@/services/documents';
import { Field } from './ResearchCommon';
import './CreationKnowledge.css';

const statuses: Record<string, string> = { pending: '等待索引', indexing: '索引中', ready: '可检索', failed: '索引失败', deleted: '目标文档已删除' };

export function KnowledgeShareDrawer({ client, card, children, onClose }: {
  client: ResearchClient; card: KnowledgeCard; children: ReactNode; onClose: () => void;
}) {
  const [bases, setBases] = useState<KnowledgeBaseSummary[]>([]);
  const [shares, setShares] = useState<KnowledgeShare[]>([]);
  const [target, setTarget] = useState<number>();
  const [canShare, setCanShare] = useState(false);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const request = useRef(0);
  const load = useCallback(async () => {
    const token = ++request.current; setLoading(true); setError('');
    try {
      const [libraries, data] = await Promise.all([client.knowledgeBases(), client.knowledgeShares(card.id)]);
      if (token !== request.current) return;
      setBases(libraries.filter(base => base.is_active)); setShares(data.results); setCanShare(data.can_share);
    } catch (e) { if (token === request.current) setError(documentError(e)); }
    finally { if (token === request.current) setLoading(false); }
  }, [client, card.id]);
  useEffect(() => { void load(); return () => { request.current += 1; }; }, [load]);
  const pending = shares.some(row => ['pending', 'indexing'].includes(row.index_status));
  useEffect(() => {
    if (!pending || busy) return;
    let active = true; let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void client.knowledgeShares(card.id).then(data => { if (active) { setShares(data.results); setCanShare(data.can_share); } })
        .catch(e => { if (active) setError(documentError(e)); }).finally(() => { polling = false; });
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [pending, busy, client, card.id]);
  const existing = shares.find(row => row.knowledge_base_id === target);
  const current = existing && !existing.document_deleted && existing.shared_revision === card.revision;
  const label = existing?.document_deleted ? '再次分享到组织知识库' : current && existing.index_status === 'failed' ? '重试索引' : existing && !current ? '更新分享' : current ? '已分享当前版本' : '确认分享到组织知识库';
  async function publish() {
    if (!target) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const row = await client.shareKnowledge(card.id, { knowledge_base_id: target, revision: card.revision, ...(existing?.document_deleted && { recreate: true }) });
      setShares(old => [...old.filter(item => item.knowledge_base_id !== row.knowledge_base_id), row]);
      setNotice(`已保存到「${row.knowledge_base_name}」，${statuses[row.index_status] || row.index_status}。`);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <Drawer title="分享到组织知识库" className="douyin-knowledge-drawer" open width={680} maskClosable={false} onClose={() => !busy && onClose()}
    footer={<div className="douyin-actions"><Button disabled={busy} onClick={onClose}>关闭</Button><Button type="primary" loading={busy} disabled={!canShare || !target || loading || Boolean(current && existing.index_status !== 'failed')} onClick={() => void publish()}>{label}</Button></div>}>
    <div className="douyin-form">
      <Alert type="info" showIcon message="分享后的内容对组织成员可见" description="只分享下方预览的知识与出处。后续修改需手动更新分享；删除个人卡片不会删除组织文档。" />
      {error && <Alert type="error" message={error} description="如卡片版本已更新，请关闭后刷新知识，再重新分享。" action={<Button disabled={busy} onClick={() => void load()}>刷新分享记录</Button>} />}
      {notice && <Alert type="success" message={notice} />}{loading && <Spin />}
      {!loading && !error && !canShare && <Alert type="warning" message="需要知识库写入权限才能分享或更新，请联系组织管理员。" />}
      <Field label="目标知识库"><Select aria-label="目标知识库" value={target} disabled={busy || loading || !canShare} placeholder="选择组织知识库" options={bases.map(base => ({ value: base.id, label: base.name }))} onChange={value => { setTarget(value); setNotice(''); }} /></Field>
      {!loading && !error && !bases.length && <Empty description="没有可用的组织知识库，请先在知识库中创建。" />}
      {existing?.document_deleted && <Alert type="warning" message="目标文档已删除" description="点击再次分享会新建文档。" />}
      <h3>分享内容预览 · 版本 {card.revision}</h3>{children}
      {!!shares.length && <section aria-label="分享记录"><h3>分享记录</h3>{shares.map(row => <article className="douyin-research-card douyin-knowledge-card" key={row.knowledge_base_id}>
        <strong>{row.knowledge_base_name}</strong><p>已分享版本 {row.shared_revision} · {statuses[row.index_status] || row.index_status}{!row.is_active && ' · 知识库已停用'}</p>
        {!row.document_deleted && row.shared_revision < card.revision && <Tag>有新版本待分享</Tag>}
        <div className="douyin-actions">{row.document_id && !row.document_deleted && <a href={knowledgeDocumentLink(row.knowledge_base_id, row.document_id)} target="_blank" rel="noreferrer">查看文档</a>}
          <Button disabled={busy || !canShare || !row.is_active} onClick={() => setTarget(row.knowledge_base_id)}>选择此库</Button></div>
      </article>)}</section>}
    </div>
  </Drawer>;
}

function Source({ item, client }: { item: OrganizationKnowledgeSnapshot; client: ResearchClient }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function preview() {
    setBusy(true); setError('');
    try {
      const blob = await client.organizationKnowledgeContent(item.knowledge_base_id, item.document_id);
      const url = URL.createObjectURL(blob); window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <><small>{item.knowledge_base_name} · 版本 {item.revision}{item.page_number != null && ` · 第 ${item.page_number} 页`}{item.section_path.length > 0 && ` · ${item.section_path.join(' / ')}`}</small>
    {item.provenance?.basis && <Tag>{{ author_view: '作者观点', observation: '观察', inference: 'AI 推断' }[item.provenance.basis] || item.provenance.basis}</Tag>}
    <Button loading={busy} onClick={() => void preview()}>查看原文</Button>{error && <Alert type="warning" message={error} description="原文可能已更新或移除；已生成结果中的引用快照保留。" />}</>;
}

export function OrganizationKnowledgeReferences({ items, client }: { items?: OrganizationKnowledgeSnapshot[]; client: ResearchClient }) {
  if (!items?.length) return null;
  return <details className="douyin-knowledge-reference"><summary>本次参考资料 · 组织知识库（{items.length}）</summary>
    <p>以下为生成时冻结的资料，原文后续修改不改变本次引用。资料不自动代表你的真实经历。</p>
    <div className="douyin-knowledge-grid">{items.map(item => <article className="douyin-research-card douyin-knowledge-card" key={item.chunk_id}>
      <h4>{item.title}</h4><p>{item.snippet}</p><Source item={item} client={client} />
    </article>)}</div>
  </details>;
}

export function OrganizationKnowledgePicker({ client, query, selected, onChange, personalCount }: {
  client: ResearchClient; query: string; selected: OrganizationKnowledgeSnapshot[];
  onChange: (value: OrganizationKnowledgeSnapshot[]) => void; personalCount: number;
}) {
  const [open, setOpen] = useState(false);
  return <section className="douyin-form douyin-knowledge-picker" aria-label="组织知识库参考">
    <h3>组织知识库 <small>已选 {selected.length} 项</small></h3><p>个人卡片与组织资料合计 {personalCount + selected.length} / 10 项，勾选后才用于本次创作。</p>
    <Button aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起组织资料检索' : '检索组织知识库'}</Button>
    {!!selected.length && <div className="douyin-knowledge-selected">{selected.map(item => <div key={item.chunk_id}><Checkbox checked onChange={() => onChange(selected.filter(row => row.chunk_id !== item.chunk_id))}>{item.title} · {item.knowledge_base_name}</Checkbox></div>)}</div>}
    {open && <OrganizationSearch client={client} query={query} selected={selected} onChange={onChange} personalCount={personalCount} />}
  </section>;
}

function OrganizationSearch({ client, query, selected, onChange, personalCount }: {
  client: ResearchClient; query: string; selected: OrganizationKnowledgeSnapshot[];
  onChange: (value: OrganizationKnowledgeSnapshot[]) => void; personalCount: number;
}) {
  const [bases, setBases] = useState<KnowledgeBaseSummary[]>([]); const [baseIds, setBaseIds] = useState<number[]>([]);
  const [text, setText] = useState(query.slice(0, 4000)); const [edited, setEdited] = useState(false);
  const [results, setResults] = useState<OrganizationKnowledgeSnapshot[]>([]);
  const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(''); const [mode, setMode] = useState(''); const [searched, setSearched] = useState(false);
  const request = useRef(0);
  const searchRequest = useRef(0);
  useEffect(() => {
    if (edited) return;
    searchRequest.current += 1;
    setText(query.slice(0, 4000)); setBusy(false); setResults([]); setSearched(false); setMode('');
  }, [query, edited]);
  const load = useCallback(async () => {
    searchRequest.current += 1; setBusy(false); setResults([]); setSearched(false); setMode('');
    const token = ++request.current; setLoading(true); setError('');
    try {
      const data = await client.knowledgeBases();
      if (token === request.current) {
        const available = data.filter(base => base.is_active); setBases(available);
        setBaseIds(old => old.filter(id => available.some(base => base.id === id)));
      }
    }
    catch (e) { if (token === request.current) setError(documentError(e)); }
    finally { if (token === request.current) setLoading(false); }
  }, [client]);
  useEffect(() => { void load(); return () => { request.current += 1; searchRequest.current += 1; }; }, [load]);
  async function search() {
    if (!text.trim() || !baseIds.length) return;
    const token = ++searchRequest.current; setBusy(true); setError('');
    try {
      const data = await client.searchOrganizationKnowledge(text.trim(), baseIds);
      if (token !== searchRequest.current) return;
      setResults(data.results); setMode(data.retrieval_mode); setSearched(true);
    } catch (e) { if (token === searchRequest.current) setError(documentError(e)); }
    finally { if (token === searchRequest.current) setBusy(false); }
  }
  function invalidate() { searchRequest.current += 1; setBusy(false); setResults([]); setSearched(false); setMode(''); }
  return <div className="douyin-form">
    {error && <Alert type="error" message={error} description="可重试，也可不引用组织资料继续创作。" action={<Button onClick={() => void load()}>重新加载知识库</Button>} />}
    <Field label="检索知识库"><Select mode="multiple" aria-label="检索知识库" loading={loading} value={baseIds} placeholder="选择一个或多个知识库" options={bases.map(base => ({ value: base.id, label: base.name }))} onChange={value => { setBaseIds(value); invalidate(); }} /></Field>
    <Field label="检索组织资料"><Input.Search aria-label="检索组织资料" maxLength={4000} value={text} onChange={e => { setText(e.target.value); setEdited(true); invalidate(); }} onSearch={() => void search()} enterButton="搜索资料" loading={busy} disabled={loading || !baseIds.length} /></Field>
    {!loading && !error && !bases.length && <Empty description="暂无可用组织知识库，可使用个人知识卡片继续创作。" />}
    {mode === 'lexical' && <p role="status">当前使用关键词检索。</p>}
    {searched && !busy && !results.length && <Empty description="没有匹配资料，可调整关键词或不引用资料继续创作。" />}
    <div className="douyin-knowledge-grid">{results.map(item => {
      const checked = selected.some(row => row.chunk_id === item.chunk_id);
      return <article className="douyin-research-card douyin-knowledge-card" key={item.chunk_id}><h4>{item.title}</h4><p>{item.snippet}</p><Source item={item} client={client} />
        <Checkbox checked={checked} disabled={busy || !checked && selected.length + personalCount >= 10} onChange={e => {
          if (e.target.checked && selected.length + personalCount >= 10) return;
          onChange(e.target.checked ? [...selected, item] : selected.filter(row => row.chunk_id !== item.chunk_id));
        }}>引用 {item.title}</Checkbox>
      </article>;
    })}</div>
  </div>;
}

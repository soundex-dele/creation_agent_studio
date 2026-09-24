import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useBlocker, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Drawer, Empty, Grid, Input, Pagination, Segmented, Spin, message } from 'antd';
import { ArrowLeft, ArrowUpRight, Clock3, FileText, Menu, PenLine, Plus, Sparkles, Users } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { documentError, documentsApi, type DocumentPage, type OnlineDocument } from '@/services/documents';
import { DocumentEditor } from './documents/DocumentEditor';
import type { DocumentDraft } from './documents/DocumentDraft';
import './DocumentsPage.css';

export function DocumentsWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const client = useMemo(() => documentsApi(base), [base]);
  const [params] = useSearchParams();
  const linkedDocument = params.get('document');
  const [scope, setScope] = useState('mine');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [listing, setListing] = useState<DocumentPage>({ count: 0, results: [] });
  const [selected, setSelected] = useState<OnlineDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState('');
  const [listOpen, setListOpen] = useState(false);
  const [editorKey, setEditorKey] = useState(0);
  const draft = useRef<DocumentDraft | null>(null);
  const screens = Grid.useBreakpoint();
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  const onDraft = useCallback((value: DocumentDraft | null) => { draft.current = value; }, []);
  const blocker = useBlocker(() => Boolean(draft.current?.hasChanges));
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    void draft.current?.save().then(() => blocker.proceed()).catch((e) => { void message.error(`未能保存，请先处理当前草稿：${documentError(e)}`); blocker.reset(); });
  }, [blocker]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (draft.current?.hasChanges) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      void client.list(scope, search, page, controller.signal).then((value) => { if (!controller.signal.aborted) { setListing(value); if (!value.results.length && page > 1) setPage(page - 1); } }).catch((e) => { if (!controller.signal.aborted) setError(documentError(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, search ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [client, scope, search, page, revision]);
  const onOpen = useCallback((value: OnlineDocument) => { setSelected(value); setEditorKey((n) => n + 1); setListOpen(false); refresh(); }, [refresh]);
  useEffect(() => {
    if (!linkedDocument) return;
    let active = true;
    setOpening(true);
    void client.get(linkedDocument).then(value => { if (active) onOpen(value); })
      .catch(e => { if (active) void message.error(documentError(e)); })
      .finally(() => { if (active) setOpening(false); });
    return () => { active = false; };
  }, [client, linkedDocument, onOpen]);
  const open = async (id?: string) => {
    setOpening(true);
    try { await draft.current?.save(); onOpen(id ? await client.get(id) : await client.create()); }
    catch (e) { void message.error(documentError(e)); }
    finally { setOpening(false); }
  };
  const list = <aside className="documents-list" aria-label="文档列表">
    {showHeader && <Link className="documents-back" to="/apps"><ArrowLeft size={14} aria-hidden="true" />返回应用</Link>}
    <header><div className="documents-app-icon"><FileText size={23} aria-hidden="true" /></div><div><h1>在线文档</h1><p>记录灵感，沉淀每一个想法</p></div></header>
    <Button className="documents-create" type="primary" icon={<Plus size={17} aria-hidden="true" />} block loading={opening} onClick={() => void open()}>新建文档</Button>
    <Segmented block aria-label="文档范围" value={scope} onChange={(value) => { setScope(String(value)); setPage(1); }} options={[{ label: '我的文档', value: 'mine' }, { label: '共享给我', value: 'shared' }]} />
    <Input.Search aria-label="搜索文档" placeholder="搜索标题或正文" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} allowClear />
    <p className="documents-list-caption"><span><Clock3 size={13} aria-hidden="true" />最近更新</span><span>{listing.count} 份文档</span></p>
    {error ? <Alert type="error" message={error} action={<Button onClick={refresh}>重试</Button>} /> : loading ? <div className="documents-list-loading"><Spin /></div> : listing.results.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={search ? '没有找到匹配的文档' : scope === 'mine' ? '新建文档，开始记录想法' : '还没有成员向你共享文档'} /> : <ul>
      {listing.results.map((doc) => <li key={doc.id}><button className={selected?.id === doc.id ? 'is-selected' : ''} disabled={opening} onClick={() => void open(doc.id)} aria-current={selected?.id === doc.id ? 'page' : undefined}>
        <div className="documents-item-title"><FileText size={17} aria-hidden="true" /><strong>{doc.title}</strong></div><p>{doc.plain_text || '空白文档，等待你的第一个想法'}</p><div className="documents-item-meta"><time dateTime={doc.updated_at}>{new Date(doc.updated_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time><span>{doc.permission === 'viewer' ? '只读' : doc.permission === 'editor' ? '可编辑' : '我的文档'}</span></div>
      </button></li>)}
    </ul>}
    <Pagination size="small" current={page} total={listing.count} pageSize={20} showSizeChanger={false} onChange={setPage} hideOnSinglePage />
  </aside>;
  return <section className="documents-workspace" aria-label="在线文档工作台">
    {screens.lg ? list : <><div className="documents-mobile-nav"><Button icon={<Menu size={17} aria-hidden="true" />} onClick={() => setListOpen(true)}>文档列表</Button><span>在线文档</span><Button type="text" aria-label="新建文档" icon={<Plus size={19} aria-hidden="true" />} loading={opening} onClick={() => void open()} /></div><Drawer title="在线文档" open={listOpen} onClose={() => setListOpen(false)} placement="left">{list}</Drawer></>}
    {selected ? <DocumentEditor key={`${selected.id}:${editorKey}`} base={base} document={selected} onDraft={onDraft} onSaved={refresh} onOpen={onOpen} onDelete={() => { setSelected(null); refresh(); }} /> : <section className="documents-welcome">
      <div className="documents-welcome-content">
        <span className="documents-eyebrow"><PenLine size={15} aria-hidden="true" />你的灵感，从这里开始</span>
        <div className="documents-paper-art" aria-hidden="true"><div className="documents-art-sheet"><FileText size={28} /><i /><i /><i /><div><span /><span /><span /></div></div><span className="documents-art-spark"><Sparkles size={23} /></span></div>
        <h2>让想法成为文档<span>让创作自然发生。</span></h2>
        <p>从一闪而过的灵感，到值得分享的作品。<br />在这里安心书写，用 AI 完善每一段表达。</p>
        <Button type="primary" size="large" icon={<Plus size={18} aria-hidden="true" />} loading={opening} onClick={() => void open()}>{listing.count > 0 ? '开始一份新文档' : '新建第一份文档'}</Button>
        <Button type="link" onClick={() => setListOpen(true)} className="documents-mobile-list-link">查看文档列表<ArrowUpRight size={15} aria-hidden="true" /></Button>
      </div>
      <div className="documents-features"><div><PenLine size={20} aria-hidden="true" /><strong>专注书写</strong><p>丰富格式，自动保存</p></div><div><Users size={20} aria-hidden="true" /><strong>轻松共享</strong><p>与成员分享每一份灵感</p></div><div><Sparkles size={20} aria-hidden="true" /><strong>AI 随行</strong><p>润色、续写，拓展思路</p></div></div>
    </section>}
  </section>;
}

export default function DocumentsPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <div className="documents-host"><DocumentsWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/documents`} showHeader={resolveApplicationPresentation(params).showApplicationHeader} /></div>;
}

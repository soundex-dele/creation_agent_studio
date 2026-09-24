import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Drawer, Empty, Grid, Input, Pagination, Spin, Tag } from 'antd';
import { ArrowLeft, AudioLines, FileText, Headphones, ListTodo, Menu, Plus, Search } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { activeMeeting, meetingApi, meetingError, meetingStatus, timeLabel, type MeetingRecord, type MeetingSummary } from '@/services/meetingAssistant';
import { RecordingDetail } from './meeting/RecordingDetail';
import { UploadRecording } from './meeting/UploadRecording';
import './MeetingAssistantPage.css';

export function MeetingWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const client = useMemo(() => meetingApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('record');
  const [record, setRecord] = useState<MeetingRecord | null>(null);
  const [listing, setListing] = useState<{ count: number; results: MeetingSummary[] }>({ count: 0, results: [] });
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [upload, setUpload] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [dirty, setDirty] = useState(false);
  const screens = Grid.useBreakpoint();
  const latestId = useRef(selectedId);
  latestId.current = selectedId;
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      void client.list(search, page, controller.signal).then(value => {
        if (!controller.signal.aborted) { setListing(value); if (!value.results.length && page > 1) setPage(page - 1); }
      }).catch(e => { if (!controller.signal.aborted) setError(meetingError(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, search ? 250 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [client, search, page, revision]);
  useEffect(() => {
    if (!selectedId) { setRecord(null); setOpening(false); setDetailError(''); return; }
    const controller = new AbortController();
    setOpening(true); setDetailError(''); setRecord(null);
    void client.get(selectedId, controller.signal).then(value => { if (!controller.signal.aborted) setRecord(value); })
      .catch(e => { if (!controller.signal.aborted) setDetailError(meetingError(e)); })
      .finally(() => { if (!controller.signal.aborted) setOpening(false); });
    return () => controller.abort();
  }, [client, selectedId]);
  const running = record && activeMeeting(record.status);
  useEffect(() => {
    if (!selectedId || !running) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await client.get(selectedId, controller.signal);
        if (controller.signal.aborted) return;
        setRecord(value); setDetailError('');
        if (!activeMeeting(value.status)) refresh();
      } catch (e) { if (!controller.signal.aborted) setDetailError(meetingError(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 1500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [client, selectedId, running, refresh]);
  const select = (id: string | null) => {
    if (dirty) return;
    const next = new URLSearchParams(params);
    if (id) next.set('record', id); else next.delete('record');
    setParams(next); setDrawer(false);
  };
  const changed = (value: MeetingRecord) => { if (latestId.current === value.id) { setRecord(value); refresh(); } };
  const list = <aside className="meeting-sidebar" aria-label="录音列表">
    {showHeader && <Link className="meeting-back" to="/apps"><ArrowLeft size={14} aria-hidden="true" />返回应用</Link>}
    <div className="meeting-brand"><span><AudioLines size={24} aria-hidden="true" /></span><div><h1>会议与访谈助手</h1><p>让每一次对话，留下价值</p></div></div>
    <Button type="primary" size="large" block icon={<Plus size={18} aria-hidden="true" />} onClick={() => setUpload(true)} disabled={dirty}>上传录音</Button>
    <Input allowClear aria-label="搜索录音" placeholder="搜索录音标题" prefix={<Search size={15} aria-hidden="true" />} value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} />
    <div className="meeting-list-meta"><span>我的录音 · {listing.count}</span><Button type="text" size="small" onClick={refresh}>刷新</Button></div>
    {error ? <Alert type="error" message={error} action={<Button onClick={refresh}>重试</Button>} /> : loading ? <div className="meeting-loading"><Spin /></div> : !listing.results.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={search ? '未找到录音' : '还没有录音'} /> : <ul className="meeting-record-list">{listing.results.map(item => <li key={item.id}>
      <button type="button" aria-current={selectedId === item.id ? 'true' : undefined} disabled={dirty} onClick={() => select(item.id)}><div><AudioLines size={17} aria-hidden="true" /><strong>{item.title}</strong></div><p>{item.kind === 'meeting' ? '会议' : '访谈'} · {item.recorded_on}</p><footer><span>{timeLabel(item.duration)}</span><Tag>{meetingStatus[item.id === record?.id ? record.status : item.status]}</Tag></footer></button>
    </li>)}</ul>}
    {listing.count > 20 && <Pagination size="small" current={page} pageSize={20} total={listing.count} showSizeChanger={false} onChange={setPage} />}
    <p className="meeting-privacy">录音和分析仅自己可见</p>
  </aside>;
  return <section className="meeting-workspace" aria-label="会议与访谈助手">
    {screens.lg ? list : <><nav className="meeting-mobile-nav"><Button icon={<Menu size={18} aria-hidden="true" />} onClick={() => setDrawer(true)}>我的录音</Button><Button type="primary" disabled={dirty} onClick={() => setUpload(true)}>上传录音</Button></nav><Drawer title="我的录音" placement="left" open={drawer} onClose={() => setDrawer(false)}>{list}</Drawer></>}
    <main className="meeting-main">
      {detailError && <Alert type="error" message={detailError} action={<Button onClick={() => selectedId && void client.get(selectedId).then(value => { changed(value); setDetailError(''); }).catch(e => setDetailError(meetingError(e)))}>重试</Button>} />}
      {opening ? <div className="meeting-loading"><Spin /><span>正在打开录音…</span></div> : record ? <RecordingDetail key={record.id} client={client} record={record} onChange={changed} onDirty={setDirty} onDelete={() => { setDirty(false); select(null); refresh(); }} /> : <section className="meeting-welcome">
        <span className="meeting-welcome-icon"><Headphones size={42} aria-hidden="true" /></span><p className="meeting-eyebrow">专注对话，留住重点</p><h2>从一段录音，<br />到清晰的下一步。</h2><p>会议里的决定，访谈中的好观点。<br />把值得留住的内容整理出来，随时回听核对。</p>
        <Button type="primary" size="large" icon={<Plus size={17} aria-hidden="true" />} onClick={() => setUpload(true)}>上传第一段录音</Button>
        <div className="meeting-features"><div><AudioLines aria-hidden="true" /><h3>逐字留存</h3><p>按时间分段，点击回听</p></div><div><FileText aria-hidden="true" /><h3>沉淀素材</h3><p>摘要、原话与文章提纲</p></div><div><ListTodo aria-hidden="true" /><h3>确认行动</h3><p>由你决定哪些加入待办</p></div></div>
      </section>}
    </main>
    {upload && <UploadRecording client={client} onClose={() => setUpload(false)} onCreated={value => { setUpload(false); select(value.id); refresh(); }} />}
  </section>;
}

export default function MeetingAssistantPage() {
  const { applicationId } = useParams();
  const [params] = useSearchParams();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <MeetingWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/meeting-assistant`} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}

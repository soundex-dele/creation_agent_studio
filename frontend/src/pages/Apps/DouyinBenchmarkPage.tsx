import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Input, Modal, Pagination, Select, Spin } from 'antd';
import { ArrowLeft, ArrowUpRight, Plus, ScanSearch } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { documentError } from '@/services/documents';
import { douyinApi, type DouyinAccount } from '@/services/douyinBenchmark';
import { DouyinWorkspace } from './douyin/DouyinWorkspace';
import { CollectorSettings } from './douyin/CollectorSettings';
import './DouyinBenchmarkPage.css';

export function DouyinHome({ base }: { base: string }) {
  const client = useMemo(() => douyinApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const accountId = params.get('account');
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [connection, setConnection] = useState<{ connected: boolean; message: string } | null>(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(0); const [page, setPage] = useState(1); const [refresh, setRefresh] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false); const [formError, setFormError] = useState('');
  const [form, setForm] = useState({ source: '', count: 50, group: '', notes: '' });
  const navigate = (id: string | null) => setParams((old) => { const next = new URLSearchParams(old); if (id) next.set('account', id); else next.delete('account'); return next; });
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    void client.accounts(page).then((data) => { if (active) { setAccounts(data.results); setCount(data.count); } }).catch((e) => { if (active) setError(documentError(e)); }).finally(() => { if (active) setLoading(false); });
    void client.connection().then((data) => { if (active) setConnection(data); }).catch((e) => { if (active) setConnection({ connected: false, message: documentError(e) }); });
    return () => { active = false; };
  }, [client, page, refresh]);
  return <main className="douyin-host app-scroll-page">
    <header className="douyin-header"><div>
      {resolveApplicationPresentation(params).showApplicationHeader && <Link to="/apps"><ArrowLeft size={14} aria-hidden="true" /> 返回应用</Link>}
      <div className="douyin-title"><ScanSearch size={32} aria-hidden="true" /><div><small>从内容研究到自己的表达</small><h1>抖音对标助手</h1></div></div>
      <p>找到值得研究的作品，把结构与方法变成你的拍摄脚本。</p>
    </div><div className="douyin-actions"><Button onClick={() => setSettingsOpen(true)}>采集设置</Button>{accountId && <Button onClick={() => navigate(null)}>全部账号</Button>}<Button type="primary" icon={<Plus size={16} aria-hidden="true" />} onClick={() => { setOpen(true); setFormError(''); }}>添加对标账号</Button></div></header>
    {connection && <Alert type={connection.connected ? 'success' : 'warning'} showIcon message={connection.message} action={<Button size="small" onClick={() => setRefresh((v) => v + 1)}>检查配置</Button>} />}
    {accountId ? <DouyinWorkspace key={accountId} client={client} accountId={accountId} onRemoved={() => { navigate(null); setRefresh((v) => v + 1); }} /> : <section className="douyin-panel">
      <div className="douyin-section-title"><h2>我的对标账号</h2><span>个人资料与创作历史仅自己可见</span></div>
      {error ? <Alert type="error" message={error} action={<Button onClick={() => setRefresh((v) => v + 1)}>重试</Button>} /> : loading ? <Spin /> : !accounts.length ? <Empty description="添加第一个账号，开始研究选题和内容结构"><Button type="primary" onClick={() => setOpen(true)}>添加账号</Button></Empty> : <div className="douyin-account-grid">{accounts.map((a) => <button className="douyin-account-card" key={a.id} onClick={() => navigate(a.id)}><div><ScanSearch size={22} aria-hidden="true" /><ArrowUpRight size={18} aria-hidden="true" /></div><h3>{a.name || '待采集账号'}</h3><p>{a.profile.signature || a.notes || '采集作品后查看账号分析'}</p><small>{a.group || '未分组'}</small></button>)}</div>}
      <Pagination current={page} total={count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
    </section>}
    {settingsOpen && <CollectorSettings client={client} onClose={() => setSettingsOpen(false)} onSaved={() => setRefresh((v) => v + 1)} />}
    <Modal className="douyin-modal" title="添加对标账号" open={open} confirmLoading={busy} okText="添加并采集" okButtonProps={{ disabled: !form.source.trim() }} onCancel={() => !busy && setOpen(false)} onOk={() => {
      setBusy(true); setFormError(''); void client.create(form).then((a) => { setOpen(false); navigate(a.id); setRefresh((v) => v + 1); setForm({ source: '', count: 50, group: '', notes: '' }); }).catch((e) => setFormError(documentError(e))).finally(() => setBusy(false));
    }}><div className="douyin-form">
      <label>主页链接或分享文本<Input.TextArea aria-label="主页链接或分享文本" value={form.source} rows={3} maxLength={4000} onChange={(e) => setForm({ ...form, source: e.target.value })} /></label>
      <label>采集数量<Select aria-label="采集数量" value={form.count} options={[20, 50, 100].map((value) => ({ value, label: `${value} 条` }))} onChange={(value) => setForm({ ...form, count: value })} /></label>
      <label>分组<Input aria-label="分组" value={form.group} maxLength={100} onChange={(e) => setForm({ ...form, group: e.target.value })} /></label>
      <label>备注<Input.TextArea aria-label="备注" value={form.notes} maxLength={5000} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
      {formError && <Alert type="error" message={formError} />}
    </div></Modal>
  </main>;
}

export default function DouyinBenchmarkPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((s) => s.currentOrganizationId);
  const userId = useAuthStore((s) => s.user?.id);
  if (!applicationId || !organizationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <DouyinHome key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/douyin-benchmark`} />;
}

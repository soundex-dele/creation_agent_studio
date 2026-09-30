import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Input, Modal, Pagination, Select, Spin, Tabs } from 'antd';
import { ArrowLeft, ArrowRight, ArrowUpRight, Clapperboard, FolderOpen, LockKeyhole, Plus, ScanSearch, Settings2, UsersRound } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { documentError } from '@/services/documents';
import { douyinApi, type DouyinAccount } from '@/services/douyinBenchmark';
import { DouyinWorkspace } from './douyin/DouyinWorkspace';
import { CollectorSettings } from './douyin/CollectorSettings';
import './DouyinBenchmarkPage.css';
import { ResearchHub } from './douyin/ResearchHub';
import './douyin/ResearchHub.css';

export function DouyinHome({ base }: { base: string }) {
  const client = useMemo(() => douyinApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const accountId = params.get('account');
  const view = params.get('view') || '';
  const setView = (value: string) => setParams(old => { const next = new URLSearchParams(old); next.delete('account'); if (value) next.set('view', value); else next.delete('view'); return next; });
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [connection, setConnection] = useState<{ connected: boolean; message: string } | null>(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(0); const [page, setPage] = useState(1); const [refresh, setRefresh] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false); const [formError, setFormError] = useState('');
  const [form, setForm] = useState({ source: '', count: 50, group: '', notes: '' });
  const navigate = (id: string | null) => setParams((old) => { const next = new URLSearchParams(old); if (id) { next.set('account', id); next.delete('view'); } else { next.delete('account'); next.delete('view'); }  return next; });
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    void client.accounts(page).then((data) => { if (active) { setAccounts(data.results); setCount(data.count); } }).catch((e) => { if (active) setError(documentError(e)); }).finally(() => { if (active) setLoading(false); });
    void client.connection().then((data) => { if (active) setConnection(data); }).catch((e) => { if (active) setConnection({ connected: false, message: documentError(e) }); });
    return () => { active = false; };
  }, [client, page, refresh]);
  return <main className="douyin-host app-scroll-page">
    <header className="douyin-header"><div className="douyin-header-copy">
      {resolveApplicationPresentation(params).showApplicationHeader && <Link className="douyin-back" to="/apps"><ArrowLeft size={14} aria-hidden="true" /> 返回应用</Link>}
      <div className="douyin-title"><span className="douyin-app-mark"><ScanSearch size={26} aria-hidden="true" /></span><div><small>内容研究 · 创作工作台</small><h1>抖音对标助手</h1></div></div>
      <p>找到值得研究的作品，把结构与方法变成你的拍摄脚本。</p>
    </div><div className="douyin-actions douyin-header-actions"><Button icon={<Settings2 size={16} aria-hidden="true" />} onClick={() => setSettingsOpen(true)}>采集设置</Button>{accountId && <Button icon={<UsersRound size={16} aria-hidden="true" />} onClick={() => navigate(null)}>全部账号</Button>}<Button type="primary" icon={<Plus size={16} aria-hidden="true" />} onClick={() => { setOpen(true); setFormError(''); }}>添加对标账号</Button></div></header>
    <Tabs className="douyin-top-nav" activeKey={view || 'research'} onChange={setView} items={[{ key: 'research', label: '对标研究' }, { key: 'ideas', label: '选题库' }, { key: 'create', label: '创作中心' }, { key: 'review', label: '作品复盘' }, { key: 'subscriptions', label: '订阅通知' }]} />
    {!accountId && !view && <div className="douyin-actions"><Button type="primary" onClick={() => setView('research')}>跨账号研究与选题雷达</Button><Button onClick={() => setView('profiles')}>个人创作档案</Button></div>}
    {!accountId && !view && <section className="douyin-intro" aria-label="研究与创作流程">
      <div className="douyin-intro-copy"><span className="douyin-eyebrow">从观察到表达</span><h2>读懂好内容，<br />找到你的创作方向。</h2><p>把值得学习的账号放在一起，<br />从真实作品中积累下一条视频的灵感。</p></div>
      <ol className="douyin-process">
        {[{ icon: UsersRound, title: '收集对标', description: '建立账号库，采集作品样本' }, { icon: ScanSearch, title: '研究内容', description: '拆解口播与画面，核对分析出处' }, { icon: Clapperboard, title: '开始创作', description: '结合自身定位，形成拍摄脚本' }].map(({ icon: Icon, title, description }, index) => <li key={title}><span className="douyin-process-icon"><Icon size={20} aria-hidden="true" /></span><div><span className="douyin-step-number">0{index + 1}</span><h3>{title}</h3><p>{description}</p></div></li>)}
      </ol>
    </section>}
    {connection && <Alert className="douyin-connection" type={connection.connected ? 'success' : 'warning'} showIcon message={connection.message} action={<Button size="small" onClick={() => setRefresh((v) => v + 1)}>检查配置</Button>} />}
    {view ? <ResearchHub base={base} section={view} onSection={setView} openAccount={navigate} /> : accountId ? <DouyinWorkspace key={accountId} client={client} accountId={accountId} onRemoved={() => { navigate(null); setRefresh((v) => v + 1); }} /> : <section className="douyin-panel douyin-library">
      <div className="douyin-section-title"><div><span className="douyin-eyebrow">账号库</span><h2>我的对标账号 {!loading && !error && <span className="douyin-count">{count}</span>}</h2></div><span className="douyin-private"><LockKeyhole size={14} aria-hidden="true" />个人资料与创作历史仅自己可见</span></div>
      {error ? <Alert type="error" message={error} action={<Button onClick={() => setRefresh((v) => v + 1)}>重试</Button>} /> : loading ? <div className="douyin-loading" role="status"><Spin /><span>正在加载对标账号…</span></div> : !accounts.length ? <div className="douyin-empty"><Empty image={<span className="douyin-empty-icon"><UsersRound size={32} aria-hidden="true" /></span>} description={<><h3>你的内容研究，从这里开始</h3><p>添加第一个账号，开始研究选题和内容结构</p></>}><Button type="primary" icon={<Plus size={16} aria-hidden="true" />} onClick={() => { setOpen(true); setFormError(''); }}>添加账号</Button></Empty></div> : <div className="douyin-account-grid">{accounts.map((a) => <button type="button" className="douyin-account-card" key={a.id} onClick={() => navigate(a.id)}><span className="douyin-card-top"><span className="douyin-avatar" aria-hidden="true">{Array.from(a.name || '待')[0]}</span><ArrowUpRight className="douyin-card-arrow" size={20} aria-hidden="true" /></span><strong className="douyin-card-name">{a.name || '待采集账号'}</strong><span className="douyin-card-description">{a.profile.signature || a.notes || '采集作品后查看账号分析'}</span><span className="douyin-card-footer"><span className="douyin-group"><FolderOpen size={14} aria-hidden="true" />{a.group || '未分组'}</span><span className="douyin-card-enter">进入研究<ArrowRight size={14} aria-hidden="true" /></span></span></button>)}</div>}
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

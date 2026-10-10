import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Checkbox, Drawer, Empty, Input, InputNumber, Modal, Select, Spin, Tabs, Tag } from 'antd';
import { Code2, Plus, RefreshCw } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { defaultRepoBrief, repoApi, repoError, repoTerminal, type RepoBrief, type RepoDestination, type RepoDetail, type RepoEvidence, type RepoHandoff, type RepoProject, type RepoReport, type RepoTask } from '@/services/repoExplainer';
import RepoContentEditor from './repo/RepoContentEditor';
import RepoTaskProgress from './repo/RepoTaskProgress';
import './RepoExplainerPage.css';

export default function RepoExplainerPage() {
  const organization = useOrganizationStore(s => s.currentOrganizationId);
  const user = useAuthStore(s => s.user?.id);
  const { applicationId } = useParams();
  return <RepoWorkspace key={`${organization}:${user}:${applicationId}`} organization={organization} applicationId={applicationId} />;
}

function RepoWorkspace({ organization, applicationId }: { organization: string | null; applicationId?: string }) {
  const [params, setParams] = useSearchParams();
  const client = useMemo(() => repoApi(`${tenantApiRoot(organization || '')}/applications/${applicationId}/repo-explainer`), [organization, applicationId]);
  const [projects, setProjects] = useState<RepoProject[]>([]);
  const [archived, setArchived] = useState(false);
  const [projectId, setProjectId] = useState(params.get('project') || '');
  const [detail, setDetail] = useState<RepoDetail>();
  const [tab, setTab] = useState('sources');
  const [name, setName] = useState('');
  const [kind, setKind] = useState('github');
  const [source, setSource] = useState('');
  const [ref, setRef] = useState('');
  const [file, setFile] = useState<File>();
  const [snapshotId, setSnapshotId] = useState('');
  const [analysisId, setAnalysisId] = useState('');
  const [contentId, setContentId] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [brief, setBrief] = useState<RepoBrief>(defaultRepoBrief);
  const [destinations, setDestinations] = useState<RepoDestination[]>([]);
  const [evidence, setEvidence] = useState<RepoEvidence & { text?: string; url?: string }>();
  const [handoff, setHandoff] = useState<RepoHandoff>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const activeProject = useRef(projectId); activeProject.current = projectId;
  const uploadBody = useRef<{ file: File; data: FormData }>();
  const refreshSequence = useRef(0);
  const refreshProjects = useCallback(async () => { setProjects(await client.projects(archived)); }, [client, archived]);
  const refresh = useCallback(async () => {
    if (!projectId) return;
    const sequence = ++refreshSequence.current;
    const result = await client.project(projectId);
    if (activeProject.current === projectId && sequence === refreshSequence.current) setDetail(result);
  }, [client, projectId]);
  const refreshAfterTask = useCallback(() => { void refresh().catch(e => setError(repoError(e))); }, [refresh]);
  useEffect(() => { if (organization) void refreshProjects().catch(e => setError(repoError(e))); }, [organization, refreshProjects]);
  useEffect(() => { void client.destinations().then(setDestinations).catch(e => setError(repoError(e))); }, [client]);
  useEffect(() => {
    setDetail(undefined); setSnapshotId(''); setAnalysisId(''); setContentId(''); setSelected([]); setHandoff(undefined);
    if (!projectId) return;
    setLoading(true); void refresh().catch(e => setError(repoError(e))).finally(() => setLoading(false));
  }, [projectId, refresh]);
  const hasActiveTasks = detail?.tasks.some(t => !repoTerminal(t.status)) || false;
  useEffect(() => {
    if (!hasActiveTasks) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await refresh(); } catch (e) { if (!stopped) setError(repoError(e)); }
      if (!stopped) timer = setTimeout(() => void poll(), 2500);
    };
    timer = setTimeout(() => void poll(), 2500);
    return () => { stopped = true; clearTimeout(timer); };
  }, [hasActiveTasks, refresh]);
  const snapshot = detail?.snapshots.find(s => s.id === snapshotId) || detail?.snapshots[0];
  const analyses = detail?.tasks.filter(t => t.kind === 'analyze' && t.status === 'succeeded') || [];
  const analysis = analysisId ? analyses.find(t => t.id === analysisId) : analyses[0];
  const report = analysis?.output as RepoReport | undefined;
  const content = detail?.contents.find(c => c.id === contentId) || detail?.contents[0];
  useEffect(() => { setHandoff(undefined); }, [content?.id]);
  useEffect(() => {
    if (!analysisId && analysis?.id) { setAnalysisId(analysis.id); setSelected([]); }
  }, [analysisId, analysis?.id]);
  const selectProject = (id: string) => { if (editing) return; setProjectId(id); const next = new URLSearchParams(params); next.set('project', id); setParams(next, { replace: true }); };
  async function act(work: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError('');
    try { await work(); await refresh(); } catch (e) { setError(repoError(e)); } finally { setBusy(false); }
  }
  const selectAnalysis = (id: string) => { setAnalysisId(id); setSelected([]); };
  const trackTask = (task: RepoTask) => {
    if (activeProject.current !== projectId) return;
    setDetail(current => current && current.id === projectId ? {
      ...current, tasks: [task, ...current.tasks.filter(t => t.id !== task.id)],
    } : current);
  };
  const create = () => act(async () => { const p = await client.create(name.trim()); await refreshProjects(); selectProject(p.id); setName(''); });
  const importSource = () => act(async () => {
    let body: FormData | Record<string, string> = { kind, ...(kind === 'github' ? { url: source, ref } : { path: source }) };
    if (kind === 'zip') {
      if (!file) throw new Error('请选择源码 ZIP 文件');
      if (uploadBody.current?.file !== file) { const data = new FormData(); data.append('kind', 'zip'); data.append('file', file); uploadBody.current = { file, data }; }
      body = uploadBody.current.data;
    }
    trackTask(await client.import(projectId, body));
  });
  async function showEvidence(id: string) {
    if (!analysis || !report?.evidence[id]) return;
    const row = report.evidence[id]; setEvidence(row);
    try {
      const full = await client.evidence(projectId, analysis.snapshot_id, row.path);
      setEvidence(old => old?.id === row.id ? { ...row, text: full.text, url: full.source_url ? `${full.source_url}#L${row.start}-L${row.end}` : undefined } : old);
    } catch (e) { setError(repoError(e)); }
  }
  const statuses = { documented: '文档描述', implemented: '找到实现依据', unconfirmed: '尚待确认' };
  const taskList = detail?.tasks.filter((t, index) => !repoTerminal(t.status) || index === 0 || (t.status === 'failed' && index < 6));
  return <div className="repo-page app-scroll-page"><div className="repo-inner">
    <header className="repo-heading"><div><span className="repo-eyebrow"><Code2 size={16} aria-hidden="true" /> SOURCE TO STORY</span><h1>仓库解读助手</h1><p>从源码证据出发，把工具功能变成值得分享的内容。</p></div><Button icon={<RefreshCw size={16} />} onClick={() => void act(refreshProjects)}>刷新</Button></header>
    {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
    <section className="repo-card"><div className="repo-project-controls">
      <label className="repo-field">当前项目<Select aria-label="当前项目" placeholder="选择项目" value={projectId || undefined} disabled={editing} onChange={selectProject} options={projects.map(p => ({ value: p.id, label: p.title }))} /></label>
      <label className="repo-field" htmlFor="repo-project-name">新项目名称<Input id="repo-project-name" value={name} onChange={e => setName(e.target.value)} placeholder="例如：AI 文档问答工具" maxLength={200} /></label>
      <Button type="primary" icon={<Plus size={16} aria-hidden="true" />} disabled={!name.trim() || busy || editing} onClick={() => void create()}>创建项目</Button>
    </div><div className="repo-actions"><Checkbox checked={archived} onChange={e => setArchived(e.target.checked)}>查看归档</Checkbox>
      {detail && <Button disabled={editing || busy} onClick={() => void act(async () => { await client.update(projectId, { archived: !detail.archived }); await refreshProjects(); })}>{detail.archived ? '恢复项目' : '归档项目'}</Button>}
      {detail && <Button disabled={editing || busy} onClick={() => {
        let title = detail.title;
        Modal.confirm({ title: '修改项目名称', content: <Input aria-label="项目名称" defaultValue={title} maxLength={200} onChange={e => { title = e.target.value; }} />,
          onOk: async () => { if (!title.trim()) throw new Error('请输入项目名称'); await client.update(projectId, { title: title.trim() }); await refresh(); await refreshProjects(); } });
      }}>重命名</Button>}
      {editing && <small>正在编辑，请等待保存或处理保存错误后切换项目。</small>}</div></section>
    {loading && <Spin />}
    {!projectId && <Empty description="创建一个项目，导入你准备介绍的工具仓库" />}
    {detail && <>
      {taskList?.map(task => <RepoTaskProgress key={task.id} task={task} organization={organization || ''} busy={busy}
        onSettled={refreshAfterTask} onCancel={() => void act(() => client.cancel(projectId, task.id))} />)}
      <Tabs activeKey={tab} onChange={value => { if (!editing) setTab(value); }} items={[
        { key: 'sources', label: '仓库资料', children: <section className="repo-stack">
          <div className="repo-card"><h2>导入源码快照</h2><p>只读取文件，不安装或运行仓库。重新导入会创建新快照。</p>
            <div className="repo-grid"><label className="repo-field">来源<Select value={kind} onChange={setKind} options={[{ value: 'github', label: '公开 GitHub' }, { value: 'zip', label: '源码 ZIP' }, { value: 'local', label: '服务端本地仓库' }]} /></label>
              {kind === 'zip' ? <label className="repo-field">源码 ZIP<input type="file" accept=".zip" onChange={e => setFile(e.target.files?.[0])} /></label> : <label className="repo-field">{kind === 'github' ? '仓库链接' : '服务端仓库路径'}<Input value={source} onChange={e => setSource(e.target.value)} placeholder={kind === 'github' ? 'https://github.com/owner/repo' : '执行服务器可访问的 Git 仓库目录'} /></label>}
            </div>{kind === 'github' && <label className="repo-field">分支、标签或提交（可选）<Input value={ref} onChange={e => setRef(e.target.value)} placeholder="留空使用默认分支" /></label>}
            {kind === 'local' && <p>包含未提交修改及未忽略的新文件。这里不是手机或浏览器所在设备的路径。</p>}
            <Button type="primary" loading={busy} disabled={kind === 'zip' ? !file : !source.trim()} onClick={() => void importSource()}>导入并保存快照</Button></div>
          <label className="repo-field">历史快照<Select aria-label="历史快照" value={snapshot?.id} onChange={setSnapshotId} options={detail.snapshots.map(s => ({ value: s.id, label: `${new Date(s.created_at).toLocaleString()} · ${s.origin.kind} · ${s.status}` }))} /></label>
          {snapshot && <div className="repo-card"><h3>{snapshot.origin.url || snapshot.origin.path || snapshot.origin.filename}</h3><p>状态：{snapshot.status} · 提交：{snapshot.origin.commit || '无 Git 提交信息'}</p><p>快照哈希：{snapshot.digest || '等待导入'}</p>
            {snapshot.error && <Alert type="error" message={snapshot.error} />}<p>已纳入 {snapshot.coverage.files_included || 0} 个文本文件 · 所有结论均为静态分析</p>
            <details><summary>排除内容与读取说明</summary>{snapshot.coverage.notes?.map(n => <p key={n}>{n}</p>)}<ul>{snapshot.coverage.excluded?.map(s => <li key={s.path}>{s.path}：{s.reason}</li>)}</ul></details>
            <Button type="primary" disabled={snapshot.status !== 'ready' || busy} onClick={() => void act(async () => { trackTask(await client.task(projectId, { kind: 'analyze', snapshot_id: snapshot.id })); setTab('analysis'); })}>分析此版本功能</Button></div>}
        </section> },
        { key: 'analysis', label: '功能解读', children: <section className="repo-stack">
          <label className="repo-field">分析版本<Select aria-label="分析版本" value={analysis?.id} onChange={selectAnalysis} options={analyses.map((t, i) => ({ value: t.id, label: `分析 ${analyses.length - i} · 快照 ${t.snapshot_id.slice(0, 8)}` }))} /></label>
          {!report && <Empty description={analysisId ? '所选分析已不可用，请重新选择分析版本' : '导入快照后开始分析，完成的功能报告会显示在这里'} />}
          {report && <><div className="repo-card"><h2>{report.summary}</h2><p>适合：{report.audience}</p><p>已读取 {report.coverage.files_read}/{report.coverage.files_total} 个文件、{report.coverage.chunks_read}/{report.coverage.chunks_total} 个片段。{report.coverage.note}</p>
            {[['使用流程', report.workflow], ['部署条件', report.deployment], ['限制', report.limitations]].map(([label, rows]) => <details key={String(label)}><summary>{label}</summary><ul>{(rows as string[]).map((s, i) => <li key={i}>{s}</li>)}</ul></details>)}</div>
            {report.features.map(f => <article className="repo-card" key={f.id}><div className="repo-actions"><Checkbox checked={selected.includes(f.id)} onChange={e => setSelected(v => e.target.checked ? [...v, f.id] : v.filter(id => id !== f.id))}>用于创作</Checkbox><Tag>{statuses[f.status]}</Tag><h3>{f.title}</h3></div><p>{f.description}</p>
              <dl>{[['场景', f.scenario], ['入口', f.entry], ['前置条件', f.requirements], ['限制', f.limitations], ['差异或缺口', f.discrepancies]].filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
              <div className="repo-actions">{f.evidence_ids.map(id => <Button key={id} onClick={() => void showEvidence(id)}>{id} · 查看源码依据</Button>)}</div></article>)}
            <div className="repo-actions repo-workflow-actions">
              <span>已选 {selected.length} 项功能</span>
              <Button type="primary" disabled={!selected.length} onClick={() => setTab('content')}>用已选 {selected.length} 项功能创作</Button>
            </div></>}
        </section> },
        { key: 'content', label: '内容创作', children: <section className="repo-stack">
          <div className="repo-card"><h2>创作要求</h2><p>已选 {selected.length} 项功能。每次生成独立文案，保留已有版本。</p><div className="repo-grid">
            <label className="repo-field">介绍角度<Select value={brief.angle} onChange={angle => setBrief({ ...brief, angle })} options={[{ value: 'overview', label: '工具速览' }, { value: 'feature', label: '单功能介绍' }, { value: 'tutorial', label: '场景教程' }]} /></label>
            <label className="repo-field">文案类型<Select aria-label="文案类型" value={brief.output} onChange={output => setBrief({ ...brief, output })} options={[{ value: 'video', label: '视频文案' }, { value: 'image_text', label: '图文文案' }]} /></label>
            <label className="repo-field">面向人群<Input value={brief.audience} onChange={e => setBrief({ ...brief, audience: e.target.value })} /></label>
            <label className="repo-field">表达风格<Input value={brief.style} onChange={e => setBrief({ ...brief, style: e.target.value })} /></label>
            {brief.output === 'video' && <><label className="repo-field">目标时长（秒）<InputNumber min={5} max={600} value={brief.duration} onChange={duration => setBrief({ ...brief, duration: duration || 60 })} /></label>
            <label className="repo-field">制作画幅<Select value={brief.aspect} onChange={aspect => setBrief({ ...brief, aspect })} options={['16:9', '9:16', '1:1'].map(value => ({ value }))} /></label></>}
          </div><p>{brief.output === 'video' ? '使用 write-short-video-copy 生成口播文案；保存后可交给动画制作或文案转剪映设计分镜。' : '使用 write-image-text-copy 生成图文文案；完成后可编辑和导出。'}</p><Button type="primary" disabled={!analysis || !selected.length || busy || editing} onClick={() => void act(async () => { trackTask(await client.task(projectId, { ...brief, kind: 'write', analysis_id: analysis?.id, feature_ids: selected })); })}>生成文案</Button></div>
          <label className="repo-field">内容作品<Select aria-label="内容作品" disabled={editing} value={content?.id} onChange={setContentId} options={detail.contents.map(c => ({ value: c.id, label: c.title }))} /></label>
          {content && <RepoContentEditor key={`${projectId}:${content.id}`} initial={content} client={client} projectId={projectId} destinations={destinations} onDirty={setEditing} onHandoff={h => { setHandoff(h); void refresh(); }} />}
          {handoff && <Alert type="success" message={handoff.status} description={<a href={handoff.url}>打开制作页，检查内容与参数</a>} />}
        </section> },
        { key: 'production', label: '制作记录', children: <section className="repo-stack">{!detail.handoffs.length && <Empty description="文案保存后可带稿进入制作应用" />}{detail.handoffs.map(h => <article className="repo-card" key={h.id}><h3>{h.kind === 'animation' ? '动画制作' : '文案转剪映'}</h3><p>{h.status} · {new Date(h.created_at).toLocaleString()}</p><p>固定文案版本 {h.version_id.slice(0, 8)}</p><a href={h.url}>重新打开制作页</a></article>)}</section> },
      ]} />
    </>}
    <Drawer title="快照源码证据" open={Boolean(evidence)} onClose={() => setEvidence(undefined)} width="min(900px, 100vw)">
      {evidence && <><p>{evidence.path} · L{evidence.start}–L{evidence.end}</p>{evidence.url && <a href={evidence.url} target="_blank" rel="noreferrer">查看 GitHub 固定提交</a>}<pre className="repo-code">{evidence.quote}</pre><details><summary>完整文件</summary><pre className="repo-code">{evidence.text || '载入中…'}</pre></details></>}
    </Drawer>
  </div></div>;
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Checkbox, Drawer, Empty, Input, InputNumber, Modal, Select, Spin, Tabs, Tag } from 'antd';
import { Code2, Plus, RefreshCw } from 'lucide-react';
import { useOrganizationStore } from '@platform/organization';
import { useAuthStore } from '@platform/auth';
import { tenantApiRoot } from '@platform/tenant';
import { defaultRepoBrief, repoApi, repoError, repoTerminal, type RepoBrief, type RepoDestination, type RepoDetail, type RepoEvidence, type RepoHandoff, type RepoProject, type RepoReport, type RepoTask } from '../services/repoExplainer';
import RepoContentEditor from './repo/RepoContentEditor';
import RepoTaskProgress from './repo/RepoTaskProgress';
import RepoTopicCards from './repo/RepoTopicCards';
import { repoWorkflowEditorPath } from '@platform/pages/Workflows/repoWorkflowSource';
import './RepoExplainerPage.css';

export default function RepoExplainerPage() {
  const organization = useOrganizationStore(s => s.currentOrganizationId);
  const user = useAuthStore(s => s.user?.id);
  const { applicationId } = useParams();
  return <RepoWorkspace key={`${organization}:${user}:${applicationId}`} organization={organization} applicationId={applicationId} />;
}

function RepoWorkspace({ organization, applicationId }: { organization: string | null; applicationId?: string }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const client = useMemo(() => repoApi(`${tenantApiRoot(organization || '')}/applications/${applicationId}/repo-explainer`), [organization, applicationId]);
  const [projects, setProjects] = useState<RepoProject[]>([]);
  const [archived, setArchived] = useState(false);
  const projectId = params.get('project') || '';
  const topicTaskId = params.get('topics') || '';
  const topicId = params.get('topic') || '';
  const updateParams = (values: Record<string, string>) => setParams(current => {
    const next = new URLSearchParams(current);
    Object.entries(values).forEach(([key, value]) => { if (value) next.set(key, value); else next.delete(key); });
    return next;
  }, { replace: true });
  const [detail, setDetail] = useState<RepoDetail>();
  const tab = params.get('view') || 'sources';
  const setTab = (view: string) => updateParams({ view });
  const [name, setName] = useState('');
  const [kind, setKind] = useState('github');
  const [source, setSource] = useState('');
  const [ref, setRef] = useState('');
  const [file, setFile] = useState<File>();
  const snapshotId = params.get('snapshot') || '';
  const setSnapshotId = (snapshot: string) => { updateParams({ snapshot, topics: '', topic: '' }); setEvidence(undefined); };
  const [direction, setDirection] = useState('');
  const [pinnedTask, setPinnedTask] = useState<RepoTask>();
  const [topicError, setTopicError] = useState('');
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
    setDetail(undefined); setAnalysisId(''); setContentId(''); setSelected([]); setHandoff(undefined); setEvidence(undefined); setDirection(''); setBrief(defaultRepoBrief);
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
  const needsPinnedTask = Boolean(detail && topicTaskId && !detail.tasks.some(task => task.id === topicTaskId));
  useEffect(() => {
    setPinnedTask(undefined); setTopicError('');
    if (!needsPinnedTask) return;
    let stopped = false;
    void client.getTask(projectId, topicTaskId).then(task => { if (!stopped) setPinnedTask(task); })
      .catch(e => { if (!stopped) setTopicError(repoError(e)); });
    return () => { stopped = true; };
  }, [client, projectId, topicTaskId, needsPinnedTask]);
  const tasks = pinnedTask && !detail?.tasks.some(task => task.id === pinnedTask.id) ? [...(detail?.tasks || []), pinnedTask] : detail?.tasks || [];
  const topicTask = tasks.find(task => task.id === topicTaskId && task.kind === 'topics');
  const snapshot = snapshotId ? detail?.snapshots.find(s => s.id === snapshotId)
    : detail?.snapshots.find(s => s.id === topicTask?.snapshot_id) || detail?.snapshots[0];
  const topicBatches = tasks.filter(task => task.kind === 'topics' && task.snapshot_id === snapshot?.id && task.status === 'succeeded');
  const validTopicTask = topicTask?.status === 'succeeded' && topicTask.snapshot_id === snapshot?.id ? topicTask : undefined;
  const topic = validTopicTask?.output.topics?.find(row => row.id === topicId);
  const topicAudience = topic?.audience;
  const batchDirection = topicTask ? String(topicTask.options.direction || '') : undefined;
  useEffect(() => {
    if (topicAudience !== undefined) setBrief(current => ({ ...current, audience: topicAudience }));
  }, [topic?.id, topicAudience, validTopicTask?.id]);
  useEffect(() => {
    if (batchDirection !== undefined) setDirection(batchDirection);
  }, [topicTask?.id, batchDirection]);
  const analyses = detail?.tasks.filter(t => t.kind === 'analyze' && t.status === 'succeeded') || [];
  const analysis = analysisId ? analyses.find(t => t.id === analysisId) : analyses[0];
  const report = analysis?.output as RepoReport | undefined;
  const content = detail?.contents.find(c => c.id === contentId) || detail?.contents[0];
  useEffect(() => { setHandoff(undefined); }, [content?.id]);
  useEffect(() => {
    if (!analysisId && analysis?.id) { setAnalysisId(analysis.id); setSelected([]); }
  }, [analysisId, analysis?.id]);
  const selectProject = (id: string) => { if (editing) return; updateParams({ project: id, snapshot: '', topics: '', topic: '', view: 'sources' }); };
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
  async function showEvidence(id: string, sourceTask = analysis) {
    if (!sourceTask?.output.evidence?.[id]) return;
    const row = sourceTask.output.evidence[id]; setEvidence(row);
    try {
      const full = await client.evidence(projectId, sourceTask.snapshot_id, row.path);
      setEvidence(old => activeProject.current === projectId && old === row ? { ...row, text: full.text, url: full.source_url ? `${full.source_url}#L${row.start}-L${row.end}` : undefined } : old);
    } catch (e) { setError(repoError(e)); }
  }
  const statuses = { documented: '文档描述', implemented: '找到实现依据', unconfirmed: '尚待确认' };
  const taskList = detail?.tasks.filter((t, index) => !repoTerminal(t.status) || index === 0 || (t.status === 'failed' && index < 6));
  return <div className="repo-page app-scroll-page"><div className="repo-inner">
    <header className="repo-heading"><div><span className="repo-eyebrow"><Code2 size={16} aria-hidden="true" /> SOURCE TO STORY</span><h1>仓库解读助手</h1><p>导入仓库，发现选题，再把源码依据写成值得分享的文案。</p></div><Button icon={<RefreshCw size={16} />} onClick={() => void act(refreshProjects)}>刷新</Button></header>
    {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
    <section className="repo-card"><div className="repo-project-controls">
      <label className="repo-field">当前项目<Select aria-label="当前项目" placeholder="选择项目" value={projectId || undefined} disabled={editing || busy} onChange={selectProject} options={projects.map(p => ({ value: p.id, label: p.title }))} /></label>
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
      <Tabs activeKey={tab} onChange={value => { if (!editing && !busy) setTab(value); }} items={[
        { key: 'sources', label: '仓库资料', children: <section className="repo-stack">
          <div className="repo-card"><h2>导入源码快照</h2><p>只读取文件，不安装或运行仓库。重新导入会创建新快照。</p>
            <div className="repo-grid"><label className="repo-field">来源<Select value={kind} onChange={setKind} options={[{ value: 'github', label: '公开 GitHub' }, { value: 'zip', label: '源码 ZIP' }, { value: 'local', label: '服务端本地仓库' }]} /></label>
              {kind === 'zip' ? <label className="repo-field">源码 ZIP<input type="file" accept=".zip" onChange={e => setFile(e.target.files?.[0])} /></label> : <label className="repo-field">{kind === 'github' ? '仓库链接' : '服务端仓库路径'}<Input value={source} onChange={e => setSource(e.target.value)} placeholder={kind === 'github' ? 'https://github.com/owner/repo' : '执行服务器可访问的 Git 仓库目录'} /></label>}
            </div>{kind === 'github' && <label className="repo-field">分支、标签或提交（可选）<Input value={ref} onChange={e => setRef(e.target.value)} placeholder="留空使用默认分支" /></label>}
            {kind === 'local' && <p>包含未提交修改及未忽略的新文件。这里不是手机或浏览器所在设备的路径。</p>}
            <Button type="primary" loading={busy} disabled={kind === 'zip' ? !file : !source.trim()} onClick={() => void importSource()}>导入并保存快照</Button></div>
          <label className="repo-field">历史快照<Select aria-label="历史快照" value={snapshot?.id} disabled={editing || busy} onChange={setSnapshotId} options={detail.snapshots.map(s => ({ value: s.id, label: `${new Date(s.created_at).toLocaleString()} · ${s.origin.kind} · ${s.status}` }))} /></label>
          {snapshot && <div className="repo-card"><h3>{snapshot.origin.url || snapshot.origin.path || snapshot.origin.filename}</h3><p>状态：{snapshot.status} · 提交：{snapshot.origin.commit || '无 Git 提交信息'}</p><p>快照哈希：{snapshot.digest || '等待导入'}</p>
            {snapshot.error && <Alert type="error" message={snapshot.error} />}<p>已纳入 {snapshot.coverage.files_included || 0} 个文本文件 · 所有结论均为静态分析</p>
            <details><summary>排除内容与读取说明</summary>{snapshot.coverage.notes?.map(n => <p key={n}>{n}</p>)}<ul>{snapshot.coverage.excluded?.map(s => <li key={s.path}>{s.path}：{s.reason}</li>)}</ul></details>
            <div className="repo-actions"><Button type="primary" disabled={snapshot.status !== 'ready' || busy} onClick={() => { updateParams({ snapshot: snapshot.id, view: 'topics' }); }}>从此快照策划选题</Button>
            <Button disabled={snapshot.status !== 'ready' || busy} onClick={() => void act(async () => { trackTask(await client.task(projectId, { kind: 'analyze', snapshot_id: snapshot.id })); setTab('analysis'); })}>分析此版本功能（可选）</Button></div></div>}
        </section> },
        { key: 'topics', label: '选题策划', children: <section className="repo-stack">
          <div className="repo-card"><h2>从仓库发现值得分享的选题</h2>{snapshotId && !snapshot && <Alert type="error" message="所选源码快照不可用，请重新选择。" />}<p>无需先解析功能。填写方向可聚焦某类话题，留空则推荐不同角度。</p>
            <label className="repo-field">源码快照<Select aria-label="选题源码快照" value={snapshot?.id} disabled={busy || editing} onChange={setSnapshotId}
              options={detail.snapshots.map(s => ({ value: s.id, label: `${new Date(s.created_at).toLocaleString()} · ${s.origin.kind} · ${s.status}` }))} /></label>
            <label className="repo-field" htmlFor="repo-topic-direction">限定方向（可选）<Input.TextArea id="repo-topic-direction" value={direction} maxLength={2000} showCount autoSize={{ minRows: 3, maxRows: 8 }}
              placeholder="例如：面向普通用户的 AI 效率工具，重点介绍实际使用场景" onChange={e => setDirection(e.target.value)} /></label>
            <Button type="primary" disabled={!snapshot || snapshot.status !== 'ready' || busy || editing} onClick={() => void act(async () => {
              if (!snapshot) return;
              const task = await client.task(projectId, { kind: 'topics', snapshot_id: snapshot.id, direction: direction.trim() });
              trackTask(task);
              if (activeProject.current === projectId && !topicId) updateParams({ snapshot: snapshot.id, topics: task.id, topic: '' });
            })}>生成 5 个选题</Button><p>重新生成会保留历史批次和已选选题。</p>
          </div>
          <label className="repo-field">历史选题批次<Select aria-label="历史选题批次" value={topicTaskId || undefined} disabled={editing || busy} placeholder="选择一批已完成的选题"
            onChange={id => { updateParams({ topics: id, topic: '' }); const batch = topicBatches.find(t => t.id === id); setDirection(String(batch?.options.direction || '')); }}
            options={[...topicBatches.map(t => ({ value: t.id, label: `${new Date(t.created_at || '').toLocaleString()} · ${t.options.direction || '不限方向'}` })),
              ...(topicTaskId && !topicBatches.some(t => t.id === topicTaskId) ? [{ value: topicTaskId, label: topicTask && !repoTerminal(topicTask.status) ? '选题生成中…' : '所选批次不可用', disabled: true }] : [])]} /></label>
          {topicError && <Alert type="error" message={`选题批次不可用：${topicError}`} />}
          {topicTaskId && !validTopicTask && !topicError && <Alert type="info" message={topicTask && !repoTerminal(topicTask.status) ? '选题正在生成，完成后会显示在这里。' : '所选选题批次尚未成功完成或与当前快照不匹配，请重新选择。'} />}
          <RepoTopicCards task={validTopicTask} selectedId={topicId} disabled={busy || editing}
            onEvidence={id => void showEvidence(id, validTopicTask)} onSelect={row => {
              if (!validTopicTask) return;
              setBrief(current => ({ ...current, audience: row.audience }));
              updateParams({ topics: validTopicTask.id, topic: row.id, snapshot: validTopicTask.snapshot_id, view: 'content' });
            }} />
        </section> },
        { key: 'content', label: '内容创作', children: <section className="repo-stack">
          <div className="repo-card"><h2>创作要求</h2>
            {topic ? <div className="repo-selected-topic"><h3>{topic.title}</h3><p>{topic.angle}</p><ol>{topic.outline.map((item, index) => <li key={index}>{item}</li>)}</ol>
              <p>选题来源：快照 {validTopicTask?.snapshot_id.slice(0, 8)} · {String(validTopicTask?.options.direction || '不限方向')}</p>
              <Button disabled={editing} onClick={() => setTab('topics')}>更换选题</Button></div>
              : <Alert type="info" message={topicId ? '所选选题不可用，请返回选题策划重新选择。' : '请先生成选题并选择一个选题，再编写文案。'} action={<Button disabled={editing} onClick={() => setTab('topics')}>前往选题策划</Button>} />}
            <p>每次生成独立文案，保留已有版本。</p><div className="repo-grid">
            <label className="repo-field">文案类型<Select aria-label="文案类型" value={brief.output} onChange={output => setBrief({ ...brief, output })} options={[{ value: 'video', label: '视频文案' }, { value: 'image_text', label: '图文文案' }]} /></label>
            <label className="repo-field">面向人群<Input value={brief.audience} onChange={e => setBrief({ ...brief, audience: e.target.value })} /></label>
            <label className="repo-field">表达风格<Input value={brief.style} onChange={e => setBrief({ ...brief, style: e.target.value })} /></label>
            {brief.output === 'video' && <><label className="repo-field">目标时长（秒）<InputNumber min={5} max={600} value={brief.duration} onChange={duration => setBrief({ ...brief, duration: duration || 60 })} /></label>
            <label className="repo-field">制作画幅<Select value={brief.aspect} onChange={aspect => setBrief({ ...brief, aspect })} options={['16:9', '9:16', '1:1'].map(value => ({ value }))} /></label></>}
          </div><p>{brief.output === 'video' ? '使用 write-short-video-copy 生成口播文案；保存后可交给动画制作或文案转剪映设计分镜。' : '使用 write-image-text-copy 生成图文文案；完成后可编辑和导出。'}</p><Button type="primary" disabled={!topic || busy || editing} onClick={() => void act(async () => { trackTask(await client.task(projectId, { ...brief, kind: 'write', topic_task_id: validTopicTask?.id, topic_id: topic?.id })); })}>生成文案</Button></div>
          <label className="repo-field">内容作品<Select aria-label="内容作品" disabled={editing} value={content?.id} onChange={setContentId} options={detail.contents.map(c => ({ value: c.id, label: c.title }))} /></label>
          {content && <RepoContentEditor key={`${projectId}:${content.id}`} initial={content} client={client} projectId={projectId} destinations={destinations} onDirty={setEditing} onHandoff={h => { setHandoff(h); void refresh(); }} />}
          {handoff && <Alert type="success" message={handoff.status} description={<a href={handoff.url}>打开制作页，检查内容与参数</a>} />}
        </section> },
        { key: 'analysis', label: '功能解读', children: <section className="repo-stack">
          <label className="repo-field">分析版本<Select aria-label="分析版本" value={analysis?.id} onChange={selectAnalysis} options={analyses.map((t, i) => ({ value: t.id, label: `分析 ${analyses.length - i} · 快照 ${t.snapshot_id.slice(0, 8)}` }))} /></label>
          {!report && <Empty description={analysisId ? '所选分析已不可用，请重新选择分析版本' : '导入快照后开始分析，完成的功能报告会显示在这里'} />}
          {report && <><div className="repo-card"><h2>{report.summary}</h2><p>适合：{report.audience}</p><p>已读取 {report.coverage.files_read}/{report.coverage.files_total} 个文件、{report.coverage.chunks_read}/{report.coverage.chunks_total} 个片段。{report.coverage.note}</p>
            {[['使用流程', report.workflow], ['部署条件', report.deployment], ['限制', report.limitations]].map(([label, rows]) => <details key={String(label)}><summary>{label}</summary><ul>{(rows as string[]).map((s, i) => <li key={i}>{s}</li>)}</ul></details>)}</div>
            {report.features.map(f => <article className="repo-card" key={f.id}><div className="repo-actions"><Checkbox checked={selected.includes(f.id)} onChange={e => setSelected(v => e.target.checked ? [...v, f.id] : v.filter(id => id !== f.id))}>用于工作流素材</Checkbox><Tag>{statuses[f.status]}</Tag><h3>{f.title}</h3></div><p>{f.description}</p>
              <dl>{[['场景', f.scenario], ['入口', f.entry], ['前置条件', f.requirements], ['限制', f.limitations], ['差异或缺口', f.discrepancies]].filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
              <div className="repo-actions">{f.evidence_ids.map(id => <Button key={id} onClick={() => void showEvidence(id)}>{id} · 查看源码依据</Button>)}</div></article>)}
            <div className="repo-actions repo-workflow-actions">
              <span>已选 {selected.length} 项功能</span>
              <Button type="primary" disabled={!selected.length || !organization || !applicationId || !analysis || busy || editing}
                onClick={() => {
                  if (!organization || !applicationId || !analysis || !selected.length) return;
                  navigate(repoWorkflowEditorPath({ organizationId: organization, applicationId,
                    projectId, analysisId: analysis.id, featureIds: selected }));
                }}>用总预设制作全套素材</Button>
              <small>进入编辑器后可修改素材和节点；保存后运行，生成文章、图文图片、封面、短视频文案及 builder 脚本。</small>
            </div></>}
        </section> },
        { key: 'production', label: '制作记录', children: <section className="repo-stack">{!detail.handoffs.length && <Empty description="文案保存后可带稿进入制作应用" />}{detail.handoffs.map(h => <article className="repo-card" key={h.id}><h3>{h.kind === 'animation' ? '动画制作' : '文案转剪映'}</h3><p>{h.status} · {new Date(h.created_at).toLocaleString()}</p><p>固定文案版本 {h.version_id.slice(0, 8)}</p><a href={h.url}>重新打开制作页</a></article>)}</section> },
      ]} />
    </>}
    <Drawer title="快照源码证据" open={Boolean(evidence)} onClose={() => setEvidence(undefined)} width="min(900px, 100vw)">
      {evidence && <><p>{evidence.path} · L{evidence.start}–L{evidence.end}</p>{evidence.url && <a href={evidence.url} target="_blank" rel="noreferrer">查看 GitHub 固定提交</a>}<pre className="repo-code">{evidence.quote}</pre><details><summary>完整文件</summary><pre className="repo-code">{evidence.text || '载入中…'}</pre></details></>}
    </Drawer>
  </div></div>;
}

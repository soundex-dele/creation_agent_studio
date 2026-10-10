import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, InputNumber, Select } from 'antd';
import { repoError, type RepoClient, type RepoContent, type RepoDestination, type RepoDocument, type RepoHandoff } from '@/services/repoExplainer';

export default function RepoContentEditor({ initial, client, projectId, destinations, onHandoff, onDirty }: {
  initial: RepoContent; client: RepoClient; projectId: string; destinations: RepoDestination[]; onHandoff: (h: RepoHandoff) => void; onDirty: (dirty: boolean) => void;
}) {
  const [doc, setDoc] = useState(initial.draft);
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState<RepoContent>();
  const [dirty, setDirty] = useState(false);
  const [target, setTarget] = useState<number>();
  useEffect(() => { onDirty(dirty || busy); }, [dirty, busy, onDirty]);
  const current = useRef(doc); const server = useRef(initial); const flight = useRef<Promise<RepoContent>>();
  const stopped = useRef(false); const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const change = (value: RepoDocument) => { current.current = value; setDoc(value); setDirty(true); };
  const save = useCallback(() => {
    if (flight.current) return flight.current;
    if (stopped.current) return Promise.reject(new Error('请先处理保存冲突或重试保存。'));
    if (JSON.stringify(current.current) === JSON.stringify(server.current.draft)) return Promise.resolve(server.current);
    const promise = (async () => {
      if (live.current) { setBusy(true); setError(''); }
      try {
        while (JSON.stringify(current.current) !== JSON.stringify(server.current.draft)) {
          const submitted = current.current;
          const value = await client.save(projectId, initial.id, server.current.revision, submitted);
          server.current = value;
          // Server normalizes review flags; adopt only if the user has not typed again.
          if (current.current === submitted) {
            current.current = value.draft;
            if (live.current) setDoc(value.draft);
          }
          if (live.current) setSaved(value);
        }
        if (live.current) setDirty(false);
        return server.current;
      } catch (e) {
        stopped.current = true;
        if (live.current) {
          setError(repoError(e));
          const value = (e as { response?: { data?: { current?: RepoContent } } }).response?.data?.current;
          if (value) setConflict(value);
        }
        throw e;
      } finally { if (live.current) setBusy(false); flight.current = undefined; }
    })();
    flight.current = promise;
    return promise;
  }, [client, initial.id, projectId]);
  useEffect(() => {
    if (!dirty || stopped.current) return;
    const timer = setTimeout(() => { void save().catch(() => undefined); }, 1000);
    return () => clearTimeout(timer);
  }, [doc, dirty, save]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  async function action(kind: 'download' | 'handoff') {
    try {
      const value = await save();
      if (kind === 'handoff') {
        if (!target) return;
        setBusy(true);
        onHandoff(await client.handoff(projectId, value.versions[0].id, target));
      } else {
        const blob = await client.download(projectId, initial.id);
        const url = URL.createObjectURL(blob); const a = document.createElement('a');
        a.href = url; a.download = `${value.title}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (e) { setError(repoError(e)); } finally { setBusy(false); }
  }
  function resolve(useLocal: boolean) {
    if (!conflict) return;
    server.current = conflict; setSaved(conflict); stopped.current = false; setConflict(undefined); setError('');
    if (useLocal) { void save().catch(() => undefined); }
    else { current.current = conflict.draft; setDoc(conflict.draft); setDirty(false); }
  }
  return <section className="repo-editor">
    <div className="repo-actions"><strong>{busy ? '保存或交接中…' : dirty ? '有未保存修改' : `已保存 · v${saved.revision}`}</strong>
      <Button onClick={() => { stopped.current = false; void save().catch(() => undefined); }} disabled={busy || Boolean(conflict)}>保存 / 重试</Button>
      <Button onClick={() => void action('download')} disabled={busy}>导出 Markdown</Button></div>
    {error && <Alert type="error" message={error} />}
    {conflict && <div className="repo-actions"><Button onClick={() => resolve(true)}>保留本地内容另存新版本</Button><Button onClick={() => resolve(false)}>采用服务器版本</Button></div>}
    <Alert type="info" message="文案需要人工核对；引用有效不代表已实测。手工修改同样标记为待核对。" />
    <label className="repo-field">历史版本<Select aria-label="历史版本" placeholder="选择旧版本复制到当前草稿" disabled={busy} options={saved.versions.map(v => ({ value: v.id, label: `v${v.revision}` }))} onChange={id => { const v = saved.versions.find(x => x.id === id); if (v) change(v.document); }} /></label>
    <div className="repo-grid"><label className="repo-field">作品标题<Input value={doc.title} onChange={e => change({ ...doc, title: e.target.value })} /></label>
      <label className="repo-field">封面短句<Input value={doc.cover} onChange={e => change({ ...doc, cover: e.target.value })} /></label></div>
    <label className="repo-field">画幅<Select value={doc.aspect} options={['16:9', '9:16', '1:1'].map(value => ({ value }))} onChange={aspect => change({ ...doc, aspect })} /></label>
    <h3>视频分镜</h3>
    {doc.scenes.map((scene, i) => <article className="repo-card" key={i}>
      <div className="repo-actions"><strong>分镜 {i + 1} · 待核对</strong><label>预计秒数 <InputNumber aria-label={`分镜 ${i + 1} 秒数`} min={1} max={600} value={scene.seconds} onChange={seconds => change({ ...doc, scenes: doc.scenes.map((s, n) => n === i ? { ...s, seconds: seconds || 1 } : s) })} /></label>
        <Button danger onClick={() => change({ ...doc, scenes: doc.scenes.filter((_, n) => n !== i) })}>删除分镜</Button></div>
      <label className="repo-field">旁白<Input.TextArea autoSize={{ minRows: 3 }} value={scene.narration} onChange={e => change({ ...doc, scenes: doc.scenes.map((s, n) => n === i ? { ...s, narration: e.target.value } : s) })} /></label>
      <label className="repo-field">画面建议<Input.TextArea autoSize={{ minRows: 2 }} value={scene.visual} onChange={e => change({ ...doc, scenes: doc.scenes.map((s, n) => n === i ? { ...s, visual: e.target.value } : s) })} /></label>
      <small>功能：{scene.feature_ids.join('、') || '待补充'} · 证据：{scene.evidence_ids.join('、') || '待补充'}</small>
    </article>)}
    <Button onClick={() => change({ ...doc, scenes: [...doc.scenes, { narration: '', visual: '', seconds: 5, feature_ids: [], evidence_ids: [], needs_review: true }] })}>添加分镜</Button>
    <details><summary>完整口播（由旁白自动组合）</summary><p className="repo-prose">{doc.scenes.map(s => s.narration).join('\n')}</p></details>
    <label className="repo-field">素材准备清单（每行一项）<Input.TextArea value={doc.checklist.join('\n')} onChange={e => change({ ...doc, checklist: e.target.value.split('\n') })} /></label>
    <h3>配套图文</h3>
    <label className="repo-field">图文标题<Input value={doc.article.title} onChange={e => change({ ...doc, article: { ...doc.article, title: e.target.value } })} /></label>
    <label className="repo-field">引言<Input.TextArea value={doc.article.intro} onChange={e => change({ ...doc, article: { ...doc.article, intro: e.target.value } })} /></label>
    {doc.article.sections.map((section, i) => <article className="repo-card" key={i}>
      {(['heading', 'body', 'image'] as const).map((field, n) => <label className="repo-field" key={field}>{['章节标题', '正文', '配图建议'][n]}<Input.TextArea autoSize={{ minRows: field === 'body' ? 4 : 1 }} value={section[field]} onChange={e => change({ ...doc, article: { ...doc.article, sections: doc.article.sections.map((s, k) => k === i ? { ...s, [field]: e.target.value } : s) } })} /></label>)}
      <small>待核对 · 功能：{section.feature_ids.join('、') || '待补充'} · 证据：{section.evidence_ids.join('、') || '待补充'}</small>
    </article>)}
    <div className="repo-card"><h3>带稿进入制作</h3><p>保存当前版本后创建关联草稿。在目标应用补充真实素材、调整参数并启动生成。</p>
      <div className="repo-actions"><Select aria-label="制作应用" placeholder="选择剪映或动画制作" value={target} onChange={setTarget} options={destinations.map(d => ({ value: d.id, label: d.name }))} />
        <Button type="primary" disabled={!target || busy || Boolean(conflict)} onClick={() => void action('handoff')}>创建制作草稿</Button></div>
      {!destinations.length && <p>当前组织没有可使用的制作应用，请检查应用启用状态和权限。</p>}</div>
  </section>;
}

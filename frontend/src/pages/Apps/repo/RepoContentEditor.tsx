import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, InputNumber, Select } from 'antd';
import { isRepoCopy, legacyRepoCopy, repoError, type RepoClient, type RepoContent, type RepoDestination, type RepoDocument, type RepoHandoff } from '@/services/repoExplainer';

export default function RepoContentEditor({ initial, client, projectId, destinations, onHandoff, onDirty }: {
  initial: RepoContent; client: RepoClient; projectId: string; destinations: RepoDestination[]; onHandoff: (h: RepoHandoff) => void; onDirty: (dirty: boolean) => void;
}) {
  const [doc, setDoc] = useState(initial.draft);
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState<RepoContent>();
  const [dirty, setDirty] = useState(false);
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
  async function action(kind: 'download' | 'handoff', target?: number) {
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
    <label className="repo-field">历史版本<Select aria-label="历史版本" placeholder="选择旧版本复制到当前草稿" disabled={busy} options={saved.versions.map(v => ({ value: v.id, label: `v${v.revision}` }))} onChange={id => { const v = saved.versions.find(x => x.id === id); if (v) change(isRepoCopy(saved.draft) && !isRepoCopy(v.document) ? legacyRepoCopy(v.document, saved.draft.kind) : v.document); }} /></label>
    {isRepoCopy(doc) ? <>
      <h3>{doc.kind === 'video' ? '视频文案' : '图文文案'}</h3>
      {doc.skill && <small>写作技能：{doc.skill.slug}</small>}
      <div className="repo-grid"><label className="repo-field">作品标题<Input value={doc.title} onChange={e => change({ ...doc, title: e.target.value })} /></label>
        <label className="repo-field">封面短句<Input value={doc.cover} onChange={e => change({ ...doc, cover: e.target.value })} /></label></div>
      <label className="repo-field">备选标题（每行一项）<Input.TextArea value={doc.alternatives.join('\n')} onChange={e => change({ ...doc, alternatives: e.target.value.split('\n') })} /></label>
      {doc.kind === 'video' && <div className="repo-grid">
        <label className="repo-field">预计时长（秒）<InputNumber aria-label="预计时长" min={5} max={600} value={doc.duration} onChange={duration => change({ ...doc, duration: duration || 60 })} /></label>
        <label className="repo-field">制作画幅<Select value={doc.aspect} options={['16:9', '9:16', '1:1'].map(value => ({ value }))} onChange={aspect => change({ ...doc, aspect })} /></label>
      </div>}
      {doc.paragraphs.map((paragraph, i) => <article className="repo-card" key={i}>
        <div className="repo-actions"><strong>{doc.kind === 'video' ? '段落' : '第'} {i + 1}{doc.kind === 'image_text' ? ' 页文案' : ''} · 待核对</strong>
          <Button danger onClick={() => change({ ...doc, paragraphs: doc.paragraphs.filter((_, n) => n !== i) })}>删除段落</Button></div>
        <label className="repo-field">{doc.kind === 'video' ? '段落备注（不朗读，可留空）' : '页标题'}<Input value={paragraph.heading} onChange={e => change({ ...doc, paragraphs: doc.paragraphs.map((p, n) => n === i ? { ...p, heading: e.target.value } : p) })} /></label>
        <label className="repo-field">{doc.kind === 'video' ? '口播正文' : '上图文字'}<Input.TextArea aria-label={`文案正文 ${i + 1}`} autoSize={{ minRows: 4 }} value={paragraph.text} onChange={e => change({ ...doc, paragraphs: doc.paragraphs.map((p, n) => n === i ? { ...p, text: e.target.value, needs_review: true } : p) })} /></label>
        <small>功能：{paragraph.feature_ids.join('、') || '待补充'} · 证据：{paragraph.evidence_ids.join('、') || '待补充'}</small>
      </article>)}
      <Button onClick={() => change({ ...doc, paragraphs: [...doc.paragraphs, { heading: '', text: '', feature_ids: [], evidence_ids: [], needs_review: true }] })}>添加文案段落</Button>
      {doc.kind === 'video' && <details><summary>完整口播</summary><p className="repo-prose">{doc.paragraphs.map(p => p.text).join('\n\n')}</p></details>}
      <label className="repo-field">发布配文<Input.TextArea autoSize={{ minRows: 3 }} value={doc.publish_copy} onChange={e => change({ ...doc, publish_copy: e.target.value })} /></label>
      <label className="repo-field">待核事项（每行一项）<Input.TextArea value={doc.notes.join('\n')} onChange={e => change({ ...doc, notes: e.target.value.split('\n') })} /></label>
      {doc.kind === 'video' ? <div className="repo-card"><h3>带稿进入制作</h3><p>将当前已保存的完整文案交给制作应用，由目标应用设计分镜。</p>
        <div className="repo-actions">{destinations.map(destination => <Button key={destination.id} type="primary" disabled={busy || Boolean(conflict)} onClick={() => void action('handoff', destination.id)}>
          {destination.slug === 'animation-studio' ? '导入动画制作' : '导入文案转剪映'}</Button>)}</div>
        {!destinations.length && <p>当前组织没有可使用的制作应用，请检查应用启用状态和权限。</p>}</div>
        : <p>图文文案已完成，可继续编辑或导出 Markdown。</p>}
    </> : <div className="repo-card"><h3>历史作品</h3><p>原稿及历史版本已保留。可选择其中一种文案，继续编辑并保存为新版本。</p>
      <div className="repo-actions">{!!doc.scenes.length && <Button onClick={() => change(legacyRepoCopy(doc, 'video'))}>提取视频文案</Button>}
        {!!doc.article.sections.length && <Button onClick={() => change(legacyRepoCopy(doc, 'image_text'))}>提取图文文案</Button>}</div>
      <details><summary>查看原稿</summary><pre className="repo-code">{JSON.stringify(doc, null, 2)}</pre></details>
    </div>}
  </section>;
}

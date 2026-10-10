import { useEffect, useState } from 'react';
import { Alert, Button, Input, Modal, Pagination, Select, Tag } from 'antd';
import { documentError } from '@/services/documents';
import { researchLabels, type CommentRow, type Comparison, type ResearchClient, type ResearchTask, type ResearchVersion, type Variant } from '@/services/douyinResearch';
import { ScriptEditor } from './ScriptEditor';
import { ArticleEditor } from './ArticleEditor';
import { GenerationPreview } from './GenerationPreview';
import { ComparisonTable } from './ResearchLibrary';
import { Field } from './ResearchCommon';
import { ExtractKnowledge, KnowledgeCandidates, KnowledgeReferences } from './CreationKnowledge';

export function ResearchResult({ client, task, run, onDirty }: { client: ResearchClient; task: ResearchTask; run: (body: Record<string, unknown>) => Promise<void>; onDirty?: (value: boolean) => void }) {
  const [starting, setStarting] = useState<number | null>(null);
  const [error, setError] = useState(''); const [saved, setSaved] = useState(''); const [ref, setRef] = useState(''); const [image, setImage] = useState('');
  const [comments, setComments] = useState<CommentRow[]>([]); const [commentPage, setCommentPage] = useState(1); const [commentTotal, setCommentTotal] = useState(0);
  const output = task.output;
  async function action(fn: () => Promise<unknown>) { setError(''); setSaved(''); try { await fn(); setSaved('操作已完成'); } catch (e) { setError(documentError(e)); } }
  useEffect(() => { let alive = true; if (task.kind === 'comments' && output.work_id) void client.comments(output.work_id, commentPage, output.batch_id).then(data => { if (alive) { setComments(data.results); setCommentTotal(data.count); } }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client, task.kind, output.work_id, output.batch_id, commentPage]);
  const evidence = output.evidence?.find(e => e.segments.some(s => s.id === ref) || e.frames.some(f => f.id === ref));
  const segment = evidence?.segments.find(s => s.id === ref) || output.segments?.find(s => s.id === ref);
  const frame = evidence?.frames.find(f => f.id === ref) || output.frames?.find(f => f.id === ref);
  const work = task.sources?.find(s => s.id === ref);
  const comment = output.comments?.find(c => c.id === ref);
  useEffect(() => {
    let alive = true; let url = ''; setImage('');
    if (frame) void client.frame(evidence?.task_id || task.id, frame.id.includes(':') ? frame.id.split(':').slice(1).join(':') : frame.id).then(blob => { url = URL.createObjectURL(blob); if (alive) setImage(url); else URL.revokeObjectURL(url); }).catch(e => { if (alive) setError(documentError(e)); });
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [client, evidence?.task_id, task.id, frame]);
  const saveIdea = (title: string, notes: string) => action(() => client.create('ideas', { title: title.slice(0, 300), notes, source_task: task.id, tags: [] }));
  return <section className="douyin-form">{error && <Alert type="error" message={error} />}{saved && <Alert type="success" message={saved} />}{output.warning && <Alert type="warning" message={output.warning} />}{output.note && <p>{output.note}</p>}
    {output.creation_context?.account_name && <p>创作账号：{output.creation_context.account_name} · 文风 v{output.creation_context.voice_version_number}</p>}
    <GenerationPreview key={task.id} task={task} />
    <ExtractKnowledge task={task} run={run} />
    <KnowledgeReferences cards={output.knowledge_cards} />
    {task.kind === 'knowledge_extract' && task.status === 'succeeded' && <KnowledgeCandidates key={task.id} client={client} task={task} />}
    {task.kind === 'knowledge_extract' && ['failed', 'cancelled'].includes(task.status) && output.source_task_id && <Button onClick={() => void action(() => run({ kind: 'knowledge_extract', source_task_id: output.source_task_id }))}>重试提炼</Button>}
    {task.kind === 'article' && task.status === 'succeeded' && <ArticleEditor key={task.id} client={client} taskId={task.id} onDirty={onDirty} />}
    {output.coverage && <p>最近{output.coverage.days}天，使用 {output.coverage.sampled} / {output.coverage.available} 条已采集作品。{output.baseline && '这是首次基线报告。'}</p>}
    {output.coverage && <details><summary>查看各账号样本覆盖</summary>{output.coverage.accounts.map(a => <p key={a.account_id}>{a.account_name}：{a.sampled} / {a.available}</p>)}</details>}{output.new_topic_note && <p>{output.new_topic_note}</p>}
    {output.topics && <div className="douyin-research-grid">{output.topics.map((topic, i) => <article className="douyin-research-card" key={i}><h3>{topic.title} {topic.is_new && <Tag>新出现主题</Tag>}</h3><p>{topic.angle}</p>{topic.hook && <blockquote>{topic.hook}</blockquote>}{topic.pillar && <p>内容支柱：{topic.pillar}</p>}{topic.reason && <p>适合原因：{topic.reason}</p>}{topic.materials_needed && <p>需要补充：{topic.materials_needed}</p>}{topic.duplicate_note && <p>重复提醒：{topic.duplicate_note}</p>}{topic.sample_count != null && <p>{topic.account_count} 个账号 · {topic.sample_count} 条样本 · 点赞中位数 {topic.median_likes ?? '未获取'}</p>}<div className="douyin-actions"><Button onClick={() => void saveIdea(topic.title, [topic.angle, topic.hook, topic.pillar, topic.reason, topic.materials_needed, topic.duplicate_note].filter(Boolean).join('\n'))}>保存为选题</Button>{task.kind === 'topics' && <><Button type="primary" loading={starting === i} disabled={task.status !== 'succeeded' || starting !== null} onClick={() => { setStarting(i); void action(() => run({ kind: 'article', source_task_id: task.id, topic_index: i })).finally(() => setStarting(null)); }}>开始写作</Button><Button disabled={task.status !== 'succeeded' || starting !== null} onClick={() => void action(() => run({ kind: 'script', source_task_id: task.id, topic_index: i }))}>生成拍摄脚本</Button></>}{topic.refs?.map(id => <Button key={id} onClick={() => setRef(id)}>核对作品 {id.slice(0, 6)}</Button>)}</div></article>)}</div>}
    {output.children?.map(child => <p key={child.task_id}>视频 {child.work_id.slice(0, 8)} · {child.status} {child.error}</p>)}
    {output.claims?.map((claim, i) => <article className="douyin-research-card" key={i}><Tag>{({ observation: '观察事实', inference: '初步推测', suggestion: '创作建议' })[claim.type]}</Tag><p>{claim.text}</p><div className="douyin-actions">{claim.refs.map(id => <Button key={id} onClick={() => setRef(id)}>出处 {id.slice(0, 8)}</Button>)}<Button onClick={() => void saveIdea(claim.text.slice(0, 100), claim.text)}>保存为选题</Button></div></article>)}
    {output.comparison && !Array.isArray(output.comparison) && <ComparisonTable data={output.comparison} />}
    {task.kind === 'comments' && <><p>采集 {output.actual ?? 0} 条评论及回复。</p><Button type="primary" disabled={!commentTotal} onClick={() => void action(() => run({ kind: 'needs', source_task_id: task.id }))}>挖掘评论需求</Button>{comments.map(c => <article key={c.id} className="douyin-research-card"><p>{c.parent_id && <Tag>回复 {c.parent_id}</Tag>}{c.text}</p><small>点赞 {c.likes ?? '未获取'} · 评论 {c.platform_id}</small></article>)}<Pagination current={commentPage} total={commentTotal} pageSize={50} showSizeChanger={false} onChange={setCommentPage} /></>}
    {task.kind === 'variants' && task.status === 'succeeded' && <VariantEditor client={client} task={task} />}
    {task.kind === 'script' && task.status === 'succeeded' && <ScriptEditor client={client.editor} accountId={task.account_id || ''} taskId={task.id} />}
    <Modal className="douyin-modal" open={!!ref} title="核对原始出处" footer={null} onCancel={() => setRef('')}>
      {segment && <><p>{segment.start.toFixed(1)}–{segment.end.toFixed(1)}秒</p><p>{segment.text}</p><Button onClick={() => void action(() => client.create('inspirations', { title: segment.text.slice(0, 100), kind: 'segment', text: segment.text, source_task: evidence?.task_id || task.id, source_ref: segment.id.split(':').pop(), source_time: segment.start, work: evidence?.work_id || task.work_id }))}>收藏片段</Button></>}
      {frame && <><p>{frame.time}秒关键帧</p>{image && <img src={image} className="douyin-evidence-image" alt={`${frame.time}秒关键帧`} />}<Button onClick={() => void action(() => client.create('inspirations', { title: `${frame.time}秒关键帧`, kind: 'frame', source_task: evidence?.task_id || task.id, source_ref: frame.id.split(':').pop(), source_time: frame.time, work: evidence?.work_id || task.work_id }))}>收藏关键帧</Button></>}
      {work && <><h3>{work.title}</h3><p>{work.description}</p><a href={work.url} target="_blank" rel="noreferrer">打开原作品</a></>}
      {comment && <><p>{comment.text}</p><p>评论ID：{comment.platform_id} · 点赞：{comment.likes ?? '未获取'}</p></>}
      {output.comparison && (Array.isArray(output.comparison) ? output.comparison.filter(p => p.id === ref).map(p => <div key={p.id}><h3>{p.work.title}</h3><p>{p.theme} · {p.hook}</p><a href={p.work.url} target="_blank" rel="noreferrer">打开发布作品</a></div>) : (output.comparison as Comparison).accounts.filter(a => a.account_id === ref).map(a => <p key={a.account_id}>{a.name} · 样本 {a.sample_count} 条 · 采集 {a.captured_at}</p>))}
      {!segment && !frame && !work && !comment && !output.comparison && <p>来源 {ref}，当前结果不含可显示的原始片段。</p>}
    </Modal>
  </section>;
}

function VariantEditor({ client, task }: { client: ResearchClient; task: ResearchTask }) {
  const [versions, setVersions] = useState<ResearchVersion[]>([]); const [content, setContent] = useState<{ hooks: Variant[]; titles: Variant[]; covers: Variant[] }>({ hooks: task.output.hooks || [], titles: task.output.titles || [], covers: task.output.covers || [] });
  const [selection, setSelection] = useState({ hook: '', title: '', cover: '' }); const [sourceRevision, setSourceRevision] = useState(0); const [error, setError] = useState(''); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false); const [selectedVersion, setSelectedVersion] = useState('');
  useEffect(() => { let alive = true; void client.versions(task.id).then(v => { if (alive) { setVersions(v); setSelectedVersion(v[0]?.id || ''); if (v[0]) setContent({ hooks: v[0].content.hooks || [], titles: v[0].content.titles || [], covers: v[0].content.covers || [] }); } }).catch(e => { if (alive) setError(documentError(e)); }); if (task.output.source_task_id) void client.versions(task.output.source_task_id).then(v => { if (alive) setSourceRevision(v[0]?.revision || 0); }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client, task.id, task.output.source_task_id]);
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await fn(); setMessage('已保存'); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } }
  return <div className="douyin-form"><h3>候选表达与组合</h3><p>这些表达尚未验证效果。应用开头时会添加到文案开头，请在脚本编辑器检查衔接。</p>{error && <Alert type="error" message={error} />}{message && <Alert type="success" message={message} />}
    <Field label="表达历史版本"><Select aria-label="表达历史版本" value={selectedVersion || undefined} options={versions.map(v => ({ value: v.id, label: `版本${v.revision}` }))} onChange={id => { const version = versions.find(v => v.id === id); if (version) { setSelectedVersion(id); setContent({ hooks: version.content.hooks || [], titles: version.content.titles || [], covers: version.content.covers || [] }); } }} /></Field>
    {(['hooks', 'titles', 'covers'] as const).map(key => <section key={key}><h4>{{ hooks: '开头', titles: '标题', covers: '封面短句' }[key]}</h4><div className="douyin-research-grid">{content[key].map((v, i) => <article key={i} className="douyin-research-card"><Input.TextArea aria-label={`${key}${i + 1}`} rows={3} value={v.text} maxLength={key === 'hooks' ? 3000 : 300} onChange={e => setContent(old => ({ ...old, [key]: old[key].map((item, n) => n === i ? { ...item, text: e.target.value } : item) }))} /><p>{v.angle}</p><div className="douyin-actions"><Button onClick={() => setSelection(old => ({ ...old, [{ hooks: 'hook', titles: 'title', covers: 'cover' }[key]]: v.text }))}>加入组合</Button><Button onClick={() => void action(async () => { await client.create('inspirations', { title: v.text.slice(0, 100), kind: key === 'hooks' ? 'hook' : 'text', text: v.text, source_task: task.id }); })}>收藏</Button></div></article>)}</div></section>)}
    <Button disabled={!versions.length || busy} onClick={() => void action(async () => { const version = await client.saveVersion(task.id, versions[0].revision, content); setVersions([version, ...versions]); setSelectedVersion(version.id); })}>保存候选新版本</Button>
    {(['title', 'cover', 'hook'] as const).map(key => <Field key={key} label={{ title: '组合标题', cover: '组合封面', hook: '组合开头' }[key]}><Input.TextArea aria-label={`组合${key}`} value={selection[key]} maxLength={key === 'hook' ? 3000 : 300} onChange={e => setSelection({ ...selection, [key]: e.target.value })} /></Field>)}
    <Button type="primary" disabled={!sourceRevision || busy || !Object.values(selection).some(Boolean)} onClick={() => void action(async () => { const version = await client.apply(task.id, { ...selection, revision: sourceRevision }); setSourceRevision(version.revision); })}>应用组合并保存脚本新版本</Button>
  </div>;
}

export { researchLabels };

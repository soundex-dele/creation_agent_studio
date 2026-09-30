import { useState } from 'react';
import { Alert, Button, Input, Select, Tabs, Tag } from 'antd';
import { documentError } from '@/services/documents';
import type { Idea, Inspiration, ResearchClient } from '@/services/douyinResearch';
import { DeleteRecord, Field, Pager, RecordEditor, Status, useRows, type EditorField } from './ResearchCommon';

export const ideaStates = { research: '待研究', create: '待创作', shoot: '待拍摄', published: '已发布' };
const fields: EditorField[] = [{ key: 'title', label: '标题' }, { key: 'notes', label: '研究笔记', kind: 'long' }, { key: 'tags', label: '标签（逗号分隔）', kind: 'tags' }];
export function IdeaLibrary({ client, onCreate }: { client: ResearchClient; onCreate: (idea: Idea) => void }) {
  const [tab, setTab] = useState('ideas'); const [search, setSearch] = useState(''); const [tag, setTag] = useState(''); const [sort, setSort] = useState('position'); const [status, setStatus] = useState('');
  const [editing, setEditing] = useState<Idea | Inspiration | Record<string, unknown> | null>(null); const [error, setError] = useState('');
  const rows = useRows<Idea | Inspiration>(client, tab, { search, tag, sort, status });
  async function action(fn: () => Promise<unknown>) { setError(''); try { await fn(); rows.reload(); } catch (e) { setError(documentError(e)); } }
  const move = (idea: Idea, next: string) => action(() => client.update('ideas', idea.id, { revision: idea.revision, status: next }));
  const renderCard = (record: Idea | Inspiration) => <article className="douyin-research-card" key={record.id} draggable={tab === 'ideas'} onDragStart={e => { e.dataTransfer.setData('text/plain', record.id); }}>
    <h3>{record.title}</h3>{record.tags.map(t => <Tag key={t}>{t}</Tag>)}{'text' in record && <p className="douyin-preserve-text">{record.text}</p>}<p className="douyin-preserve-text">{record.notes}</p>
    {'source_ref' in record && record.source_ref && <p>来源片段：{record.source_ref} {record.source_time == null ? '' : `${record.source_time}秒`}</p>}
    {!record.source_task && 'work' in record && !record.work && <small>独立灵感／来源不可用</small>}
    <div className="douyin-actions"><Button onClick={() => setEditing(record)}>编辑</Button>{tab === 'ideas' ? <><Button type="primary" onClick={() => onCreate(record as Idea)}>用此选题创作</Button><Select aria-label={`${record.title}状态`} value={(record as Idea).status} options={Object.entries(ideaStates).map(([value, label]) => ({ value, label }))} onChange={value => void move(record as Idea, value)} /></> : <Button onClick={() => void action(() => client.create('ideas', { title: record.title, notes: `${'text' in record ? record.text : ''}\n${record.notes}`, tags: record.tags, inspiration: record.id }))}>转为选题</Button>}<DeleteRecord client={client} resource={tab} record={record} done={rows.reload} /></div>
  </article>;
  return <section className="douyin-form"><div className="douyin-section-title"><h2>灵感与选题库</h2><Button type="primary" onClick={() => setEditing({ title: '', notes: '', tags: [], ...(tab === 'ideas' ? { status: 'research', position: 0 } : { kind: 'text', text: '' }) })}>新建{tab === 'ideas' ? '选题' : '灵感'}</Button></div>
    <Tabs activeKey={tab} onChange={v => { setTab(v); setEditing(null); setStatus(''); }} items={[{ key: 'ideas', label: '选题看板' }, { key: 'inspirations', label: '灵感收藏' }]} />
    <div className="douyin-research-filters"><Field label="搜索标题或笔记"><Input aria-label="搜索标题或笔记" value={search} onChange={e => setSearch(e.target.value)} /></Field><Field label="筛选标签"><Input aria-label="筛选标签" value={tag} onChange={e => setTag(e.target.value)} /></Field><Field label="排序"><Select aria-label="选题排序" value={sort} onChange={setSort} options={[{ value: 'position', label: '自定义顺序' }, { value: 'updated', label: '最近更新' }]} /></Field>{tab === 'ideas' && <Field label="状态"><Select aria-label="状态筛选" value={status || undefined} allowClear onChange={v => setStatus(v || '')} options={Object.entries(ideaStates).map(([value, label]) => ({ value, label }))} /></Field>}</div>
    {error && <Alert type="error" message={error} />}<Status loading={rows.loading} error={rows.error} empty={!rows.results.length} />
    {tab === 'ideas' ? <div className="douyin-idea-board">{Object.entries(ideaStates).filter(([state]) => !status || status === state).map(([state, label]) => <section key={state} className="douyin-idea-column" aria-label={label} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); const idea = rows.results.find(r => r.id === e.dataTransfer.getData('text/plain')); if (idea) void move(idea as Idea, state); }}><h3>{label}</h3>{rows.results.filter(r => (r as Idea).status === state).map(renderCard)}</section>)}</div> : <div className="douyin-research-grid">{rows.results.map(renderCard)}</div>}<Pager rows={rows} />
    {editing && <RecordEditor title={tab === 'ideas' ? '编辑选题' : '编辑灵感'} initial={editing} fields={[...fields, ...(tab === 'ideas' ? [{ key: 'status', label: '选题状态', kind: 'select' as const, options: Object.entries(ideaStates).map(([value, label]) => ({ value, label })) }, { key: 'position', label: '排序序号', kind: 'number' as const }] : [{ key: 'text', label: '灵感原文', kind: 'long' as const }])]} onClose={() => setEditing(null)} onSave={async values => { if (values.id) await client.update(tab, String(values.id), values); else await client.create(tab, values); rows.reload(); }} />}
  </section>;
}

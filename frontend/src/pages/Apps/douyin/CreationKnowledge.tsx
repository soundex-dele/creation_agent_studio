import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, Button, Checkbox, Drawer, Empty, Input, Popconfirm, Select, Spin, Tag } from 'antd';
import { documentError } from '@/services/documents';
import type { ResearchClient, ResearchTask } from '@/services/douyinResearch';
import { knowledgeFields, type KnowledgeCandidate, type KnowledgeCard, type KnowledgeContent, type KnowledgeSnapshot } from '@/services/douyinKnowledge';
import { Field, Pager, useRows } from './ResearchCommon';
import './CreationKnowledge.css';

const categories = { content: '内容知识', method: '创作方法' };
const bases = { author_view: '作者观点', observation: '观察', inference: 'AI 推断' };
const statuses: Record<string, string> = { pending: '等待索引', indexing: '索引中', ready: '可推荐', failed: '索引失败，可手动选用' };

export function KnowledgeSources({ card }: { card: KnowledgeContent }) {
  return <details className="douyin-knowledge-sources"><summary>查看原始出处（{card.evidence.length}）</summary>
    {card.evidence.map(source => <article key={source.ref}>
      <strong>{source.account_name} · {source.title || '未命名作品'}</strong>
      <p>{source.kind === 'frame' ? '画面观察记录' : '原文依据'}{source.start != null && ` · ${source.start.toFixed(1)}${source.end != null ? `–${source.end.toFixed(1)}` : ''} 秒`}</p>
      <blockquote>{source.text}</blockquote>
      {/^https:\/\/(www\.)?douyin\.com\//.test(source.url) && <a href={source.url} target="_blank" rel="noreferrer">打开原作品</a>}
    </article>)}
  </details>;
}

function CardBody({ card, children }: { card: KnowledgeContent; children?: ReactNode }) {
  return <article className="douyin-research-card douyin-knowledge-card">
    <div><Tag>{categories[card.category]}</Tag><Tag>{bases[card.basis]}</Tag></div>
    <h4>{card.title}</h4><p>{card.text}</p>{card.application_notes && <p><strong>适用场景：</strong>{card.application_notes}</p>}
    <div>{card.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}</div><KnowledgeSources card={card} />{children}
  </article>;
}

export function KnowledgeReferences({ cards }: { cards?: KnowledgeSnapshot[] }) {
  if (!cards?.length) return null;
  return <details className="douyin-knowledge-reference"><summary>本次参考知识（{cards.length}）</summary>
    <p>以下为生成时的参考快照，外部观点不代表你的亲身经历。</p>
    <div className="douyin-knowledge-grid">{cards.map(card => <CardBody key={card.id} card={card}><small>卡片版本 {card.revision}</small></CardBody>)}</div>
  </details>;
}

function KnowledgeEditor({ card, onClose, onSave }: { card: KnowledgeContent; onClose: () => void; onSave: (value: KnowledgeContent) => Promise<void> }) {
  const [value, setValue] = useState(card); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [tags, setTags] = useState(card.tags.join('，'));
  const changed = JSON.stringify(value) !== JSON.stringify(card) || tags !== card.tags.join('，');
  const save = async () => {
    setBusy(true); setError('');
    try {
      const parsed = [...new Set(tags.split(/[,，]/).map(t => t.trim()).filter(Boolean))];
      if (parsed.length > 20 || parsed.some(t => t.length > 40)) throw new Error('最多20个标签，每个不超过40字。');
      await onSave({ ...value, tags: parsed }); onClose();
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  };
  const close = () => {
    if (!busy && (!changed || window.confirm('关闭会丢弃当前未保存的编辑，是否关闭？'))) onClose();
  };
  return <Drawer className="douyin-knowledge-drawer" title="编辑知识卡片" open width={640} onClose={close} maskClosable={false}
    footer={<div className="douyin-actions"><Button onClick={close} disabled={busy}>取消</Button><Button type="primary" loading={busy} disabled={!value.title.trim() || !value.text.trim()} onClick={() => void save()}>保存卡片</Button></div>}>
    <div className="douyin-form">
      {error && <Alert type="error" message={error} description="编辑内容已保留。版本冲突时可先复制内容，关闭后刷新卡片再编辑。" />}
      <Field label="知识标题"><Input aria-label="知识标题" value={value.title} maxLength={300} onChange={e => setValue({ ...value, title: e.target.value })} /></Field>
      <Field label="知识正文"><Input.TextArea aria-label="知识正文" rows={8} maxLength={6000} value={value.text} onChange={e => setValue({ ...value, text: e.target.value })} /></Field>
      <Field label="适用场景"><Input.TextArea aria-label="适用场景" rows={3} maxLength={2000} value={value.application_notes} onChange={e => setValue({ ...value, application_notes: e.target.value })} /></Field>
      <Field label="标签（逗号分隔）"><Input aria-label="知识标签" value={tags} maxLength={820} onChange={e => setTags(e.target.value)} /></Field>
      <p>证据与依据标记保留原始记录，编辑正文不会修改来源。</p><KnowledgeSources card={card} />
    </div>
  </Drawer>;
}

export function KnowledgeCandidates({ client, task }: { client: ResearchClient; task: ResearchTask }) {
  const [cards, setCards] = useState<KnowledgeCandidate[]>(task.output.cards || []);
  const [selected, setSelected] = useState<string[]>([]); const [saved, setSaved] = useState<string[]>(task.output.saved_candidate_ids || []);
  const [editing, setEditing] = useState<KnowledgeCandidate | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function confirm() {
    setBusy(true); setError('');
    try {
      await client.confirmKnowledge({ task_id: task.id, cards: cards.filter(c => selected.includes(c.candidate_id)).map(c => ({ candidate_id: c.candidate_id, ...knowledgeFields(c) })) });
      setSaved(old => [...old, ...selected]); setSelected([]);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <section className="douyin-form" aria-label="候选知识">
    <h3>选择值得保存的知识</h3><p>先核对原文并按需编辑，确认后才会进入个人知识库。</p>
    {error && <Alert type="error" message={error} />}{!!saved.length && <Alert type="success" message={`已入库 ${saved.length} 张卡片，可在创作知识库查看。`} />}
    <div className="douyin-knowledge-grid">{cards.map(card => <CardBody key={card.candidate_id} card={card}>
      <div className="douyin-actions"><Checkbox disabled={busy || saved.includes(card.candidate_id)} checked={selected.includes(card.candidate_id)} onChange={e => setSelected(old => e.target.checked ? [...old, card.candidate_id] : old.filter(id => id !== card.candidate_id))}>选择 {card.title}</Checkbox>
        <Button disabled={busy || saved.includes(card.candidate_id)} onClick={() => setEditing(card)}>编辑</Button>{saved.includes(card.candidate_id) && <Tag>已入库</Tag>}
      </div>
    </CardBody>)}</div>
    <Button type="primary" loading={busy} disabled={!selected.length} onClick={() => void confirm()}>确认入库（{selected.length}）</Button>
    {editing && <KnowledgeEditor key={editing.candidate_id} card={editing} onClose={() => setEditing(null)} onSave={async value => { setCards(old => old.map(c => c.candidate_id === editing.candidate_id ? { ...c, ...value } : c)); }} />}
  </section>;
}

export function ExtractKnowledge({ task, run }: { task: Pick<ResearchTask, 'id' | 'kind' | 'status' | 'output'>; run: (body: Record<string, unknown>) => Promise<void> }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const eligible = task.status === 'succeeded' && ['transcribe', 'breakdown', 'joint'].includes(task.kind);
  if (!eligible) return null;
  return <div className="douyin-form"><Button loading={busy} onClick={() => {
    setBusy(true); setError(''); void run({ kind: 'knowledge_extract', source_task_id: task.id }).catch(e => setError(documentError(e))).finally(() => setBusy(false));
  }}>提炼知识</Button>{error && <Alert type="error" message={error} />}</div>;
}

export function KnowledgeLibrary({ client }: { client: ResearchClient }) {
  const [search, setSearch] = useState(''); const [category, setCategory] = useState(''); const [tag, setTag] = useState('');
  const rows = useRows<KnowledgeCard>(client, 'knowledge-cards', { search, category, tag });
  const [editing, setEditing] = useState<KnowledgeCard | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const reload = useRef(rows.reload); reload.current = rows.reload;
  const pending = rows.results.some(c => ['pending', 'indexing'].includes(c.index_status));
  useEffect(() => { if (!pending) return; const timer = setInterval(() => reload.current(), 3000); return () => clearInterval(timer); }, [pending]);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true); setError(''); try { await fn(); rows.reload(); } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <section className="douyin-form douyin-knowledge-library">
    <div className="douyin-section-title"><h2>创作知识库</h2><Button onClick={rows.reload}>刷新知识</Button></div>
    <p>仅你可见，可跨对标账号检索，供自己的不同创作账号选用。</p>
    <div className="douyin-knowledge-filters">
      <Field label="搜索知识"><Input.Search aria-label="搜索知识" placeholder="搜索标题、正文或适用场景" allowClear onSearch={setSearch} /></Field>
      <Field label="知识类型"><Select aria-label="知识类型" value={category} options={[{ value: '', label: '全部类型' }, ...Object.entries(categories).map(([value, label]) => ({ value, label }))]} onChange={setCategory} /></Field>
      <Field label="筛选标签"><Input.Search aria-label="筛选标签" placeholder="输入完整标签" allowClear onSearch={setTag} /></Field>
    </div>
    {(error || rows.error) && <Alert type="error" message={error || rows.error} action={<Button onClick={rows.reload}>重试加载</Button>} />}
    {rows.loading && <Spin />} {!rows.loading && !rows.error && !rows.results.length && <Empty description={search || category || tag ? '没有匹配的知识，可调整筛选条件。' : '尚无知识卡片，请从作品转写或拆解结果中提炼并确认入库。'} />}
    <div className="douyin-knowledge-grid">{rows.results.map(card => <CardBody key={card.id} card={card}>
      {card.source_missing && <p>来源已移除，已保存的证据仍可核对。</p>}<small>{statuses[card.index_status] || card.index_status} · 版本 {card.revision}</small>
      {card.index_status === 'failed' && <Alert type="warning" message="索引失败" description="卡片已保存，仍可手动选用。重试后会重新参与推荐。" />}
      <div className="douyin-actions"><Button disabled={busy} onClick={() => setEditing(card)}>编辑</Button>
        {card.index_status === 'failed' && <Button disabled={busy} onClick={() => void action(() => client.retryKnowledgeIndex(card.id))}>重试索引</Button>}
        <Popconfirm title="删除这张知识卡片？" description="将退出推荐和新创作，历史生成快照保留。" onConfirm={() => action(() => client.remove('knowledge-cards', card.id))}><Button danger type="text" disabled={busy}>删除</Button></Popconfirm>
      </div>
    </CardBody>)}</div><Pager rows={rows} />
    {editing && <KnowledgeEditor key={`${editing.id}:${editing.revision}`} card={editing} onClose={() => setEditing(null)} onSave={async value => { await client.update('knowledge-cards', editing.id, { revision: editing.revision, ...knowledgeFields(value) }); rows.reload(); }} />}
  </section>;
}

export function KnowledgePicker({ client, query, selected, onChange }: { client: ResearchClient; query: string; selected: KnowledgeSnapshot[]; onChange: (value: KnowledgeSnapshot[]) => void }) {
  const [results, setResults] = useState<KnowledgeCard[]>([]); const [lastQuery, setLastQuery] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [searched, setSearched] = useState(false);
  const [search, setSearch] = useState(''); const [page, setPage] = useState(1); const [count, setCount] = useState(0); const [browsing, setBrowsing] = useState(false);
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);
  async function load(mode: 'recommend' | 'search', nextPage = 1, text = search) {
    const token = ++request.current; setBusy(true); setError('');
    try {
      const data = mode === 'recommend' ? await client.recommendKnowledge(query) : await client.list<KnowledgeCard>('knowledge-cards', { search: text, page: nextPage });
      if (token !== request.current) return;
      setResults(data.results); setSearched(true); setBrowsing(mode === 'search'); setPage(nextPage); setCount('count' in data && typeof data.count === 'number' ? data.count : 0);
      if (mode === 'recommend') setLastQuery(query);
    } catch (e) { if (token === request.current) setError(documentError(e)); } finally { if (token === request.current) setBusy(false); }
  }
  function toggle(card: KnowledgeSnapshot, checked: boolean) {
    if (checked && selected.length >= 10) { setError('一次最多选择10张知识卡片。'); return; }
    onChange(checked ? [...selected, card] : selected.filter(c => c.id !== card.id));
  }
  return <section className="douyin-form douyin-knowledge-picker" aria-label="参考知识">
    <h3>参考知识 <small>已选 {selected.length} / 10</small></h3><p>外部观点与创作方法仅作参考，勾选后才会用于本次创作。</p>
    <div className="douyin-actions"><Button disabled={busy || !query.trim()} onClick={() => void load('recommend')}>推荐相关知识</Button><Button disabled={busy} onClick={() => void load('search')}>浏览全部知识</Button></div>
    {lastQuery !== null && query !== lastQuery && <p role="status">主题或定位已改变，推荐待刷新；已选知识保留。</p>}
    <Field label="搜索补选知识"><Input.Search aria-label="搜索补选知识" value={search} onChange={e => setSearch(e.target.value)} onSearch={value => void load('search', 1, value)} allowClear /></Field>
    {error && <Alert type="error" message={error} />}{busy && <Spin />}
    {!!selected.length && <div className="douyin-knowledge-selected">{selected.map(card => <div key={card.id}><Checkbox checked onChange={() => toggle(card, false)}>{card.title} · v{card.revision}</Checkbox><Button size="small" disabled={busy} onClick={() => {
      setBusy(true); setError(''); void client.knowledgeCard(card.id).then(latest => onChange(selected.map(c => c.id === latest.id ? latest : c))).catch(e => setError(documentError(e))).finally(() => setBusy(false));
    }}>刷新版本</Button></div>)}</div>}
    {searched && !busy && !results.length && <Empty description="没有匹配的知识，可搜索其他关键词或直接创作。" />}
    <div className="douyin-knowledge-grid">{results.map(card => <CardBody key={card.id} card={card}>
      {card.source_missing && <p>来源已移除，保留证据快照。</p>}
      <Checkbox checked={selected.some(c => c.id === card.id)} disabled={busy || selected.length >= 10 && !selected.some(c => c.id === card.id)} onChange={e => toggle(card, e.target.checked)}>使用 {card.title}</Checkbox>
    </CardBody>)}</div>
    {browsing && <Pager rows={{ page, count, setPage: value => { void load('search', value); } }} />}
  </section>;
}

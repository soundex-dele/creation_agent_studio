import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Input, Modal, Select, Tag } from 'antd';
import { metric, type DouyinAccount } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { metricLabels, type Comparison, type MetricKey, type ResearchClient, type ResearchWork, type Trend } from '@/services/douyinResearch';
import { Field, Pager, Status, useRows } from './ResearchCommon';

export function ComparisonTable({ data }: { data: Comparison }) {
  return <section><p>{data.note}</p><div className="douyin-comparison-grid">{data.accounts.map(a => <article className="douyin-research-card" key={a.account_id}><h3>{a.name}</h3>
    <p>采集时间：{a.captured_at ? new Date(a.captured_at).toLocaleString() : '未采集'}</p><dl className="douyin-research-metrics"><div><dt>样本数</dt><dd>{a.sample_count}</dd></div><div><dt>样本内每周发布</dt><dd>{a.posts_per_week ?? '—'}</dd></div>
      {(Object.keys(metricLabels) as MetricKey[]).map(key => <div key={key}><dt>{metricLabels[key]}中位数</dt><dd>{metric(a.medians[key])}</dd></div>)}<div><dt>突出作品占有效样本</dt><dd>{a.outstanding_share == null ? '不可计算' : `${(a.outstanding_share * 100).toFixed(1)}%`}</dd></div></dl>
    <p>时长分布：30秒内 {a.duration_buckets.under_30} / 30–60秒 {a.duration_buckets['30_to_60']} / 60–180秒 {a.duration_buckets['60_to_180']} / 180秒以上 {a.duration_buckets['180_plus']}</p><small>{a.explanation}</small>
  </article>)}</div></section>;
}

export function TrendPanel({ data }: { data: Trend }) {
  const [key, setKey] = useState<MetricKey>('likes');
  const values = data.points.map(p => p.values[key]);
  const max = Math.max(1, ...values.filter((v): v is number => v !== null));
  const dates = data.points.map(p => Date.parse(p.captured_at));
  const span = Math.max(1, (dates[dates.length - 1] || 0) - (dates[0] || 0));
  const x = (i: number) => 35 + (dates[i] - dates[0]) / span * 530;
  const y = (v: number) => 170 - v / max * 145;
  return <section><h3>{data.work.title}</h3><Field label="趋势指标"><Select aria-label="趋势指标" value={key} options={Object.entries(metricLabels).map(([value, label]) => ({ value, label }))} onChange={setKey} /></Field>
    {values.filter(v => v != null).length >= 4 && <svg className="douyin-trend" viewBox="0 0 600 210" role="img" aria-label={`${metricLabels[key]}累计值趋势，详细数值见下方数据表`}>
      <text x="0" y="20">{max}</text><text x="15" y="174">0</text><path d="M35 20V170H565" className="douyin-chart-axis" />
      {values.map((value, i) => value == null ? null : <g key={i}>{i > 0 && values[i - 1] != null && <line x1={x(i - 1)} y1={y(values[i - 1]!)} x2={x(i)} y2={y(value)} className="douyin-chart-line" />}<circle cx={x(i)} cy={y(value)} r="4" tabIndex={0}><title>{new Date(dates[i]).toLocaleString()}：{value}</title></circle></g>)}
      <text x="35" y="198">{new Date(dates[0]).toLocaleDateString()}</text><text x="565" y="198" textAnchor="end">{new Date(dates[dates.length - 1]!).toLocaleDateString()}</text>
    </svg>}
    <p>按实际采集时间展示；缺失值为“未获取”，下降值保留。少于4个有效观测时仅显示数据表。</p>
    <div className="douyin-table-scroll" tabIndex={0} aria-label="指标历史表"><table className="douyin-data-table"><caption>{metricLabels[key]}采集历史</caption><thead><tr><th>采集时间</th><th>累计值</th><th>相邻增量</th><th>每小时增量</th></tr></thead><tbody>{data.points.map((p, i) => <tr key={i}><td>{new Date(p.captured_at).toLocaleString()}</td><td>{metric(p.values[key])}</td><td>{metric(p.delta[key])}</td><td>{metric(p.per_hour[key])}</td></tr>)}</tbody></table></div>
    {!data.points.length && <p>暂无指标快照，请先刷新作品。</p>}
  </section>;
}

export function ResearchLibrary({ client, accounts, run, onAccounts }: { client: ResearchClient; accounts: DouyinAccount[]; run: (body: Record<string, unknown>) => Promise<void>; onAccounts: () => void }) {
  const [selectedAccounts, setAccounts] = useState<string[]>([]); const [group, setGroup] = useState(''); const [days, setDays] = useState(30); const [search, setSearch] = useState(''); const [sort, setSort] = useState('published_at');
  const [selected, setSelected] = useState<string[]>([]); const [comparison, setComparison] = useState<Comparison | null>(null); const [trend, setTrend] = useState<Trend | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [commentCount, setCommentCount] = useState(100); const [replies, setReplies] = useState(false);
  const rows = useRows<ResearchWork>(client, 'works', { accounts: selectedAccounts.length ? selectedAccounts.join(',') : undefined, group, days, search, sort });
  async function action(fn: () => Promise<unknown>) { setBusy(true); setError(''); setMessage(''); try { await fn(); setMessage('操作已完成，可在下方查看结果或前往素材库查看收藏。'); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } }
  useEffect(() => { setSelected([]); }, [group, days, search, selectedAccounts]);
  return <section className="douyin-form"><div className="douyin-section-title"><div><h2>跨账号研究</h2><p>从已采集作品发现主题，比较表达方法。</p></div><Button onClick={onAccounts}>管理对标账号</Button></div>
    <div className="douyin-research-filters"><Field label="研究账号"><Select aria-label="研究账号" mode="multiple" value={selectedAccounts} placeholder="默认全部账号" options={accounts.map(a => ({ value: a.id, label: a.name || a.source_url }))} onChange={setAccounts} /></Field>
      <Field label="账号分组"><Select aria-label="账号分组" allowClear value={group || undefined} options={[...new Set(accounts.map(a => a.group).filter(Boolean))].map(value => ({ value, label: value }))} onChange={v => setGroup(v || '')} /></Field>
      <Field label="发布范围"><Select aria-label="发布范围" value={days} options={[7, 30, 90].map(value => ({ value, label: `最近${value}天` }))} onChange={setDays} /></Field>
      <Field label="作品搜索"><Input aria-label="作品搜索" value={search} onChange={e => setSearch(e.target.value)} /></Field>
      <Field label="作品排序"><Select aria-label="作品排序" value={sort} options={[{ value: 'published_at', label: '发布时间' }, ...Object.entries(metricLabels).map(([value, label]) => ({ value, label }))]} onChange={setSort} /></Field>
    </div>
    <div className="douyin-actions"><Button type="primary" loading={busy} onClick={() => void action(() => run({ kind: 'radar', account_ids: selectedAccounts, group, days }))}>生成对标主题分析</Button><Button disabled={selectedAccounts.length < 2 || selectedAccounts.length > 5 || busy} onClick={() => void action(async () => setComparison(await client.compare(selectedAccounts, days)))}>比较账号数据</Button><Button disabled={selectedAccounts.length < 2 || selectedAccounts.length > 5 || busy} onClick={() => void action(() => run({ kind: 'compare', account_ids: selectedAccounts, days }))}>分析内容方向</Button></div>
    {comparison && <ComparisonTable data={comparison} />}{error && <Alert type="error" message={error} />}{message && <Alert type="success" message={message} />}
    <div className="douyin-research-batch"><span>已选 {selected.length} 条作品（可跨页）</span><Button disabled={selected.length < 2 || selected.length > 5 || busy} onClick={() => void action(() => run({ kind: 'joint', work_ids: selected }))}>联合拆解</Button><Button disabled={!selected.length || busy} onClick={() => void action(() => run({ kind: 'refresh', work_ids: selected }))}>刷新所选指标</Button><Button disabled={!selected.length} onClick={() => setSelected([])}>清空选择</Button></div>
    <div className="douyin-actions"><Field label="一级评论上限"><Select aria-label="一级评论上限" value={commentCount} options={[50, 100, 200].map(value => ({ value, label: `${value}条` }))} onChange={setCommentCount} /></Field><Checkbox checked={replies} onChange={e => setReplies(e.target.checked)}>包含回复（每作品总计最多500条）</Checkbox><Button disabled={selected.length !== 1 || busy} onClick={() => void action(() => run({ kind: 'comments', work_ids: selected, count: commentCount, include_replies: replies }))}>采集所选作品评论</Button></div>
    <Status loading={rows.loading} error={rows.error} empty={!rows.results.length} />
    <div className="douyin-research-grid">{rows.results.map(w => <article className="douyin-research-card" key={w.id}>
      <Checkbox aria-label={`选择 ${w.title}`} checked={selected.includes(w.id)} disabled={!selected.includes(w.id) && selected.length >= 20} onChange={e => setSelected(old => e.target.checked ? [...old, w.id] : old.filter(id => id !== w.id))}>{w.account_name}</Checkbox>
      <h3>{w.title || '未命名作品'}</h3><p>{w.published_at ? new Date(w.published_at).toLocaleString() : '发布时间未获取'} {w.kind === 'image_album' && <Tag>图文</Tag>}</p>
      <dl className="douyin-research-metrics">{(Object.keys(metricLabels) as MetricKey[]).map(key => <div key={key}><dt>{metricLabels[key]}</dt><dd>{metric(w[key])}</dd></div>)}</dl>
      <div className="douyin-actions"><a href={w.url} target="_blank" rel="noreferrer">原作品</a><Button onClick={() => void action(async () => setTrend(await client.trend(w.id)))}>增长趋势</Button><Button onClick={() => void action(() => client.create('inspirations', { title: w.title || '未命名作品', kind: 'work', work: w.id, text: w.description || '', tags: [] }))}>收藏灵感</Button></div>
    </article>)}</div><Pager rows={rows} />
    <Modal className="douyin-modal" title="作品增长追踪" open={!!trend} width={850} footer={null} onCancel={() => setTrend(null)}>{trend && <TrendPanel data={trend} />}</Modal>
  </section>;
}

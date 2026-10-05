import { useEffect, useState, type Ref } from 'react';
import { Alert, Button, Empty, Input, Select, Tag } from 'antd';
import { type Data, type Library, type Matches, type Preferences, type RentalApi, type RentalRecord, type Report, type Task, activeTask, rentalError, string, strings } from '@/services/rentalGrowth';
import { options, platformLabels, typeLabels } from './config';
import type { EditorState } from './Editors';
import { GenerationMessages } from './GenerationMessages';

export function Creator({ library, preferences, initial, busy, onTask, generateButtonRef }: { library: Library; preferences: Preferences; initial: Data; busy: boolean; onTask: (value: Data) => Promise<void>; generateButtonRef?: Ref<HTMLButtonElement> }) {
  const [platform, setPlatform] = useState(string(initial.platform) || preferences.platform);
  const [kind, setKind] = useState(string(initial.content_type) || 'property');
  const [properties, setProperties] = useState(strings(initial.property_ids));
  const [persona, setPersona] = useState(string(initial.persona_id));
  const [instruction, setInstruction] = useState(string(initial.angle));
  const [start, setStart] = useState('');
  const selectedPersona = library.personas.find(row => row.id === persona && !row.archived);
  return <section className="rental-card rental-composer">
    <div className="rental-section-heading"><div><span className="rental-eyebrow">CONTENT STUDIO</span><h2>{initial.content_id ? '继续创作／转换平台' : '把真实房源，写成值得咨询的内容'}</h2><p>先选房源与租客，再确定今天想讲的角度。</p></div></div>
    <div className="rental-form-grid">
      <div className="rental-field"><label htmlFor="creator-platform">平台</label><Select id="creator-platform" value={platform} options={options(platformLabels).filter(o => o.value !== 'unknown')} onChange={setPlatform} /></div>
      <div className="rental-field"><label htmlFor="creator-kind">内容类型</label><Select id="creator-kind" value={kind} options={options(typeLabels)} onChange={setKind} /></div>
      <div className="rental-field rental-field--wide"><label htmlFor="creator-properties">房源</label><Select id="creator-properties" mode="multiple" showSearch optionFilterProp="label" value={properties} options={library.properties.filter(r => !r.archived && r.status === 'available').map(r => ({ value: r.id, label: `${r.title} · ${r.data.rent == null ? '租金待补充' : `${r.data.rent} 元／月`}` }))} onChange={setProperties} /><small>单套推荐至少一套，对比至少两套。攻略与问答可以不选房源。</small></div>
      <div className="rental-field"><label htmlFor="creator-persona">目标租客画像</label><Select id="creator-persona" allowClear showSearch optionFilterProp="label" placeholder="选择常用画像，也可不指定" value={persona || undefined} options={library.personas.filter(r => !r.archived).map(r => ({ value: r.id, label: r.title }))} onChange={v => setPersona(v || '')} /><small>决定文案写给谁看；可在「房源 → 目标租客画像」编辑。</small>{selectedPersona && <div className="rental-prose"><p>{string(selectedPersona.data.needs)}</p><p><strong>关注点：</strong>{string(selectedPersona.data.concerns) || '未填写'}</p></div>}</div>
      <div className="rental-field"><label htmlFor="creator-date">七天计划开始日期</label><Input id="creator-date" type="date" value={start} onChange={e => setStart(e.target.value)} /><small>留空从今天开始，每天一个选题。</small></div>
      <div className="rental-field rental-field--wide"><label htmlFor="creator-angle">内容角度、真实素材或修改要求</label><Input.TextArea id="creator-angle" rows={4} value={instruction} maxLength={20000} onChange={e => setInstruction(e.target.value)} placeholder="例如：面向养猫的上班族，说明费用和临街噪声；或粘贴真实带看经验。" /></div>
    </div>
    <div className="rental-actions"><Button ref={generateButtonRef} type="primary" loading={busy} onClick={() => void onTask({ kind: 'copy', platform, content_type: kind, property_ids: properties, persona_id: persona || null, content_id: initial.content_id || null, instruction })}>生成发布文案</Button><Button disabled={busy} onClick={() => void onTask({ kind: 'topics', platform, property_ids: properties, persona_id: persona || null, instruction, start_date: start || null })}>生成七天选题</Button></div>
    <p className="rental-muted">生成后可编辑、保存和复制。平台发布由你手动完成。</p>
  </section>;
}

export function TaskHistory({ tasks, busy, library, onTask, onCancel, onApply, onEdit, onOpenCopy }: { tasks: Task[]; busy: boolean; library: Library; onTask: (value: Data) => Promise<void>; onCancel: (id: string) => void; onApply: (id: string) => void; onEdit: (editor: EditorState) => void; onOpenCopy: (row: RentalRecord) => void }) {
  const [limit, setLimit] = useState(5); const [notice, setNotice] = useState('');
  const names: Record<string, string> = { topics: '七天选题', copy: '文案生成', extract: '需求提取', reply: '回复建议', review: '效果复盘' };
  return <section className="rental-task-history"><h3>生成记录</h3>{notice && <Alert type="info" message={notice} closable onClose={() => setNotice('')} />}{!tasks.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成结果会保存在这里，离开页面后也能回来继续。" />}
    {[...tasks.filter(activeTask), ...tasks.filter(task => !activeTask(task)).slice(0, limit)].map(task => <article className="rental-card" key={task.id}>
      <div className="rental-card-title"><h3>{names[task.kind]}</h3><Tag>{({ queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[task.status] || task.status}</Tag></div>
      <time className="rental-muted">{new Date(task.created_at).toLocaleString('zh-CN')}</time>
      <GenerationMessages task={task} />
      {task.error && <Alert type="error" message={task.error} />}
      {task.result.topics && <ol className="rental-topic-list">{task.result.topics.map((topic, i) => <li key={i}><span>{topic.date}</span><strong>{topic.title}</strong><p>{topic.angle}</p></li>)}</ol>}
      {task.result.answer && <p className="rental-prose">{task.result.answer}</p>}
      {task.result.questions?.length ? <div className="rental-note"><strong>下一步待确认</strong><ul>{task.result.questions.map((q, i) => <li key={i}>{q}</li>)}</ul></div> : null}
      {task.result.requirements && <div className="rental-note"><strong>提取的需求草稿</strong><dl>{Object.entries(task.result.requirements).map(([key, value]) => <div key={key}><dt>{({ budget_min: '最低预算', budget_max: '最高预算', city: '城市', districts: '片区', rental_type: '出租方式', layout: '户型', move_in: '入住日期', must_have: '必要条件', needs: '生活需求', concerns: '关注点' } as Record<string, string>)[key] || key}</dt><dd>{Array.isArray(value) ? value.join('、') : String(value)}</dd></div>)}</dl></div>}
      <div className="rental-actions">
        {activeTask(task) && <Button disabled={busy} onClick={() => onCancel(task.id)}>取消生成</Button>}
        {['failed', 'cancelled'].includes(task.status) && <Button disabled={busy} onClick={() => void onTask(task.request)}>重新生成</Button>}
        {task.status === 'succeeded' && task.kind === 'topics' && <Button disabled={busy || task.applied} onClick={() => onApply(task.id)}>{task.applied ? '已加入创作计划' : '采用七天计划'}</Button>}
        {task.result.content_id && <Button onClick={() => { const row = library.contents.find(r => r.id === task.result.content_id); if (row) onOpenCopy(row); }}>打开文案</Button>}
        {task.result.answer && <Button onClick={() => void navigator.clipboard.writeText(task.result.answer!).then(() => setNotice('已复制，请核对后自行发送。')).catch(() => setNotice('复制失败，请选择文本手动复制。'))}>复制建议</Button>}
        {task.result.requirements && <Button onClick={() => { const row = library.leads.find(r => r.id === task.request.lead_id); if (row) onEdit({ kind: 'leads', row, data: task.result.requirements }); }}>审核并应用到客户档案</Button>}
      </div>
    </article>)}
    {tasks.length > limit && <Button onClick={() => setLimit(v => v + 10)}>加载更早记录</Button>}
  </section>;
}

export function LeadDesk({ lead, library, api, busy, tasks, onTask, onEdit, onCancel, onApply, onOpenCopy }: { lead: RentalRecord; library: Library; api: RentalApi; busy: boolean; tasks: Task[]; onTask: (value: Data) => Promise<void>; onEdit: (editor: EditorState) => void; onCancel: (id: string) => void; onApply: (id: string) => void; onOpenCopy: (row: RentalRecord) => void }) {
  const [matches, setMatches] = useState<Matches | null>(null); const [error, setError] = useState('');
  const [consultation, setConsultation] = useState(''); const [properties, setProperties] = useState(strings(lead.data.property_ids));
  const [scenario, setScenario] = useState('首次咨询');
  useEffect(() => { let alive = true; api.matches(lead.id).then(value => { if (alive) setMatches(value); }).catch(e => { if (alive) setError(rentalError(e)); }); return () => { alive = false; }; }, [api, lead.id, lead.revision, library.properties]);
  return <section className="rental-lead-desk">
    <div className="rental-section-heading"><div><span className="rental-eyebrow">CLIENT DESK</span><h2>{lead.title} · 咨询工作台</h2><p>整理需求、匹配房源，再确定下一步。</p></div><Button onClick={() => onEdit({ kind: 'leads', row: lead })}>编辑客户</Button></div>
    {!!lead.duplicates?.length && <Alert type="warning" message={`联系方式可能重复：${lead.duplicates.map(r => r.title).join('、')}。记录未自动合并。`} />}
    {error && <Alert type="error" message={error} />}
    <div className="rental-card"><h3>房源匹配</h3><div className="rental-match-grid">{(['matched', 'unknown', 'conflicts'] as const).map(bucket => <section key={bucket}><h4>{{ matched: '符合条件', unknown: '待确认', conflicts: '明确冲突' }[bucket]} · {matches?.[bucket].length || 0}</h4>{matches?.[bucket].map(item => <article className="rental-match-item" key={item.property.id}><strong>{item.property.title}</strong><p>{item.reasons.join('；')}</p><p className={bucket === 'conflicts' ? 'rental-warning' : 'rental-muted'}>{[...item.unknown, ...item.conflicts].join('；')}</p><Button size="small" onClick={() => onEdit({ kind: 'properties', row: item.property })}>查看房源</Button></article>)}</section>)}</div></div>
    <div className="rental-card"><h3>咨询与回复助手</h3><div className="rental-form-grid">
      <div className="rental-field"><label htmlFor="reply-scenario">沟通场景</label><Select id="reply-scenario" value={scenario} options={['首次咨询', '预算询问', '推荐房源', '预约带看', '看房后跟进', '房源已出租'].map(value => ({ value, label: value }))} onChange={setScenario} /></div>
      <div className="rental-field"><label htmlFor="reply-properties">本次相关房源</label><Select id="reply-properties" mode="multiple" value={properties} options={library.properties.filter(p => !p.archived).map(p => ({ value: p.id, label: p.title }))} onChange={setProperties} /></div>
      <div className="rental-field rental-field--wide"><label htmlFor="reply-text">客户咨询原文</label><Input.TextArea id="reply-text" value={consultation} onChange={e => setConsultation(e.target.value)} maxLength={18000} rows={6} placeholder="粘贴咨询内容，例如预算、区域、入住时间和顾虑。" /></div>
    </div><div className="rental-actions"><Button type="primary" disabled={busy || !consultation.trim()} onClick={() => void onTask({ kind: 'reply', lead_id: lead.id, property_ids: properties, instruction: `场景：${scenario}\n咨询：${consultation}` })}>生成回复建议</Button><Button disabled={busy || !consultation.trim()} onClick={() => void onTask({ kind: 'extract', lead_id: lead.id, instruction: consultation })}>提取需求草稿</Button><Button onClick={() => onEdit({ kind: 'followups', initial: { title: `${lead.title} · 跟进`, lead_id: lead.id } })}>记录跟进</Button><Button onClick={() => onEdit({ kind: 'viewings', initial: { title: `${lead.title} · 带看`, lead_id: lead.id }, data: { property_ids: properties } })}>预约带看</Button></div></div>
    <TaskHistory tasks={tasks.filter(t => t.request.lead_id === lead.id)} {...{ library, busy, onTask, onEdit, onCancel, onApply, onOpenCopy }} />
  </section>;
}

function rate(value: number | null) { return value == null ? '—' : `${(value * 100).toFixed(1)}%`; }
export function ReportPanel({ report, library, busy, onTask, onRange }: { report: Report | null; library: Library; busy: boolean; onTask: (value: Data) => Promise<void>; onRange: (range: Data) => void }) {
  const [start, setStart] = useState(''); const [end, setEnd] = useState(''); const [group, setGroup] = useState('platform');
  const lookup = (key: string) => key === 'unknown' ? '未知／未关联' : platformLabels[key] || typeLabels[key] || library.personas.find(r => r.id === key)?.title || library.properties.find(r => r.id === key)?.title || key;
  return <section>
    <div className="rental-section-heading"><div><span className="rental-eyebrow">GROWTH REVIEW</span><h2>看见内容带来的真实咨询</h2><p>把关注点放在客户、带看和成交上。</p></div><Button disabled={busy} onClick={() => void onTask({ kind: 'review', instruction: '请复盘全部已记录数据，给出下一步运营建议。' })}>生成全量复盘建议</Button></div>
    <div className="rental-filters"><div className="rental-field"><label htmlFor="report-start">首次咨询开始日期</label><Input id="report-start" type="date" value={start} onChange={e => setStart(e.target.value)} /></div><div className="rental-field"><label htmlFor="report-end">首次咨询结束日期</label><Input id="report-end" type="date" value={end} onChange={e => setEnd(e.target.value)} /></div><Button onClick={() => onRange({ start, end })}>查看客户批次</Button></div>
    {report && <><div className="rental-kpis">{[['咨询客户', report.summary.leads], ['已带看客户', report.summary.viewed], ['成交客户', report.summary.won], ['带看率', rate(report.summary.viewing_rate)], ['成交率', rate(report.summary.deal_rate)]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div><p className="rental-muted">{report.note}</p>
      <div className="rental-card"><div className="rental-field"><label htmlFor="report-group">比较维度</label><Select id="report-group" value={group} onChange={setGroup} options={options({ platform: '平台', content_type: '内容类型', persona_id: '目标画像', property_ids: '房源' })} /></div><div className="rental-summary-list">{report.groups[group]?.map(row => <article key={row.key}><strong>{lookup(row.key)}</strong><span>咨询 {row.leads} · 带看 {row.viewed} · 成交 {row.won}</span><span>带看率 {rate(row.viewing_rate)} · 成交率 {rate(row.deal_rate)}</span></article>)}</div></div>
      <h3>作品效果</h3><div className="rental-grid">{report.publications.map(row => <article className="rental-card" key={row.id}><h3>{row.title}</h3><Tag>{platformLabels[row.platform]}</Tag><p>咨询 {row.leads} · 带看 {row.viewed} · 成交 {row.won}</p><dl className="rental-metrics">{Object.entries(row.metrics).map(([key, value]) => <div key={key}><dt>{{ views: '浏览／播放', likes: '点赞', saves: '收藏', comments: '评论' }[key]}</dt><dd>{value ?? '未记录'}</dd></div>)}</dl><small>数据更新：{row.metrics_at ? new Date(row.metrics_at).toLocaleString('zh-CN') : '尚未录入'}</small></article>)}</div><p className="rental-muted">未知来源：咨询 {report.unknown.leads} · 带看 {report.unknown.viewed} · 成交 {report.unknown.won}</p>
    </>}
  </section>;
}

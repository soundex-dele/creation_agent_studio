import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, Select, Spin, Tabs, Tag } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { isActive, metric, type DouyinAccount } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { radarKinds, researchApi, researchTaskStatus, type RadarInput, type RadarSource, type ResearchTask } from '@/services/douyinResearch';
import { allRows, Field, Pager, useRows } from './ResearchCommon';
import './TopicRadar.css';

const labels: Record<string, string> = { radar_hotlist: '抖音热榜', radar_search: '关键词发现', radar_topics: '选题建议' };

function Source({ row, onKeyword }: { row: RadarSource; onKeyword?: (value: string) => void }) {
  return <div className="douyin-radar-source">
    {row.kind === 'hot' ? <><p>榜单排名 {row.rank ?? '未获取'} · 热度 {metric(row.heat ?? null)}</p>
      <h3>{row.title}</h3>{onKeyword && <Button onClick={() => onKeyword(row.title)}>搜索相关作品</Button>}</>
      : <><p>{row.author || '作者未获取'} · {row.published_at ? new Date(row.published_at).toLocaleString() : '发布时间未获取'}</p><h3>{row.title}</h3>
        <dl className="douyin-research-metrics">{(['likes', 'comments', 'collects', 'shares'] as const).map((key, index) =>
          <div key={key}><dt>{['点赞', '评论', '收藏', '分享'][index]}</dt><dd>{metric(row[key] ?? null)}</dd></div>)}</dl></>}
    <a href={row.url} target="_blank" rel="noreferrer">{row.kind === 'hot' ? '在抖音查看热词' : '打开原作品'}</a>
    <small>采集于 {new Date(row.captured_at).toLocaleString()}</small>
  </div>;
}

export function TopicRadar({ base }: { base: string }) {
  const client = useMemo(() => researchApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const taskId = params.get('task') || '';
  const [task, setTask] = useState<ResearchTask | null>(null);
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [accountError, setAccountError] = useState('');
  const [target, setTarget] = useState<string>();
  const [tab, setTab] = useState('hot');
  const [keyword, setKeyword] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [lastRequest, setLastRequest] = useState<RadarInput | null>(null);
  const [saved, setSaved] = useState<number[]>([]);
  const [saving, setSaving] = useState<number | null>(null);
  const history = useRows<ResearchTask>(client, 'tasks', { kind: radarKinds.join(',') });
  useEffect(() => {
    let alive = true;
    void allRows<DouyinAccount>(client, 'accounts').then(rows => { if (alive) { setAccounts(rows.filter(a => a.is_owned)); setAccountError(''); } })
      .catch(e => { if (alive) setAccountError(documentError(e)); });
    return () => { alive = false; };
  }, [client, retry]);
  useEffect(() => {
    if (!taskId && !history.loading && history.results[0]) {
      const id = history.results[0].id;
      setParams(old => { const next = new URLSearchParams(old); next.set('task', id); return next; }, { replace: true });
    }
  }, [taskId, history.loading, history.results, setParams]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout> | undefined;
    setTask(null); setSelected([]); setSaved([]); setError(''); setLoadError('');
    if (!taskId) return;
    const poll = async () => {
      try {
        const value = await client.task(taskId);
        if (!alive) return;
        if (!radarKinds.includes(value.kind)) { setLoadError('此任务不属于全站选题雷达，请选择下方雷达历史或发起扫描。'); return; }
        setTask(value); setLoadError('');
        if (value.kind === 'radar_search') { setTab('search'); setKeyword(value.output.keyword || value.output.radar_request?.kind === 'radar_search' && value.output.radar_request.keyword || ''); }
        if (isActive(value)) timer = setTimeout(() => void poll(), 2500);
      } catch (e) { if (alive) setLoadError(documentError(e)); }
    };
    void poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [client, taskId, retry]);
  function selectTask(id: string) {
    setParams(old => { const next = new URLSearchParams(old); next.set('task', id); return next; });
  }
  async function run(body: RadarInput) {
    setBusy(true); setError(''); setLastRequest(body);
    try { const value = await client.start(body); selectTask(value.id); setTask(value); history.reload(); }
    catch (e) { setError(documentError(e)); }
    finally { setBusy(false); }
  }
  const active = !!task && isActive(task);
  const rows = task?.output.radar_items || [];
  const topics = task?.kind === 'radar_topics' ? task.output.topics || [] : [];
  const canSelect = !!task && task.kind !== 'radar_topics' && task.status === 'succeeded';
  async function saveIdea(index: number) {
    if (!task) return;
    const topic = topics[index];
    const sources = rows.filter(row => topic.refs?.includes(row.id));
    const notes = [topic.angle, `开头：${topic.hook}`, `推荐理由：${topic.reason}`, `素材缺口：${topic.materials_needed}`,
      ...sources.map(row => `来源：${row.title}\n${decodeURI(row.url)}\n采集时间：${row.captured_at}`)].join('\n\n');
    setSaving(index); setError(''); setLastRequest(null);
    try { await client.create('ideas', { title: topic.title, notes, source_task: task.id, tags: ['选题雷达'] }); setSaved(old => [...old, index]); }
    catch (e) { setError(documentError(e)); }
    finally { setSaving(null); }
  }
  return <div className="douyin-research-hub douyin-radar">
    <section className="douyin-panel douyin-form">
      <h2>发现下一条值得做的内容</h2><p>手动扫描抖音热榜或搜索关键词，选中真实来源后生成选题建议。</p>
      <Tabs activeKey={tab} onChange={setTab} items={[{ key: 'hot', label: '抖音热榜', children:
        <Button type="primary" loading={busy} disabled={active} onClick={() => void run({ kind: 'radar_hotlist' })}>刷新热榜</Button> },
      { key: 'search', label: '关键词发现', children: <form className="douyin-radar-search" onSubmit={e => { e.preventDefault(); if (keyword.trim() && !busy && !active) void run({ kind: 'radar_search', keyword: keyword.trim() }); }}>
        <Field label="行业或关键词"><Input aria-label="行业或关键词" value={keyword} maxLength={100} placeholder="例如：家庭收纳、职场沟通" onChange={e => setKeyword(e.target.value)} /></Field>
        <Button type="primary" htmlType="submit" loading={busy} disabled={active || !keyword.trim()}>搜索作品</Button>
      </form> }]} />
      <p>每次最多50条；搜索最多5页。刷新与搜索仅采集资料，不自动进行 AI 分析。</p>
      {error && <Alert type="error" message={error} action={lastRequest && <Button disabled={busy || active} onClick={() => void run(lastRequest)}>重试提交</Button>} />}
    </section>
    <section className="douyin-panel douyin-form">
      <div className="douyin-section-title"><h2>雷达历史与结果</h2><Button onClick={history.reload}>刷新雷达历史</Button></div>
      <Field label="雷达历史"><Select aria-label="雷达历史" value={history.results.some(t => t.id === taskId) ? taskId : undefined} placeholder="选择一次扫描或选题分析"
        options={history.results.map(t => ({ value: t.id, label: `${labels[t.kind]}${t.output.keyword ? ` · ${t.output.keyword}` : ''} · ${new Date(t.created_at).toLocaleString()} · ${researchTaskStatus(t)}` }))} onChange={selectTask} /></Field>
      {history.error && <Alert type="error" message={history.error} />}<Pager rows={history} />
      {loadError && <Alert type="error" message={loadError} action={<Button onClick={() => setRetry(v => v + 1)}>重试加载</Button>} />}
      {taskId && !task && !loadError && <Spin />}
      {!taskId && !history.loading && <Empty description="还没有扫描记录，刷新热榜或搜索一个关键词开始。" />}
      {task && <>
        <div className="douyin-section-title"><h3>{labels[task.kind]}{task.output.keyword && ` · ${task.output.keyword}`}</h3><Tag>{researchTaskStatus(task)}</Tag></div>
        {active && <div className="douyin-actions" role="status"><Spin size="small" /><span>正在处理，可离开页面后回来查看。</span><Button disabled={busy} onClick={() => { setBusy(true); void client.cancel(task.id).then(() => { setRetry(v => v + 1); history.reload(); }).catch(e => setError(documentError(e))).finally(() => setBusy(false)); }}>取消任务</Button></div>}
        {task.status === 'cancelled' && <Alert type="info" message="任务已取消，已取得的资料保留。重新扫描后可生成建议。" />}
        {task.error && <Alert type="error" message={task.error} />}
        {['failed', 'cancelled'].includes(task.status) && task.output.radar_request && <Button disabled={busy} onClick={() => void run(task.output.radar_request!)}>重新执行</Button>}
        {task.output.warning && <Alert type="warning" message={task.output.warning} />}
        {task.output.note && <p>{task.output.note}</p>}
        {task.status === 'succeeded' && !rows.length && <Empty description="本次未发现结果，可换个关键词或稍后刷新。" />}
        {task.kind !== 'radar_topics' && <>
          <div className="douyin-radar-create"><Field label="关联我的账号（可选）"><Select aria-label="关联我的账号" allowClear value={target} placeholder="不关联，生成通用建议" onChange={setTarget} options={accounts.map(a => ({ value: a.id, label: a.name || a.source_url }))} /></Field>
            <Button type="primary" disabled={!canSelect || !selected.length || busy} loading={busy} onClick={() => void run({ kind: 'radar_topics', source_task_id: task.id, source_ids: selected, ...(target ? { target_account_id: target } : {}) })}>生成选题建议</Button></div>
          {accountError && <Alert type="warning" message={`我的账号加载失败，仍可生成通用建议：${accountError}`} action={<Button onClick={() => setRetry(v => v + 1)}>重试加载账号</Button>} />}
          <p>已选择 {selected.length} / 20 条来源。关联账号后将使用其已有定位、受众、内容支柱和边界。</p>
          <div className="douyin-radar-grid">{rows.map(row => <article className="douyin-research-card" key={row.id}>
            <Checkbox aria-label={`选择 ${row.title}`} checked={selected.includes(row.id)} disabled={!canSelect || busy || (!selected.includes(row.id) && selected.length >= 20)} onChange={e => setSelected(old => e.target.checked ? [...old, row.id] : old.filter(id => id !== row.id))}>选作参考</Checkbox>
            <Source row={row} onKeyword={value => { setTab('search'); setKeyword(value.slice(0, 100)); }} />
          </article>)}</div>
        </>}
        {task.kind === 'radar_topics' && <>
          <p>{task.output.radar_profile ? `关联账号：${task.output.radar_profile.account_name}` : '通用选题建议'} · 建议依据所选资料生成，发布前请核对事实。</p>
          {task.output.source_task_id && <Button onClick={() => selectTask(task.output.source_task_id!)}>返回来源采集</Button>}
          <div className="douyin-radar-grid">{topics.map((topic, index) => <article className="douyin-research-card" key={index}>
            <h3>{topic.title}</h3><p>{topic.angle}</p><blockquote>{topic.hook}</blockquote><p>推荐理由：{topic.reason}</p><p>素材缺口：{topic.materials_needed}</p>
            <details><summary>查看来源依据</summary>{rows.filter(row => topic.refs?.includes(row.id)).map(row => <Source key={row.id} row={row} />)}</details>
            <Button type="primary" disabled={task.status !== 'succeeded' || saving !== null || saved.includes(index)} loading={saving === index} onClick={() => void saveIdea(index)}>{saved.includes(index) ? '已保存到选题库' : '保存到选题库'}</Button>
          </article>)}</div>
        </>}
      </>}
    </section>
  </div>;
}

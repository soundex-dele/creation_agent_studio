import { useEffect, useState } from 'react';
import { Alert, Button, Input, InputNumber, Select, Tag, Tabs } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { douyinLocation } from './navigation';
import { ReferenceRewrite } from './ReferenceRewrite';
import { productionFormats, type ProductionFormat } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { researchLabels } from '@/services/douyinResearch';
import type { CreatorProfile, Idea, ResearchClient, ResearchTask, ResearchVersion } from '@/services/douyinResearch';
import { allRows, DeleteRecord, Field, Pager, RecordEditor, Status, useRows, type EditorField } from './ResearchCommon';
import { KnowledgePicker } from './CreationKnowledge';
import { OrganizationKnowledgePicker } from './OrganizationKnowledge';
import type { OrganizationKnowledgeSnapshot } from '@/services/douyinKnowledge';
import { CasePicker } from './CaseIntegration';
import { casesApi, type CaseReference } from '@/services/cases';
import { knowledgeSelection, type KnowledgeSnapshot } from '@/services/douyinKnowledge';

const profileFields: EditorField[] = [{ key: 'name', label: '档案名称' }, ...Object.entries({ positioning: '账号定位', audience: '目标受众', experiences: '真实经历', products: '产品资料', voice: '表达习惯', conditions: '拍摄条件' }).map(([key, label]) => ({ key, label, kind: 'long' as const })), { key: 'is_default', label: '设为默认档案', kind: 'switch' }];
export function CreatorProfiles({ client }: { client: ResearchClient }) {
  const rows = useRows<CreatorProfile>(client, 'creator-profiles', { unbound: 'true' }); const [editing, setEditing] = useState<object | null>(null);
  return <section className="douyin-form"><div className="douyin-section-title"><h2>独立创作档案</h2><Button type="primary" onClick={() => setEditing({ name: '', is_default: rows.count === 0 })}>新建档案</Button></div><Status loading={rows.loading} error={rows.error} empty={!rows.results.length} /><div className="douyin-research-grid">{rows.results.map(profile => <article key={profile.id} className="douyin-research-card"><h3>{profile.name} {profile.is_default && <Tag>默认</Tag>}</h3><p>{profile.positioning}</p><p>{profile.audience}</p><div className="douyin-actions"><Button onClick={() => setEditing(profile)}>编辑档案</Button><DeleteRecord client={client} resource="creator-profiles" record={profile} done={rows.reload} /></div></article>)}</div><Pager rows={rows} />{editing && <RecordEditor title="创作档案" fields={profileFields} initial={editing} onClose={() => setEditing(null)} onSave={async values => { if (values.id) await client.update('creator-profiles', String(values.id), values); else await client.create('creator-profiles', values); rows.reload(); }} />}</section>;
}

export function CreationCenter({ client, initialIdea, run, onProfiles }: { client: ResearchClient; initialIdea?: Idea | null; run: (body: Record<string, unknown>) => Promise<void>; onProfiles: () => void }) {
  const [params, setParams] = useSearchParams();
  const target = params.get('owned') || '';
  const sourceId = params.get('source') || '';
  const topicIndex = Number(params.get('topic') || 0);
  const mode = params.get('mode') || 'write';
  const initialCase = params.get('case') || '';
  const [cases, setCases] = useState<CaseReference[]>([]);
  const [caseLoading, setCaseLoading] = useState(!!initialCase);
  const [caseError, setCaseError] = useState('');
  useEffect(() => {
    let alive = true;
    if (!initialCase) { setCases([]); setCaseLoading(false); setCaseError(''); return; }
    setCaseLoading(true);
    const ids = initialCase.split(',').map(Number);
    if (ids.length > 3 || ids.some(id => !Number.isInteger(id) || id < 1)) { setCases([]); setCaseError('案例链接无效，请重新选择。'); setCaseLoading(false); return; }
    void Promise.all(ids.map(id => casesApi.detail(id))).then(rows => {
      if (rows.some(row => row.status === 'archived')) throw new Error('案例已归档，请重新选择。');
      if (alive) { setCases(rows.map(row => ({ id: row.id, title: row.title }))); setCaseError(''); }
    }).catch(e => { if (alive) { setCases([]); setCaseError(documentError(e)); } })
      .finally(() => { if (alive) setCaseLoading(false); });
    return () => { alive = false; };
  }, [initialCase]);
  const routeIdea = params.get('idea') || initialIdea?.id || '';
  const [knowledge, setKnowledge] = useState<KnowledgeSnapshot[]>([]);
  const [organizationKnowledge, setOrganizationKnowledge] = useState<OrganizationKnowledgeSnapshot[]>([]);
  const [profiles, setProfiles] = useState<CreatorProfile[]>([]); const [ideas, setIdeas] = useState<Idea[]>([]); const [tasks, setTasks] = useState<ResearchTask[]>([]); const [brands, setBrands] = useState<{ id: string; name: string }[]>([]);
  const [profileId, setProfileId] = useState(params.get('profile') || '');
  const [ideaId, setIdeaId] = useState(routeIdea);
  useEffect(() => { setIdeaId(routeIdea); }, [routeIdea]);
  const [reference, setReference] = useState(mode === 'topics' ? sourceId : ''); const [brandId, setBrandId] = useState<string>();
  const [brief, setBrief] = useState({ positioning: '', audience: '', theme: '', conditions: '', duration: 60, production_format: 'talking_head' as ProductionFormat });
  const [writingRequirements, setWritingRequirements] = useState(''); const [factualMaterial, setFactualMaterial] = useState('');
  const [output, setOutput] = useState<'article' | 'script'>(params.get('output') === 'script' ? 'script' : 'article');
  const [sourceTask, setSourceTask] = useState(''); const [versions, setVersions] = useState<ResearchVersion[]>([]); const [versionId, setVersionId] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    void Promise.all([allRows<CreatorProfile>(client, 'creator-profiles'), allRows<Idea>(client, 'ideas'), allRows<ResearchTask>(client, 'tasks'), client.editor.brands()]).then(([p, i, t, b]) => {
      if (!alive) return; setProfiles(p); setIdeas(i); setTasks(t); setBrands(b);
      const selected = target ? p.find(row => row.account === target) : p.find(row => row.id === profileId && !row.account);
      if (selected) { setProfileId(selected.id); setBrief(old => ({ ...old, positioning: selected.positioning, audience: selected.audience, conditions: selected.conditions })); }
    }).catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // The parent remounts this form when the creator/source URL changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  useEffect(() => { let alive = true; setVersions([]); setVersionId(''); if (sourceTask) void client.versions(sourceTask).then(rows => { if (alive) { setVersions(rows); setVersionId(rows[0]?.id || ''); } }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client, sourceTask]);
  const selectedProfile = profiles.find(p => p.id === profileId);
  const source = tasks.find(t => t.id === sourceId && t.kind === 'topics' && t.status === 'succeeded');
  const selectedTopic = source?.output.topics?.[topicIndex];
  const snapshotAccount = source?.output.creation_context?.target_account_id;
  const validProfile = selectedProfile?.account ? !!selectedProfile.active_version : !target && !!brief.positioning.trim();
  const validSource = !!selectedTopic && (!target || snapshotAccount === target);
  const creatorTasks = tasks.filter(t => target ? t.output.creation_context?.target_account_id === target : !t.output.creation_context?.target_account_id);
  function setContext(key: string, value: string) { setParams(old => { const next = new URLSearchParams(old); next.delete('task'); if (value) next.set(key, value); else next.delete(key); return next; }); }
  function useDirectInput() {
    setIdeaId('');
    setParams(old => { const next = new URLSearchParams(old); for (const key of ['idea', 'source', 'topic', 'task']) next.delete(key); return next; });
  }
  async function start(kind: 'topics' | 'article' | 'script') {
    setBusy(true); setError('');
    try {
      if (kind !== 'topics' && sourceId) await run({ kind, source_task_id: sourceId, topic_index: topicIndex, ...(target && { target_account_id: target }) });
      else await run({ kind, ...brief, ...(cases.length && { case_ids: cases.map(row => row.id) }), ...(profileId && { profile_id: profileId }), ...(target && { target_account_id: target }), ...(ideaId && { idea_id: ideaId }), ...(kind !== 'topics' && { writing_requirements: writingRequirements, factual_material: factualMaterial }), ...(kind === 'topics' && reference && { source_task_id: reference }), ...(brandId && { brand_profile_id: brandId }), ...(knowledge.length && { knowledge_cards: knowledgeSelection(knowledge) }), ...(organizationKnowledge.length && { organization_knowledge_chunks: organizationKnowledge.map(({ chunk_id, revision }) => ({ chunk_id, revision })) }) });
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <section className="douyin-form"><div className="douyin-section-title"><h2>创作中心</h2><Button onClick={onProfiles}>管理定位与文风</Button></div>
    {error && <Alert type="error" message={error} />}
    {caseError && <Alert type="error" message={caseError} action={<Button onClick={() => { setCaseError(''); setContext('case', ''); }}>移除失效案例</Button>} />}
    {!!cases.length && <p>已选参考案例：{cases.map(row => row.title).join('、')}。可在下方参考资料中调整。</p>}
    <Tabs className="douyin-section-tabs" activeKey={mode} onChange={value => setParams(old => douyinLocation(old, 'create', { mode: value, profile: profileId, owned: target, case: initialCase || undefined }))} items={[{ key: 'write', label: '开始写作' }, { key: 'topics', label: '还没想好，生成选题' }, { key: 'rewrite', label: '参考改写' }, { key: 'variants', label: '开头与标题实验室' }]} />
    {mode === 'rewrite' ? <ReferenceRewrite client={client} /> : <>
    <Field label="创作账号或独立档案"><Select aria-label="创作账号或独立档案" loading={loading} value={profileId || undefined} placeholder="先选择为哪个账号创作" options={profiles.map(p => ({ value: p.id, label: `${p.name}${p.account ? ' · 我的账号' : ' · 独立档案'}` }))} onChange={id => {
      const p = profiles.find(row => row.id === id); setProfileId(id); setBrief({ positioning: p?.positioning || '', audience: p?.audience || '', conditions: p?.conditions || '', theme: '', duration: 60, production_format: 'talking_head' }); setKnowledge([]); setOrganizationKnowledge([]); setReference(''); setBrandId(undefined); setIdeaId(''); setSourceTask(''); setWritingRequirements(''); setFactualMaterial('');
      setParams(old => douyinLocation(old, 'create', { profile: id, owned: p?.account || undefined, mode, case: !profileId ? initialCase || undefined : undefined }));
    }} /></Field>
    {target && !selectedProfile && !loading && <Alert type="warning" message="当前账号尚无创作档案，请先建立并确认定位与文风。" />}
    {selectedProfile && !(sourceId && mode === 'write') && <p>当前创作对象：{selectedProfile.name} · {selectedProfile.account ? `文风 ${selectedProfile.active_version_number ? `v${selectedProfile.active_version_number}` : '尚未确认'}` : '独立档案'}。切换创作对象后需重新选择素材。</p>}
    {mode !== 'variants' && <>
      {mode === 'write' && !sourceId && !ideaId && <Field label="这次想写什么"><Input.TextArea aria-label="这次想写什么" rows={3} maxLength={2000} placeholder="输入主题、观点或想回答的问题，即可开始写作" value={brief.theme} onChange={e => setBrief({ ...brief, theme: e.target.value })} /></Field>}
      {sourceId && mode === 'write' ? <Alert type={validSource ? 'info' : 'warning'} message={validSource ? `已选：${selectedTopic?.title}。${source?.output.creation_context ? `账号：${source.output.creation_context.account_name} · 文风 v${source.output.creation_context.voice_version_number}。` : ''}沿用来源选题冻结的资料，不受最新档案变更影响。` : '来源选题不可用或不属于当前账号，请重新选择。'} action={<Button onClick={useDirectInput}>改为直接输入</Button>} /> : <Field label={mode === 'write' ? '从选题库选择（可选）' : '选题库'}><Select aria-label="选题库" allowClear placeholder="也可以使用已保存的选题" value={ideaId || undefined} options={ideas.map(i => ({ value: i.id, label: i.title }))} onChange={id => { setIdeaId(id || ''); setContext('idea', id || ''); }} /></Field>}
      {mode === 'write' && !sourceId && ideaId && <div><p>{ideas.find(i => i.id === ideaId)?.notes || '将按已保存的选题写作。'}</p><Button onClick={useDirectInput}>改为直接输入</Button></div>}
      {mode === 'write' && !sourceId && <details><summary>补充写作要求与真实素材（可选）</summary><div className="douyin-form">
        <Field label="写作角度与要求"><Input.TextArea aria-label="写作角度与要求" rows={3} maxLength={3000} placeholder="例如：重点解释原因，写给新手，约800字" value={writingRequirements} onChange={e => setWritingRequirements(e.target.value)} /></Field>
        <Field label="本次真实素材"><Input.TextArea aria-label="本次真实素材" rows={5} maxLength={10000} placeholder="填写可使用的事实、经历或案例；没有素材可留空" value={factualMaterial} onChange={e => setFactualMaterial(e.target.value)} /></Field>
      </div></details>}
      {mode === 'topics' && <Field label="本次主题（可选）"><Input.TextArea aria-label="本次主题" rows={3} maxLength={2000} value={brief.theme} onChange={e => setBrief({ ...brief, theme: e.target.value })} /></Field>}
      {(mode === 'topics' || !sourceId) && <>
        {!selectedProfile?.account && <div className="douyin-form-grid">{(['positioning', 'audience', 'conditions'] as const).filter(key => key !== 'conditions' || mode === 'topics' || output === 'script').map(key => <Field key={key} label={{ positioning: '本次账号定位', audience: '本次目标受众', conditions: '拍摄条件（可选）' }[key]}><Input.TextArea aria-label={key} rows={3} maxLength={key === 'conditions' ? 3000 : 2000} value={brief[key]} onChange={e => setBrief({ ...brief, [key]: e.target.value })} /></Field>)}</div>}
        <details><summary>参考资料与创作知识（可选）</summary><div className="douyin-form">
          {mode === 'topics' && <Field label="参考研究"><Select aria-label="参考研究" allowClear value={reference || undefined} options={tasks.filter(t => ['breakdown', 'joint', 'radar', 'needs'].includes(t.kind) && t.status === 'succeeded').map(t => ({ value: t.id, label: `${researchLabels[t.kind] || t.kind} · ${new Date(t.created_at).toLocaleString()}` }))} onChange={id => setReference(id || '')} /></Field>}
          {!selectedProfile?.account && <Field label="品牌定位与语气"><Select aria-label="品牌定位与语气" allowClear value={brandId} options={brands.map(b => ({ value: b.id, label: b.name }))} onChange={setBrandId} /></Field>}
          <CasePicker selected={cases} onChange={rows => { setCases(rows); setContext('case', rows.map(row => row.id).join(',')); }} />
          <KnowledgePicker key={profileId} client={client} query={[ideas.find(i => i.id === ideaId)?.title, brief.theme, brief.positioning].filter(Boolean).join(' ')} selected={knowledge} onChange={setKnowledge} organizationCount={organizationKnowledge.length} />
          <OrganizationKnowledgePicker key={`organization-${profileId}`} client={client} query={ideas.find(i => i.id === ideaId)?.title || brief.theme} selected={organizationKnowledge} onChange={setOrganizationKnowledge} personalCount={knowledge.length} />
        </div></details>
      </>}
      <Field label="创作产物"><Select aria-label="创作产物" value={output} onChange={setOutput} options={[{ value: 'article', label: '文章／口播文案' }, { value: 'script', label: '拍摄脚本' }]} /></Field>
      {output === 'script' && (mode === 'topics' || !sourceId) && <div className="douyin-actions"><Field label="视频形式"><Select aria-label="视频形式" value={brief.production_format} options={Object.entries(productionFormats).map(([value, option]) => ({ value, label: option.label }))} onChange={value => setBrief({ ...brief, production_format: value, duration: Math.min(brief.duration, value === 'animation' ? 120 : 600) })} /></Field><Field label="目标时长（秒）"><InputNumber aria-label="目标时长（秒）" min={15} max={brief.production_format === 'animation' ? 120 : 600} value={brief.duration} onChange={value => setBrief({ ...brief, duration: value || 60 })} /></Field></div>}
      {output === 'script' && mode === 'write' && sourceId && <p>拍摄形式与时长沿用来源选题保存的设置。</p>}
      {mode === 'write' ? <Button type="primary" loading={busy} disabled={loading || caseLoading || !!caseError || (sourceId ? !validSource : !validProfile || (ideaId ? !ideas.some(i => i.id === ideaId) : !brief.theme.trim()))} onClick={() => void start(output)}>{output === 'article' ? '开始写作' : '生成拍摄脚本'}</Button> : <Button type="primary" loading={busy} disabled={loading || caseLoading || !!caseError || !validProfile || (!target && !ideaId && !brief.theme.trim())} onClick={() => void start('topics')}>生成3个创作选题</Button>}
    </>}
    {mode === 'variants' && <><h3>开头与标题实验室</h3><p>从当前创作对象的已保存文章、脚本或改写版本生成候选表达。</p>
      <Field label="来源文案"><Select aria-label="来源文案" value={sourceTask || undefined} options={creatorTasks.filter(t => ['article', 'script', 'rewrite'].includes(t.kind) && t.status === 'succeeded').map(t => ({ value: t.id, label: `${t.output.title || '文案'} · ${new Date(t.created_at).toLocaleString()}` }))} onChange={setSourceTask} /></Field>
      <Field label="来源保存版本"><Select aria-label="来源保存版本" value={versionId || undefined} options={versions.map(v => ({ value: v.id, label: `版本${v.revision}` }))} onChange={setVersionId} /></Field>
      <Button disabled={!versionId || busy} loading={busy} onClick={async () => { setBusy(true); setError(''); try { await run({ kind: 'variants', source_version_id: versionId }); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } }}>生成候选表达</Button>
    </>}
    </>}
  </section>;
}

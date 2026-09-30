import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Modal, Spin, Tag } from 'antd';
import { ArrowLeft, ArrowUpRight, BookOpen, History, Sparkles, WandSparkles } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { createUuid } from '@/lib/uuid';
import { blankInput, promptApi, promptError, scenes, type PromptInput, type Template } from '@/services/promptMaster';
import { PromptForm } from './prompt/PromptForm';
import { PromptWorkspace } from './prompt/PromptWorkspace';
import { PromptLibrary } from './prompt/PromptLibrary';
import './PromptMasterPage.css';

const tabs = [
  { id: 'generate', label: '生成提示词', icon: Sparkles }, { id: 'optimize', label: '优化提示词', icon: WandSparkles },
  { id: 'templates', label: '场景模板', icon: BookOpen }, { id: 'library', label: '我的提示词', icon: History },
] as const;
type Tab = typeof tabs[number]['id'];

export function PromptMasterHome({ base }: { base: string }) {
  const client = useMemo(() => promptApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const tab = (tabs.some((t) => t.id === params.get('tab')) ? params.get('tab') : 'generate') as Tab;
  const id = params.get('session');
  const [form, setForm] = useState<PromptInput>(() => blankInput(tab === 'optimize' ? 'optimize' : 'generate'));
  const [templates, setTemplates] = useState<Template[]>([]); const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState(''); const [reloadCatalog, setReloadCatalog] = useState(0);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [dirty, setDirty] = useState(false);
  const updateDirty = useCallback((value: boolean) => setDirty(value), []);
  useEffect(() => {
    let active = true; setCatalogLoading(true);
    void client.catalog().then((value) => { if (active) { setTemplates(value.templates); setCatalogError(''); } })
      .catch((e) => { if (active) setCatalogError(promptError(e)); }).finally(() => { if (active) setCatalogLoading(false); });
    return () => { active = false; };
  }, [client, reloadCatalog]);
  const navigate = (nextTab: Tab, session?: string) => {
    setError('');
    setParams((old) => { const next = new URLSearchParams(old); next.set('tab', nextTab); if (session) next.set('session', session); else next.delete('session'); return next; });
  };
  const leave = (action: () => void) => {
    if (dirty || (!id && (form.topic.trim() || form.original.trim()))) {
      Modal.confirm({ title: '离开当前编辑？', content: '未保存的输入会丢失。已保存的问答和版本仍可在“我的提示词”中找到。', okText: '离开', cancelText: '继续编辑', onOk: action });
    } else action();
  };
  const newTask = (nextTab: Tab, template?: Template) => leave(() => {
    setDirty(false); setForm({ ...blankInput(nextTab === 'optimize' ? 'optimize' : 'generate'), ...(template ? { topic: template.topic, scene: template.scene } : {}) }); navigate(nextTab);
  });
  const create = async () => {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const session = await client.create({ ...form, mode: tab === 'optimize' ? 'optimize' : 'generate' });
      setForm(blankInput(form.mode));
      try { await client.start(session.id, session.revision, 'analyze', createUuid()); }
      catch (e) { setError(promptError(e)); }
      setParams((old) => { const next = new URLSearchParams(old); next.set('session', session.id); next.set('tab', session.mode); return next; });
    } catch (e) { setError(promptError(e)); }
    finally { setBusy(false); }
  };
  return <main className="prompt-master-page app-scroll-page"><div className="pm-container">
    <header className="pm-header"><div>{resolveApplicationPresentation(params).showApplicationHeader && <Link to="/apps" onClick={(e) => { if (dirty) { e.preventDefault(); leave(() => { window.location.assign('/apps'); }); } }}><ArrowLeft size={14} aria-hidden="true" /> 返回应用</Link>}
      <div className="pm-brand"><span className="pm-brand-icon"><Sparkles size={26} aria-hidden="true" /></span><div><span className="pm-eyebrow">把想法说清楚，让 AI 做到位</span><h1>提示词大师</h1></div></div></div>
      {id && <Button disabled={busy} onClick={() => newTask('generate')}>新建提示词</Button>}</header>
    <nav className="pm-tabs" aria-label="提示词大师导航">{tabs.map(({ id: tabId, label, icon: Icon }) => <button key={tabId} aria-current={tab === tabId ? 'page' : undefined} disabled={busy}
      onClick={() => newTask(tabId)}><Icon size={18} aria-hidden="true" /><span>{label}</span></button>)}</nav>
    {error && <Alert type="error" message={error} closable onClose={() => setError('')} />}
    {id ? <PromptWorkspace key={id} client={client} id={id} onDirty={updateDirty} /> : tab === 'library' ? <PromptLibrary client={client} open={(session) => navigate('library', session)} /> : tab === 'templates' ? <section className="pm-templates">
      <div className="pm-intro"><span className="pm-eyebrow">从一个熟悉的场景开始</span><h2>不用从空白页开始</h2><p>选择模板，写下你的具体需求。接下来的问题会根据你的主题调整。</p></div>
      {catalogError ? <Alert type="error" message={catalogError} action={<Button onClick={() => setReloadCatalog((v) => v + 1)}>重试</Button>} /> : catalogLoading ? <Spin /> : <div className="pm-template-grid">{templates.map((template) => <button className="pm-template-card" key={template.id} onClick={() => newTask('generate', template)}>
        <div className="pm-section-heading"><Tag>{scenes[template.scene]}</Tag><ArrowUpRight size={19} aria-hidden="true" /></div><h3>{template.title}</h3><p>{template.topic}</p><span>使用这个模板 →</span></button>)}</div>}
    </section> : <section className="pm-start"><div className="pm-intro"><span className="pm-eyebrow">{tab === 'optimize' ? '让现有提示词更进一步' : '一个主题，几次选择，清晰的提示词'}</span>
      <h2>{tab === 'optimize' ? <>好想法，值得更好的表达。</> : <>你有想法，<br />我们一起把它说清楚。</>}</h2>
      <p>{tab === 'optimize' ? '保留原意与关键约束，找出模糊之处，让下一次回答更贴近目标。' : '写作、编程、学习、办公、绘图、视频。告诉我们你想做什么，剩下的细节一起补齐。'}</p>
      <div className="pm-start-steps"><span>01 描述需求</span><span>02 回答关键问题</span><span>03 复制双版本</span></div>
    </div><div className="pm-card"><PromptForm value={{ ...form, mode: tab === 'optimize' ? 'optimize' : 'generate' }} onChange={setForm} disabled={busy} submit={() => void create()} label={busy ? '正在准备问题…' : tab === 'optimize' ? '分析并优化' : '开始梳理需求'} />
      <p className="pm-footnote">不确定怎么回答也没关系，可以选择“帮我决定”。内容仅自己可见。</p></div></section>}
    <footer className="pm-footer">提示词是起点，实际效果还需要你在目标 AI 中验证。</footer>
  </div></main>;
}

export default function PromptMasterPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((s) => s.currentOrganizationId);
  const userId = useAuthStore((s) => s.user?.id);
  if (!organizationId || !applicationId || !userId) return <div className="prompt-master-page app-scroll-page"><Empty description="请选择组织并登录后使用。" /></div>;
  return <PromptMasterHome key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/prompt-master`} />;
}

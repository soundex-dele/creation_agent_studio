import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Input, Modal, Pagination, Spin } from 'antd';
import { ArrowLeft, BookOpen, Plus } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { documentError } from '@/services/documents';
import { researchApi, type ResearchProject } from '@/services/researchAssistant';
import { ResearchWorkspace } from './research/ResearchWorkspace';
import './ResearchAssistantPage.css';

export function ResearchHome({ base }: { base: string }) {
  const client = useMemo(() => researchApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const projectId = params.get('project'); const resultId = params.get('result'); const citationId = params.get('citation');
  const [projects, setProjects] = useState<ResearchProject[]>([]); const [count, setCount] = useState(0);
  const [search, setSearch] = useState(''); const [page, setPage] = useState(1); const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [createOpen, setCreateOpen] = useState(false); const [title, setTitle] = useState(''); const [creating, setCreating] = useState(false);
  const navigate = (project: string | null, result?: string | null, citation?: string | null) => {
    setParams((old) => { const next = new URLSearchParams(old); for (const [key, value] of [['project', project], ['result', result], ['citation', citation]] as const) { if (value) next.set(key, value); else next.delete(key); } return next; });
  };
  useEffect(() => {
    let active = true; const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true); setError('');
      void client.projects(search, page, controller.signal).then((data) => { if (active) { setProjects(data.results); setCount(data.count); } })
        .catch((e) => { if (active) setError(documentError(e)); }).finally(() => { if (active) setLoading(false); });
    }, 200);
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [client, search, page, version]);
  return <main className="research-host">
    <header className="research-app-header"><div>
      {resolveApplicationPresentation(params).showApplicationHeader && <Link to="/apps"><ArrowLeft size={14} aria-hidden="true" /> 返回应用</Link>}
      <h1><BookOpen size={25} aria-hidden="true" />资料研究助手</h1><p>汇集资料，让每一个关键结论都有出处。</p></div>
      <div className="research-app-actions">{projectId && <Button onClick={() => navigate(null)}>全部项目</Button>}<Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => { setTitle(''); setCreateOpen(true); }}>新建项目</Button></div>
    </header>
    {projectId ? <ResearchWorkspace key={projectId} client={client} projectId={projectId} resultId={resultId} citationId={citationId} navigate={navigate} onChange={() => setVersion((v) => v + 1)} /> : <section className="research-projects" aria-label="研究项目列表">
      <Input.Search aria-label="搜索研究项目" placeholder="搜索项目名称" value={search} allowClear onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
      {error ? <Alert type="error" message={error} action={<Button onClick={() => setVersion((v) => v + 1)}>重试</Button>} /> : loading ? <Spin /> : projects.length ? <div className="research-project-grid">{projects.map((p) => <button key={p.id} className="research-project-card" onClick={() => navigate(p.id)}><BookOpen size={24} aria-hidden="true" /><h2>{p.title}</h2><p>{p.objective || '添加资料，设定研究目标'}</p><time dateTime={p.updated_at}>{new Date(p.updated_at).toLocaleDateString('zh-CN')}</time></button>)}</div> : <div className="research-empty"><Empty description="建立第一个研究项目" /><p>上传报告与文章，对照观点，整理写作依据。<br />资料和历史成果仅自己可见。</p><Button type="primary" onClick={() => setCreateOpen(true)}>新建研究项目</Button></div>}
      <Pagination current={page} total={count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
    </section>}
    <Modal title="新建研究项目" open={createOpen} confirmLoading={creating} onCancel={() => !creating && setCreateOpen(false)} okText="创建项目" okButtonProps={{ disabled: !title.trim() }} onOk={() => {
      setCreating(true); setError(''); void client.create(title.trim()).then((p) => { setCreateOpen(false); setVersion((v) => v + 1); navigate(p.id); }).catch((e) => setError(documentError(e))).finally(() => setCreating(false));
    }}><label htmlFor="new-research-title">项目名称</label><Input id="new-research-title" autoFocus value={title} maxLength={200} placeholder="例如：行业趋势与写作素材" onChange={(e) => setTitle(e.target.value)} />{error && <Alert type="error" message={error} />}</Modal>
  </main>;
}

export default function ResearchAssistantPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((s) => s.currentOrganizationId);
  const userId = useAuthStore((s) => s.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <ResearchHome key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/research-assistant`} />;
}

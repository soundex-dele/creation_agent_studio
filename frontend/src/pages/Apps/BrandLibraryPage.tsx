import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Pagination, Popconfirm, Space, Spin, Tabs, Typography } from 'antd';
import { ArrowLeftOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useBlocker, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '@/services/api';
import { brandModules, brandSections, type BrandItem, type BrandPage, type BrandProfile, type BrandSection } from '@/services/brandLibrary';
import { entryError } from '@/services/ideasTodos';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import './BrandLibraryPage.css';

type Kind = 'profiles' | 'products' | 'examples';
interface Editor { kind: Kind; item?: BrandProfile | BrandItem }
const productFields = { description: '产品介绍', facts: '事实条目（每行一条）', source: '来源说明', restrictions: '使用限制', prohibited_claims: '禁止承诺' };
const exampleFields = { platform: '平台', body: '范文正文', source_url: '来源链接', highlights: '值得借鉴的特点' };

function BrandEditor({ editor, base, onClose, onSaved, setDirty }: {
  editor: Editor; base: string; onClose: () => void; onSaved: (item: BrandProfile | BrandItem) => void; setDirty: (value: boolean) => void;
}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const initialValues = useMemo(() => ({ ...editor.item,
    ...(editor.kind === 'products' ? { facts: (editor.item as BrandItem | undefined)?.facts?.join('\n') || '' } : {}),
  }), [editor]);
  const save = async () => {
    const valid = await form.validateFields().catch(() => null);
    if (!valid) return;
    // Preserve sections that have not been opened without mounting every textarea.
    const values = form.getFieldsValue(true);
    if (editor.kind === 'products') values.facts = String(values.facts || '').split('\n').map((line) => line.trim()).filter(Boolean);
    setSaving(true); setError('');
    try {
      const url = `${base}/${editor.kind}`;
      const saved = editor.item
        ? await api.patch<BrandProfile | BrandItem>(`${url}/${editor.item.id}`, values)
        : await api.post<BrandProfile | BrandItem>(url, values);
      setDirty(false); onSaved(saved);
    } catch (failure) { setError(entryError(failure)); }
    finally { setSaving(false); }
  };
  const label = editor.kind === 'profiles' ? '品牌档案' : brandModules[editor.kind];
  return <Modal open title={`${editor.item ? '编辑' : '新增'}${label}`} width={760}
    onCancel={() => { if (!saving) onClose(); }} maskClosable={false} closable={!saving}
    footer={<Space><Button disabled={saving} onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></Space>}>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    <Form form={form} layout="vertical" initialValues={initialValues} onValuesChange={() => setDirty(true)} disabled={saving}>
      <Form.Item name="name" label={editor.kind === 'examples' ? '范文标题' : '名称'} rules={[{ required: true, whitespace: true, message: '请填写名称' }, { max: 200 }]}>
        <Input maxLength={200} autoFocus placeholder={editor.kind === 'profiles' ? '例如：我的成长账号' : '为这条资料命名'} />
      </Form.Item>
      {editor.kind === 'profiles' ? <Tabs items={(Object.keys(brandSections) as BrandSection[]).map((section) => ({
        key: section, label: brandModules[section],
        children: Object.entries(brandSections[section]).map(([key, label]) => <Form.Item key={key} name={[section, key]} label={label}>
          <Input.TextArea maxLength={4000} autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>),
      }))} /> : Object.entries(editor.kind === 'products' ? productFields : exampleFields).map(([key, label]) => (
        <Form.Item key={key} name={key} label={label} rules={key === 'source_url' ? [{ type: 'url', message: '请输入完整的 http 或 https 链接' }] : []}>
          <Input.TextArea maxLength={key === 'body' ? 30000 : key === 'facts' ? 200100 : key === 'platform' ? 200 : key === 'source_url' ? 2000 : 4000}
            autoSize={{ minRows: key === 'body' ? 8 : 2, maxRows: 12 }} />
        </Form.Item>
      ))}
    </Form>
  </Modal>;
}

function BrandItems({ base, kind, onEdit, onChanged }: {
  base: string; kind: 'products' | 'examples'; onEdit: (editor: Editor) => void; onChanged: () => void;
}) {
  const [items, setItems] = useState<BrandItem[]>([]);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setItems([]);
    void api.get<BrandPage<BrandItem>>(`${base}/${kind}`, { page }, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) { setItems(result.results); setCount(result.count); } })
      .catch((failure) => { if (!controller.signal.aborted) setError(entryError(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [base, kind, page, reload]);
  const remove = async (id: string) => {
    setBusy(true); setError('');
    try { await api.delete(`${base}/${kind}/${id}`); setPage(1); setReload((n) => n + 1); onChanged(); }
    catch (failure) { setError(entryError(failure)); }
    finally { setBusy(false); }
  };
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Button icon={<PlusOutlined />} onClick={() => onEdit({ kind })}>新增{brandModules[kind]}</Button>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setReload((n) => n + 1)}>重试</Button>} />}
    <List loading={loading} dataSource={items} locale={{ emptyText: `暂未添加${brandModules[kind]}` }} renderItem={(item) => <List.Item actions={[
      <Button key="edit" aria-label={`编辑${item.name}`} icon={<EditOutlined />} onClick={() => onEdit({ kind, item })} />,
      <Popconfirm key="delete" title={`删除“${item.name}”？`} description="已发送到对话的内容会保留。" onConfirm={() => remove(item.id)}>
        <Button danger disabled={busy} aria-label={`删除${item.name}`} icon={<DeleteOutlined />} />
      </Popconfirm>,
    ]}>
      <List.Item.Meta title={item.name} description={<div className="brand-library-excerpt">{kind === 'products' ? item.description || item.facts?.join('\n') : item.body || item.highlights}</div>} />
    </List.Item>} />
    <Pagination current={page} pageSize={20} total={count} onChange={setPage} showSizeChanger={false} hideOnSinglePage />
  </Space>;
}

export function BrandLibraryWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState<BrandProfile[]>([]);
  const [selected, setSelected] = useState<BrandProfile | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [reload, setReload] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [dirty, setDirty] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const blocker = useBlocker(dirty);
  useEffect(() => {
    if (blocker.state === 'blocked') {
      if (window.confirm('资料尚未保存，确定离开并放弃修改？')) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = window.setTimeout(() => {
      void api.get<BrandPage<BrandProfile>>(`${base}/profiles`, { search, page }, { signal: controller.signal })
        .then((result) => { if (!controller.signal.aborted) { setProfiles(result.results); setCount(result.count); } })
        .catch((failure) => { if (!controller.signal.aborted) setError(entryError(failure)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, search ? 250 : 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [base, search, page, reload]);
  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    void api.get<BrandProfile>(`${base}/profiles/${selectedId}`, undefined, { signal: controller.signal })
      .then((profile) => { if (!controller.signal.aborted) setSelected(profile); })
      .catch((failure) => { if (!controller.signal.aborted) { setError(entryError(failure)); setSelected(null); } });
    return () => controller.abort();
  }, [base, selectedId, reload]);
  const openEditor = (value: Editor) => { setSuccess(''); setDirty(false); setEditor(value); };
  const closeEditor = () => {
    if (dirty && !window.confirm('资料尚未保存，确定放弃修改？')) return;
    setDirty(false); setEditor(null);
  };
  const remove = async () => {
    if (!selected) return;
    setDeleting(true); setError('');
    try { await api.delete(`${base}/profiles/${selected.id}`); setSelected(null); setPage(1); setReload((n) => n + 1); setSuccess('档案已删除'); }
    catch (failure) { setError(entryError(failure)); }
    finally { setDeleting(false); }
  };
  return <div className="brand-library-page">
    <header className="brand-library-header"><div>
      {showHeader && <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>返回应用</Button>}
      <h1>品牌资料库</h1><p>把定位、事实与风格沉淀下来，让每次创作保持一致。资料仅自己可见。</p>
    </div><Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor({ kind: 'profiles' })}>新建档案</Button></header>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setReload((n) => n + 1)}>重试</Button>} />}
    {success && <Alert type="success" message={success} closable />}
    <div className="brand-library-columns">
      <aside className="brand-library-list">
        <Input.Search aria-label="搜索品牌档案" placeholder="搜索品牌或账号" maxLength={200} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} allowClear />
        {loading ? <Spin /> : <List dataSource={profiles} locale={{ emptyText: search ? '没有匹配的档案' : '从第一份品牌档案开始' }} renderItem={(profile) => (
          <List.Item><button className={`brand-library-select ${profile.id === selected?.id ? 'is-selected' : ''}`} onClick={() => setSelected(profile)} aria-pressed={profile.id === selected?.id}>
            <strong>{profile.name}</strong><span>{profile.positioning.platform || '品牌 / 账号'} · {new Date(profile.updated_at).toLocaleDateString()}</span>
          </button></List.Item>
        )} />}
        <Pagination current={page} pageSize={20} total={count} onChange={setPage} showSizeChanger={false} hideOnSinglePage simple />
      </aside>
      <main className="brand-library-detail">{selected ? <>
        <div className="brand-library-detail-heading"><div><h2>{selected.name}</h2><Typography.Text type="secondary">更新于 {new Date(selected.updated_at).toLocaleString()}</Typography.Text></div>
          <Space><Button icon={<EditOutlined />} onClick={() => openEditor({ kind: 'profiles', item: selected })}>编辑档案</Button>
            <Popconfirm title="删除整份品牌档案？" description="产品和范文一并删除，已发送到对话的内容会保留。" onConfirm={remove}><Button danger loading={deleting}>删除</Button></Popconfirm></Space>
        </div>
        <Tabs key={selected.id} items={Object.entries(brandModules).map(([module, label]) => ({ key: module, label,
          children: module === 'products' || module === 'examples' ? <BrandItems key={`${selected.id}:${module}:${reload}`} base={`${base}/profiles/${selected.id}`} kind={module} onEdit={openEditor} onChanged={() => setReload((n) => n + 1)} /> :
            <div className="brand-library-fields">{Object.entries(brandSections[module as BrandSection]).map(([key, fieldLabel]) => <Card size="small" key={key} title={fieldLabel}>
              <div className="brand-library-value">{selected[module as BrandSection][key] || <Typography.Text type="secondary">尚未填写</Typography.Text>}</div>
            </Card>)}</div>,
        }))} />
      </> : <Empty description="选择一份档案查看，或新建你的品牌资料。" />}</main>
    </div>
    {editor && <BrandEditor editor={editor} base={editor.kind === 'profiles' ? base : `${base}/profiles/${selected?.id}`}
      setDirty={setDirty} onClose={closeEditor} onSaved={(saved) => {
        if (editor.kind === 'profiles') { setSelected(saved as BrandProfile); setPage(1); setSearch(''); }
        setEditor(null); setSuccess('资料已保存'); setReload((n) => n + 1);
      }} />}
  </div>;
}

export default function BrandLibraryPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <BrandLibraryWorkspace key={`${organizationId}:${applicationId}:${userId}`}
    base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/brand-library`}
    showHeader={resolveApplicationPresentation(searchParams).showApplicationHeader} />;
}

import { useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, Modal, Pagination, Select, Space, Spin } from 'antd';
import { Folder } from 'lucide-react';
import { documentError } from '@/services/documents';
import { researchApi, type ImportEntry, type ResearchIntegration } from '@/services/researchAssistant';

export function ImportPicker({ client, integrations, onClose, onImport }: {
  client: ReturnType<typeof researchApi>; integrations: ResearchIntegration[]; onClose: () => void;
  onImport: (integration: ResearchIntegration, entries: ImportEntry[]) => Promise<void>;
}) {
  const [application, setApplication] = useState<number | undefined>(integrations[0]?.id);
  const [search, setSearch] = useState(''); const [page, setPage] = useState(1);
  const [folders, setFolders] = useState<ImportEntry[]>([]);
  const [entries, setEntries] = useState<ImportEntry[]>([]); const [count, setCount] = useState(0);
  const [selected, setSelected] = useState<ImportEntry[]>([]);
  const [loading, setLoading] = useState(false); const [saving, setSaving] = useState(false); const [error, setError] = useState('');
  const integration = integrations.find((i) => i.id === application);
  const parent = folders[folders.length - 1]?.id;
  useEffect(() => {
    if (!integration) return;
    const controller = new AbortController(); let active = true;
    const timer = setTimeout(() => {
      setLoading(true); setError('');
      void client.imports({ target: integration.target, application_id: integration.id, search, page, parent }, controller.signal)
        .then((data) => { if (active) { setEntries(data.results); setCount(data.count); } })
        .catch((e) => { if (active) setError(documentError(e)); }).finally(() => { if (active) setLoading(false); });
    }, 200);
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [client, integration, search, page, parent]);
  return <Modal open title="从已有资料导入" onCancel={saving ? undefined : onClose} maskClosable={!saving}
    confirmLoading={saving} okText={`导入 ${selected.length} 份资料`} okButtonProps={{ disabled: !selected.length || !integration }}
    onOk={() => { if (!integration) return; setSaving(true); setError(''); void onImport(integration, selected).then(onClose).catch((e) => setError(documentError(e))).finally(() => setSaving(false)); }}>
    <Space direction="vertical" style={{ width: '100%' }}>
      <p>导入当前版本的独立副本，原文后续修改不会改变历史出处。</p>
      <Select aria-label="来源应用" style={{ width: '100%' }} value={application} disabled={saving}
        options={integrations.map((i) => ({ value: i.id, label: i.name }))}
        onChange={(id) => { setApplication(id); setSelected([]); setFolders([]); setPage(1); }} />
      <Input.Search aria-label="搜索已有资料" placeholder="搜索资料标题" value={search} disabled={saving} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
      {parent && <Button disabled={saving} onClick={() => { setFolders((old) => old.slice(0, -1)); setPage(1); }}>返回上一级 · {folders[folders.length - 1]?.title}</Button>}
      {error && <Alert type="error" message={error} />}
      {loading ? <Spin /> : entries.length ? <ul className="research-import-list">{entries.map((entry) => <li key={entry.id}>
        {entry.kind === 'folder' ? <Button type="text" disabled={saving} icon={<Folder size={16} aria-hidden="true" />} onClick={() => { setFolders((old) => [...old, entry]); setSearch(''); setPage(1); }}>{entry.title}</Button>
          : <Checkbox disabled={saving || (integration?.target === 'drive' && !/\.(pdf|docx|txt|md|markdown)$/i.test(entry.title))}
            checked={selected.some((s) => s.id === entry.id)} onChange={(e) => setSelected((old) => e.target.checked ? [...old, entry] : old.filter((s) => s.id !== entry.id))}>{entry.title}</Checkbox>}
      </li>)}</ul> : <Empty description="没有可导入的资料" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      <Pagination current={page} total={count} pageSize={20} showSizeChanger={false} onChange={setPage} hideOnSinglePage />
    </Space>
  </Modal>;
}

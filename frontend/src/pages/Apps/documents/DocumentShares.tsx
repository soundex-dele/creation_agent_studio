import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Empty, Modal, Select, Space } from 'antd';
import { documentError, documentsApi, type DocumentMember, type DocumentShare } from '@/services/documents';

export function DocumentShares({ base, id, onClose }: { base: string; id: string; onClose: () => void }) {
  const client = useMemo(() => documentsApi(base), [base]);
  const [members, setMembers] = useState<DocumentMember[]>([]);
  const [shares, setShares] = useState<DocumentShare[]>([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<number>();
  const [role, setRole] = useState('viewer');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => { void client.members(search).then((items) => { if (active) setMembers(items); }).catch((e) => { if (active) setError(documentError(e)); }); }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [client, search]);
  useEffect(() => { let active = true; void client.shares(id).then((items) => { if (active) setShares(items); }).catch((e) => { if (active) setError(documentError(e)); }); return () => { active = false; }; }, [client, id]);
  const change = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await operation(); setShares(await client.shares(id)); } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  };
  return <Modal title="共享文档" open onCancel={onClose} footer={<Button onClick={onClose}>完成</Button>}>
    <p>仅指定成员可以访问。对方也需要拥有“在线文档”应用的使用权限。AI 对话仅自己可见。</p>
    {error && <Alert type="error" message={error} />}
    <Space wrap className="documents-share-add">
      <Select aria-label="选择组织成员" placeholder="搜索组织成员" showSearch filterOption={false} onSearch={setSearch} value={selected} onChange={setSelected} style={{ minWidth: 180 }} options={members.map((m) => ({ value: m.user_id, label: m.user__username }))} />
      <Select aria-label="成员权限" value={role} onChange={setRole} options={[{ value: 'viewer', label: '只读' }, { value: 'editor', label: '可编辑' }]} />
      <Button type="primary" disabled={!selected || busy} onClick={() => void change(() => client.grant(id, selected!, role))}>授权</Button>
    </Space>
    {shares.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="文档尚未共享" /> : <ul className="documents-shares">
      {shares.map((share) => <li key={share.user_id}><span>{share.user__username}</span><Select aria-label={`${share.user__username}的权限`} disabled={busy} value={share.role} onChange={(value) => void change(() => client.grant(id, share.user_id, value))} options={[{ value: 'viewer', label: '只读' }, { value: 'editor', label: '可编辑' }]} /><Button disabled={busy} onClick={() => void change(() => client.revoke(id, share.user_id))}>撤销</Button></li>)}
    </ul>}
  </Modal>;
}

import { useState } from 'react';
import { Alert, Button, Modal, Select } from 'antd';
import { casesApi } from '@/services/cases';
import { documentError } from '@/services/documents';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';

export default function CaseCreationAction({ caseId }: { caseId: number }) {
  const navigate = useApplicationNavigate();
  const [busy, setBusy] = useState(false); const [open, setOpen] = useState(false);
  const [targets, setTargets] = useState<{ id: number; name: string }[]>([]);
  const [target, setTarget] = useState<number>(); const [error, setError] = useState('');
  const enter = (id: number) => navigate(`/applications/${id}/douyin-benchmark?view=create&mode=write&case=${caseId}`);
  async function discover() {
    setBusy(true); setError('');
    try {
      const rows = await casesApi.applications();
      if (rows.length === 1) { enter(rows[0].id); return; }
      setTargets(rows); setTarget(undefined); setOpen(true);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <>
    <Button type="primary" loading={busy} onClick={() => void discover()}>用于创作</Button>
    {error && <Alert type="error" message={error} />}
    <Modal title="选择抖音对标助手" open={open} onCancel={() => setOpen(false)} okText="进入创作中心" okButtonProps={{ disabled: !target }} onOk={() => target && enter(target)}>
      {targets.length ? <label className="case-library-filter">目标应用<Select aria-label="目标抖音助手" value={target} options={targets.map(row => ({ value: row.id, label: row.name }))} onChange={setTarget} /></label> : <Alert type="info" message="当前组织暂无你可运行的抖音对标助手。请在应用中心启用应用或联系管理员授权。" />}
    </Modal>
  </>;
}

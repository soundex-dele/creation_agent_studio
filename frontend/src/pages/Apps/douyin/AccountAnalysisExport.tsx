import { useRef, useState } from 'react';
import { Alert, Button } from 'antd';
import { Download } from 'lucide-react';
import type { DouyinAccount, DouyinClient, DouyinTask } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { saveResearchBlob } from '@/services/researchAssistant';

export function AccountAnalysisExport({ client, account, task }: { client: DouyinClient; account: DouyinAccount; task: DouyinTask }) {
  const pending = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const available = task.kind === 'account' && task.status === 'succeeded' && !!task.output.claims?.length;
  const download = async () => {
    if (!available || pending.current) return;
    pending.current = true; setLoading(true); setError('');
    try {
      const blob = await client.downloadAccountAnalysis(account.id, task.id);
      // Limit the name before appending the stable task date and identifier.
      const name = (account.name || '未命名账号').replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, '_').slice(0, 80); // eslint-disable-line no-control-regex
      saveResearchBlob(blob, `${name}-账号分析-${task.created_at.slice(0, 10)}-${task.id.slice(0, 8)}.md`);
    } catch (failure) {
      const data = (failure as { response?: { data?: unknown } })?.response?.data;
      let message = '';
      if (data instanceof Blob) {
        try { message = documentError({ response: { data: JSON.parse(await data.text()) } }); }
        catch { /* Non-JSON download failures use the normal error message below. */ }
      }
      setError(message || (data instanceof Blob ? documentError(new Error('导出失败，请稍后重试。')) : documentError(failure)));
    } finally { pending.current = false; setLoading(false); }
  };
  return <div className="douyin-analysis-export">
    <Button icon={<Download size={15} aria-hidden="true" />} loading={loading} disabled={!available || loading} onClick={() => void download()}>导出 Markdown</Button>
    {error && <Alert type="error" showIcon message={error} />}
  </div>;
}

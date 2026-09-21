import { useEffect, useState } from 'react';
import { Alert, Button, Card, Empty, Image, Space, Spin, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import type { RunArtifact } from '@/services/applicationRuntime';
import { canPreviewArtifact, getRunArtifactAccess, listRunArtifacts } from '@/services/runArtifacts';

function ArtifactItem({ organizationId, artifact }: { organizationId: string; artifact: RunArtifact }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const filename = String(artifact.metadata.filename || artifact.kind);
  const { id, run_id: runId } = artifact;
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    setError(false);
    getRunArtifactAccess(organizationId, { id, run_id: runId }).then((access) => {
      if (disposed) return;
      setUrl(access.url);
      const remaining = Date.parse(access.expires_at) - Date.now() - 15000;
      if (Number.isFinite(remaining)) {
        timer = setTimeout(() => setRefresh((value) => value + 1), Math.max(10000, remaining));
      }
    }).catch(() => { if (!disposed) { setUrl(''); setError(true); } });
    return () => { disposed = true; clearTimeout(timer); };
  }, [organizationId, id, runId, refresh]);

  return <Card size="small" title={<span style={{ overflowWrap: 'anywhere' }}>{filename}</span>}>
    <Space direction="vertical" style={{ width: '100%' }}>
      {url && canPreviewArtifact(artifact) && <Image
        src={url} alt={filename} width="100%"
        style={{ height: 180, objectFit: 'contain', background: 'var(--color-bg-elevated)' }}
      />}
      <Typography.Text type="secondary">{artifact.mime_type} · {(artifact.size / 1024).toFixed(1)} KB</Typography.Text>
      {error ? <Button onClick={() => setRefresh((value) => value + 1)}>加载失败，重试</Button>
        : <Button href={url || undefined} target="_blank" rel="noopener noreferrer"
          disabled={!url} icon={<DownloadOutlined />}>下载</Button>}
    </Space>
  </Card>;
}

export default function RunArtifacts({ organizationId, runId, active = false, includeDescendants = false }: {
  organizationId: string;
  runId: string;
  active?: boolean;
  includeDescendants?: boolean;
}) {
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result = await listRunArtifacts(organizationId, runId, includeDescendants);
        if (!disposed) { setArtifacts(result); setError(''); }
      } catch {
        if (!disposed) setError('输出文件加载失败，请刷新重试');
      } finally {
        if (!disposed) {
          setLoading(false);
          if (active) timer = setTimeout(() => void load(), 5000);
        }
      }
    };
    void load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [organizationId, runId, includeDescendants, active, refresh]);

  return <Card title={`输出文件${artifacts.length ? ` (${artifacts.length})` : ''}`}
    extra={<Button icon={<ReloadOutlined />} onClick={() => setRefresh((value) => value + 1)}>刷新</Button>}>
    {error && <Alert type="warning" showIcon message={error} style={{ marginBottom: 12 }} />}
    {loading ? <Spin /> : artifacts.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={active ? '生成的文件会自动显示在这里' : '暂无输出文件'} /> : (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 260px), 1fr))', gap: 16 }}>
        {artifacts.map((artifact) => <ArtifactItem key={artifact.id} organizationId={organizationId} artifact={artifact} />)}
      </div>
    )}
  </Card>;
}

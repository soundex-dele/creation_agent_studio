import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, Select, Progress, Table, Spin, Result, message } from 'antd';
import { ArrowLeftOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '@/stores/useAppStore';
import { useRunStream } from '@/hooks/useRunStream';
import { api } from '@/services/api';
import type { AppItem } from '@/types';
import { useApplicationRuntime } from '@/components/Applications/ApplicationRuntimeContext';
import FolderPickerModal from './FolderPickerModal';
import './BatchTranscribeRunner.css';

const SLUG = 'batch-transcribe';

interface BatchTranscribeRunnerProps {
  application?: AppItem;
  embedded?: boolean;
}

const BatchTranscribeRunner: React.FC<BatchTranscribeRunnerProps> = ({ application, embedded }) => {
  const navigate = useNavigate();
  const { loadApp } = useAppStore();
  const runtime = useApplicationRuntime();
  const [runId, setRunId] = useState<string | null>(null);
  const projection = useRunStream({
    organizationId: runtime.organizationId,
    runId,
  });

  const [app, setApp] = useState<AppItem | null>(application ?? null);
  const [loadingApp, setLoadingApp] = useState(!application);
  const [folder, setFolder] = useState('');
  const [model, setModel] = useState('base');
  const [language, setLanguage] = useState('zh');
  const [videos, setVideos] = useState<{ name: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (application) {
      setApp(application);
      setLoadingApp(false);
      return;
    }
    loadApp(SLUG).then(setApp).finally(() => setLoadingApp(false));
  }, [application, loadApp]);

  const scan = async (p: string = folder) => {
    const target = p.trim();
    if (!target) return;
    const data = await api.post<{ videos: { name: string }[] }>('/apps/runtime-files/scan/', { path: target });
    setVideos(data.videos);
  };

  if (loadingApp) return <div className="bt-runner"><Spin size="large" /></div>;
  if (!app) return (
    <div className="bt-runner">
      <Result status="404" title="应用不存在"
        extra={<Button type="primary" onClick={() => navigate('/apps')}>返回应用中心</Button>} />
    </div>
  );

  const status = projection.state.status ?? (runId ? 'queued' : 'idle');
  const isRunning = Boolean(
    runId && ['queued', 'running', 'cancelling'].includes(status),
  );
  const progressCurrent = Number(projection.state.progress?.current ?? 0);
  const progressTotal = Number(projection.state.progress?.total ?? 0);
  const pct = progressTotal > 0
    ? Math.min(100, Math.round((progressCurrent / progressTotal) * 100))
    : 0;
  const items = useMemo(() => Object.entries(projection.state.tools).map(([id, tool]) => ({
    id,
    name: String(tool.name ?? id),
    status: tool.event_type === 'tool.completed'
      ? 'done'
      : tool.event_type === 'tool.failed' ? 'error' : 'running',
    result: String(tool.result ?? ''),
    error: String(tool.error ?? ''),
  })), [projection.state.tools]);

  return (
    <div className="bt-runner animate-fade-in">
      {!embedded && <div className="bt-runner-topbar">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
          返回应用中心
        </Button>
        <div className="bt-runner-app"><span>{app.icon}</span><span>{app.name}</span></div>
      </div>}

      <div className="bt-runner-config">
        <div className="bt-runner-row">
          <Input
            placeholder="服务器视频文件夹路径（如 D:\\videos）"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            style={{ flex: 1 }}
          />
          <Button icon={<FolderOpenOutlined />} onClick={() => setPickerOpen(true)}>打开</Button>
          <Button onClick={() => scan()}>扫描</Button>
        </div>
        <div className="bt-runner-row">
          <Select value={model} onChange={setModel} style={{ width: 140 }}
            options={['tiny', 'base', 'small', 'medium', 'large'].map((m) => ({ value: m, label: m }))} />
          <Select value={language} onChange={setLanguage} style={{ width: 140 }}
            options={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} />
          <Button type="primary" disabled={isRunning || submitting || videos.length === 0}
            onClick={async () => {
              setSubmitting(true);
              try {
                const run = await runtime.startRun(
                  { folder: folder.trim(), model, language },
                  crypto.randomUUID(),
                );
                setRunId(run.id);
              } catch (error) {
                message.error(error instanceof Error ? error.message : '启动转录失败');
              } finally {
                setSubmitting(false);
              }
            }}>
            开始转录
          </Button>
          <Button danger disabled={!isRunning || !runId} onClick={async () => {
            if (!runId) return;
            try {
              await runtime.sendCommand(runId, {
                type: 'cancel',
                idempotency_key: crypto.randomUUID(),
                payload: { reason: 'user_requested' },
              });
            } catch (error) {
              message.error(error instanceof Error ? error.message : '停止转录失败');
            }
          }}>停止</Button>
        </div>
        {videos.length > 0 && <div className="bt-runner-hint">找到 {videos.length} 个视频文件</div>}
      </div>

      <div className="bt-runner-progress">
        <Progress percent={pct} status={status === 'failed' ? 'exception' : isRunning ? 'active' : 'normal'} />
        <span className="bt-runner-status">{status}</span>
      </div>

      <Table
        size="small" rowKey="id" pagination={false}
        dataSource={items}
        columns={[
          { title: '文件名', dataIndex: 'name' },
          { title: '状态', dataIndex: 'status', width: 100 },
          { title: '输出路径', dataIndex: 'result' },
          { title: '错误', dataIndex: 'error' },
        ]}
      />

      <div className="bt-runner-log">
        {projection.state.output.split('\n').filter(Boolean).map((line, index) => (
          <div key={index} className="bt-runner-log-line lvl-info">{line}</div>
        ))}
      </div>

      <FolderPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(p) => {
          setFolder(p);
          setPickerOpen(false);
          scan(p);
        }}
      />
    </div>
  );
};

export default BatchTranscribeRunner;

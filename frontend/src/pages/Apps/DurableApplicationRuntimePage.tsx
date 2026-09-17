import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  List,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import {
  ApplicationRuntimeProvider,
  useApplicationRuntime,
} from '@/components/Applications/ApplicationRuntimeContext';
import { useRunStream } from '@/features/run-stream';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import {
  loadApplicationRuntime,
  type ApplicationRuntimeDescriptor,
  type RunArtifact,
  type RunResource,
} from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import FolderPickerModal from './FolderPickerModal';


interface HtmlToPngInputProps {
  loading: boolean;
  onStart: (input: Record<string, unknown>) => void;
}

function HtmlToPngInput({ loading, onStart }: HtmlToPngInputProps) {
  const [directories, setDirectories] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [orientation, setOrientation] = useState<'horizontal' | 'vertical'>('horizontal');
  const [width, setWidth] = useState<number | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [scale, setScale] = useState(2);
  const [selector, setSelector] = useState('.cover');
  const [waitUntil, setWaitUntil] = useState('networkidle');
  const [fullPage, setFullPage] = useState(false);
  const [transparent, setTransparent] = useState(false);
  const [noWebFonts, setNoWebFonts] = useState(false);

  const updateDirectory = (index: number, value: string) => {
    setDirectories((current) => current.map((item, itemIndex) => (
      itemIndex === index ? value : item
    )));
  };
  const addDirectory = (path = '') => {
    setDirectories((current) => (
      path && current.includes(path) ? current : [...current, path]
    ));
  };
  const submit = () => {
    const cleaned = directories.map((item) => item.trim()).filter(Boolean);
    if (cleaned.length === 0) {
      message.warning('请至少添加一个 HTML 目录');
      return;
    }
    onStart({
      directories: cleaned,
      orientation,
      ...(width ? { width } : {}),
      ...(height ? { height } : {}),
      device_scale_factor: scale,
      selector,
      wait_until: waitUntil,
      full_page: fullPage,
      transparent,
      no_web_fonts: noWebFonts,
    });
  };

  return (
    <Card title="转换设置">
      <Typography.Text strong>HTML 目录</Typography.Text>
      <Typography.Paragraph type="secondary" style={{ margin: '4px 0 12px' }}>
        每个目录的直属 HTML 文件会生成同名 PNG，输出在原目录中。
      </Typography.Paragraph>
      <Space direction="vertical" style={{ width: '100%' }}>
        {directories.map((directory, index) => (
          <Space.Compact key={index} style={{ width: '100%' }}>
            <Input
              value={directory}
              placeholder="输入或选择服务器上的目录"
              onChange={(event) => updateDirectory(index, event.target.value)}
            />
            <Button
              aria-label="删除目录"
              icon={<DeleteOutlined />}
              onClick={() => setDirectories((current) => (
                current.filter((_, itemIndex) => itemIndex !== index)
              ))}
            />
          </Space.Compact>
        ))}
        <Space wrap>
          <Button icon={<FolderOpenOutlined />} onClick={() => setPickerOpen(true)}>
            选择目录
          </Button>
          <Button icon={<PlusOutlined />} onClick={() => addDirectory()}>
            手动添加
          </Button>
        </Space>
      </Space>

      <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 24 }}>
        <Space wrap>
          <Typography.Text>画面方向</Typography.Text>
          <Radio.Group value={orientation} onChange={(event) => setOrientation(event.target.value)}>
            <Radio.Button value="horizontal">横版 1283×383</Radio.Button>
            <Radio.Button value="vertical">竖版 1080×1440</Radio.Button>
          </Radio.Group>
        </Space>
        <Space wrap>
          <Typography.Text>自定义尺寸</Typography.Text>
          <InputNumber min={1} max={10000} placeholder="宽度" value={width}
            onChange={(value) => setWidth(value)} />
          <Typography.Text>×</Typography.Text>
          <InputNumber min={1} max={10000} placeholder="高度" value={height}
            onChange={(value) => setHeight(value)} />
          <Typography.Text>像素倍率</Typography.Text>
          <InputNumber min={1} max={4} step={0.5} value={scale}
            onChange={(value) => setScale(value ?? 2)} />
        </Space>
        <Space wrap>
          <Typography.Text>截图元素</Typography.Text>
          <Input style={{ width: 220 }} value={selector} placeholder="例如 .cover"
            disabled={fullPage} onChange={(event) => setSelector(event.target.value)} />
          <Typography.Text>页面等待</Typography.Text>
          <Select style={{ width: 180 }} value={waitUntil} onChange={setWaitUntil} options={[
            { value: 'networkidle', label: '网络空闲' },
            { value: 'load', label: '页面加载完成' },
            { value: 'domcontentloaded', label: 'DOM 加载完成' },
          ]} />
        </Space>
        <Space wrap size="large">
          <Checkbox checked={fullPage} onChange={(event) => setFullPage(event.target.checked)}>
            截取整页
          </Checkbox>
          <Checkbox checked={transparent} onChange={(event) => setTransparent(event.target.checked)}>
            透明背景
          </Checkbox>
          <Checkbox checked={noWebFonts} onChange={(event) => setNoWebFonts(event.target.checked)}>
            移除网络字体
          </Checkbox>
        </Space>
        <Button type="primary" loading={loading} onClick={submit}>开始转换</Button>
      </Space>
      <FolderPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => {
          addDirectory(path);
          setPickerOpen(false);
        }}
      />
    </Card>
  );
}


function RuntimeConsole({ descriptor, showApplicationHeader }: {
  descriptor: ApplicationRuntimeDescriptor;
  showApplicationHeader: boolean;
}) {
  const runtime = useApplicationRuntime();
  const navigate = useNavigate();
  const [inputText, setInputText] = useState('{}');
  const [run, setRun] = useState<RunResource | null>(null);
  const [starting, setStarting] = useState(false);
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([]);
  const projection = useRunStream({
    organizationId: descriptor.organization_id,
    runId: run?.id ?? null,
  });
  const progress = projection.state.progress;
  const isHtmlToPng = descriptor.definition.renderer_key === 'html-to-png';
  const current = Number(progress?.current ?? 0);
  const total = Number(progress?.total ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  useEffect(() => {
    if (!run || projection.state.artifactIds.length === 0) return;
    runtime.listArtifacts(run.id).then((page) => setArtifacts(page.results));
  }, [projection.state.artifactIds.length, run, runtime]);

  const start = async (providedInput?: Record<string, unknown>) => {
    let input: Record<string, unknown>;
    if (providedInput) {
      input = providedInput;
    } else {
      try {
        const parsed = JSON.parse(inputText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('输入必须是 JSON 对象');
        }
        input = parsed;
      } catch (error) {
        message.error(error instanceof Error ? error.message : '无效 JSON');
        return;
      }
    }
    setStarting(true);
    setArtifacts([]);
    try {
      setRun(await runtime.startRun(input, crypto.randomUUID()));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '启动失败');
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!run) return;
    await runtime.sendCommand(run.id, {
      type: 'cancel',
      idempotency_key: crypto.randomUUID(),
      payload: { reason: 'user_requested' },
    });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {showApplicationHeader && (
        <div>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
            返回应用
          </Button>
          <Typography.Title level={2} style={{ margin: '12px 0 20px' }}>
            {descriptor.name}
          </Typography.Title>
        </div>
      )}
      {isHtmlToPng ? <HtmlToPngInput loading={starting} onStart={start} /> : <Card>
        <Typography.Paragraph type="secondary">
          Revision {descriptor.revision_no} ·{' '}
          {String(descriptor.definition.executor_key ?? '')}
        </Typography.Paragraph>
        <Input.TextArea
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          autoSize={{ minRows: 7, maxRows: 18 }}
          spellCheck={false}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" loading={starting} onClick={() => start()}>启动 Run</Button>
          <Button danger disabled={!run || ['succeeded', 'failed', 'cancelled'].includes(projection.state.status ?? '')}
            onClick={cancel}>取消</Button>
          {run && <Tag color={projection.connected ? 'processing' : 'default'}>
            {projection.state.status ?? run.status}
          </Tag>}
        </Space>
      </Card>}
      {isHtmlToPng && run && (
        <Button danger disabled={['succeeded', 'failed', 'cancelled'].includes(
          projection.state.status ?? '',
        )} onClick={cancel}>取消当前转换</Button>
      )}
      {projection.error && <Alert type="warning" showIcon message="事件流正在重连"
        description={projection.error.message} />}
      {run && <Card title={`Run ${run.id}`}>
        {total > 0 && <Progress percent={percent} />}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || '等待输出…'}
        </Typography.Paragraph>
      </Card>}
      {run && !isHtmlToPng && <Card title="Artifacts">
        {artifacts.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
          <List dataSource={artifacts} renderItem={(artifact) => (
            <List.Item actions={[<Button key="open" type="link" onClick={async () => {
              const access = await runtime.getArtifactAccess(run.id, artifact.id);
              window.open(access.url, '_blank', 'noopener,noreferrer');
            }}>打开</Button>]}> 
              <List.Item.Meta title={String(artifact.metadata.filename ?? artifact.kind)}
                description={`${artifact.mime_type} · ${artifact.size} bytes`} />
            </List.Item>
          )} />
        )}
      </Card>}
    </Space>
  );
}


export default function DurableApplicationRuntimePage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [descriptor, setDescriptor] = useState<ApplicationRuntimeDescriptor | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDescriptor(null);
    setError(null);
    if (!organizationId || !applicationId) {
      setError('请选择组织并提供 Application ID');
      return;
    }
    loadApplicationRuntime(organizationId, applicationId)
      .then(setDescriptor)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '加载失败'));
  }, [applicationId, organizationId]);

  if (error) return <Alert type="error" showIcon message="无法加载 Application" description={error} />;
  if (!descriptor) return <div style={{ display: 'grid', placeItems: 'center', minHeight: 320 }}><Spin /></div>;
  return (
    <ApplicationRuntimeProvider
      organizationId={descriptor.organization_id}
      applicationId={descriptor.application_id}
    >
      <RuntimeConsole
        descriptor={descriptor}
        showApplicationHeader={showApplicationHeader}
      />
    </ApplicationRuntimeProvider>
  );
}

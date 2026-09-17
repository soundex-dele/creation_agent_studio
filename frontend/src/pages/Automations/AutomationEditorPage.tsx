import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Form, Input, Modal, Radio, Select, Space, Typography, message } from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
import { automationApi } from '@/services/automations';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { AutomationTarget, AutomationTargetType } from '@/types/automation';
import {
  automationSchedulePresets as presets,
  isoToZonedLocal,
  zonedLocalToIso,
} from '@/lib/automationSchedule';
import './Automations.css';

const timezones = ['Asia/Shanghai', 'UTC', 'Asia/Tokyo', 'Europe/London', 'America/New_York'];
export default function AutomationEditorPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const editingId = id ? Number(id) : null;
  const { currentOrganizationId, loadOrganizations } = useOrganizationStore();
  const [form] = Form.useForm();
  const [targets, setTargets] = useState<AutomationTarget[]>([]);
  const [preview, setPreview] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const triggerType = Form.useWatch('trigger_type', form) || 'schedule';
  const targetType = (Form.useWatch('target_type', form) || 'application') as AutomationTargetType;
  const scheduleKind = Form.useWatch('schedule_kind', form) || 'cron';
  const preset = Form.useWatch('preset', form) || '0 9 * * *';

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);
  useEffect(() => {
    if (!currentOrganizationId) return;
    void automationApi.targets(currentOrganizationId, targetType).then(setTargets);
  }, [currentOrganizationId, targetType]);
  useEffect(() => {
    if (!currentOrganizationId || !editingId) return;
    void automationApi.get(currentOrganizationId, editingId).then(item => {
      const knownPreset = presets.some(entry => entry.value === item.schedule) ? item.schedule : 'custom';
      form.setFieldsValue({
        ...item,
        default_input_text: JSON.stringify(item.default_input || {}, null, 2),
        preset: knownPreset,
        run_at: item.run_at ? isoToZonedLocal(item.run_at, item.timezone) : undefined,
      });
    });
  }, [currentOrganizationId, editingId, form]);

  const title = useMemo(() => editingId ? '编辑自动化' : '新建自动化', [editingId]);
  const showSecret = (secret: string, webhookUrl: string) => Modal.info({
    title: '请立即保存 Webhook 密钥',
    width: 680,
    content: <div className="automation-secret"><Alert type="warning" showIcon message="密钥只显示这一次，关闭后无法再次查看。" /><Typography.Text copyable code>{window.location.origin}{webhookUrl}</Typography.Text><Typography.Text copyable code>{secret}</Typography.Text></div>,
    onOk: () => navigate('/automations'),
  });

  const submit = async () => {
    if (!currentOrganizationId) return;
    const values = await form.validateFields();
    let defaultInput: Record<string, unknown>;
    try { defaultInput = JSON.parse(values.default_input_text || '{}'); } catch { message.error('默认参数不是有效 JSON'); return; }
    if (!defaultInput || Array.isArray(defaultInput) || typeof defaultInput !== 'object') { message.error('默认参数必须是 JSON 对象'); return; }
    const schedule = values.schedule_kind === 'cron' ? (values.preset === 'custom' ? values.schedule : values.preset) : '';
    const payload = {
      name: values.name,
      description: values.description || '',
      trigger_type: values.trigger_type,
      target_type: values.target_type,
      target_id: values.target_id,
      default_input: defaultInput,
      schedule_kind: values.trigger_type === 'schedule' ? values.schedule_kind : '',
      timezone: values.timezone || 'Asia/Shanghai',
      schedule,
      run_at: values.trigger_type === 'schedule' && values.schedule_kind === 'once' && values.run_at ? zonedLocalToIso(values.run_at, values.timezone) : null,
    };
    setSaving(true);
    try {
      const result = editingId
        ? await automationApi.update(currentOrganizationId, editingId, payload)
        : await automationApi.create(currentOrganizationId, payload);
      message.success(editingId ? '自动化已保存并暂停，请确认后重新启用' : '自动化已创建');
      if (result.webhook_secret) showSecret(result.webhook_secret, result.webhook_url);
      else navigate(`/automations/${result.id}`);
    } finally { setSaving(false); }
  };

  const loadPreview = async () => {
    if (!currentOrganizationId) return;
    const values = form.getFieldsValue();
    const schedule = values.preset === 'custom' ? values.schedule : values.preset;
    try {
      const result = await automationApi.preview(currentOrganizationId, {
        schedule_kind: values.schedule_kind,
        timezone: values.timezone,
        schedule,
        run_at: values.run_at ? zonedLocalToIso(values.run_at, values.timezone) : null,
      });
      setPreview(result.next_runs);
    } catch { setPreview([]); }
  };

  return <div className="automation-editor animate-fade-in">
    <div className="automations-hero"><div><h1 className="page-title">{title}</h1><p className="page-subtitle">配置触发方式、Production 目标和默认参数</p></div><Button onClick={() => navigate('/automations')}>返回</Button></div>
    <Form form={form} layout="vertical" initialValues={{ trigger_type: 'schedule', target_type: 'application', schedule_kind: 'cron', timezone: 'Asia/Shanghai', preset: '0 9 * * *', default_input_text: '{}' }}>
      <Card title="基本信息"><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={160} /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item></Card>
      <Card title="执行目标"><Space direction="vertical" size="middle" className="automation-full"><Form.Item name="target_type" label="目标类型" rules={[{ required: true }]}><Radio.Group options={[{ value: 'application', label: '应用' }, { value: 'workflow', label: '工作流' }]} /></Form.Item><Form.Item name="target_id" label="Production 目标" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={targets.map(target => ({ value: target.id, label: target.name }))} placeholder="请选择目标" /></Form.Item></Space></Card>
      <Card title="触发方式"><Form.Item name="trigger_type" label="触发类型"><Radio.Group options={[{ value: 'schedule', label: '定时' }, { value: 'webhook', label: 'Webhook' }]} /></Form.Item>{triggerType === 'schedule' ? <>
        <Form.Item name="schedule_kind" label="计划类型"><Radio.Group options={[{ value: 'once', label: '单次' }, { value: 'cron', label: '周期' }]} /></Form.Item>
        <Form.Item name="timezone" label="时区" rules={[{ required: true }]}><Select showSearch options={timezones.map(value => ({ value, label: value }))} /></Form.Item>
        {scheduleKind === 'once' ? <Form.Item name="run_at" label="执行时间" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item> : <><Form.Item name="preset" label="周期预设"><Select options={[...presets]} /></Form.Item>{preset === 'custom' && <Form.Item name="schedule" label="五段 Cron" rules={[{ required: true }]}><Input placeholder="0 9 * * 1-5" /></Form.Item>}</>}
        <Space><Button onClick={() => void loadPreview()}>预览执行时间</Button>{preview.length > 0 && <Typography.Text type="secondary">{preview.map(value => new Date(value).toLocaleString()).join(' · ')}</Typography.Text>}</Space>
      </> : <Alert type="info" showIcon message="保存后会生成 Webhook URL 与一次性密钥；启用前请妥善保存密钥。" />}</Card>
      <Card title="默认参数"><Form.Item name="default_input_text" label="JSON 对象" rules={[{ required: true }]}><Input.TextArea rows={8} className="automation-json" /></Form.Item><Typography.Text type="secondary">Webhook 请求体会在顶层覆盖同名默认参数。</Typography.Text></Card>
      <div className="automation-editor-actions"><Button onClick={() => navigate('/automations')}>取消</Button><Button type="primary" loading={saving} onClick={() => void submit()}>保存</Button></div>
    </Form>
  </div>;
}

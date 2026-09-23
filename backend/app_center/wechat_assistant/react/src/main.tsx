import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Empty, Form, Input, List, Popconfirm, QRCode, Select, Space, Spin, Tag, Typography } from 'antd';
import { MessageOutlined, ReloadOutlined } from '@ant-design/icons';
import './styles.css';

export interface Binding {
  id: string; status: string; enabled: boolean; agent_id: number | null;
  conversation_id: number | null; busy: boolean; login_id: string | null;
  login_expires_at: string | null; qr_content: string;
  heartbeat_at: string | null; received_at: string | null; sent_at: string | null; last_error: string;
}
interface Agent { id: number; name: string; kind: string }
interface Task {
  id: string; text: string; state: string; run_id: string | null; run_status: string;
  conversation_id: number | null; created_at: string;
  replies: { id: string; state: string; attempts: number; last_error: string }[];
}
export type Requester = <T>(path: string, init?: RequestInit) => Promise<T>;
export const statusLabels: Record<string, string> = {
  unbound: '未绑定', qr_pending: '正在获取二维码', wait: '等待扫码', scaned: '已扫码，请在微信确认',
  need_verifycode: '请输入手机显示的验证码', connecting: '正在连接', connected: '已连接',
  reconnecting: '正在重连', expired: '登录或二维码已失效', blocked: '需要检查配置',
};
const taskLabels: Record<string, string> = { pending: '等待处理', handled: '已处理', discarded: '已作废', queued: '排队中', running: '执行中', waiting_input: '等待操作', waiting_children: '执行中', succeeded: '已完成', failed: '失败', cancelling: '取消中', cancelled: '已取消' };
const replyLabels: Record<string, string> = { pending: '待回复', retry: '回复重试中', sending: '发送中', sent: '已回复', failed: '回复失败', discarded: '回复已作废' };
const time = (value: string | null) => value ? new Date(value).toLocaleString() : '暂无';

export function WechatAssistantApp({ apiBasePath, requester, openConversation }: {
  apiBasePath: string; requester: Requester; openConversation: (id: number) => void;
}) {
  const [binding, setBinding] = useState<Binding | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agent, setAgent] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [code, setCode] = useState('');
  const epoch = useRef(0);
  const selectedByUser = useRef(false);
  const mutating = useRef(false);
  const reload = useCallback(async () => {
    if (mutating.current) return;
    const version = ++epoch.current;
    try {
      const [status, choices] = await Promise.all([
        requester<Binding | null>(apiBasePath), requester<Agent[]>(apiBasePath + 'agents'),
      ]);
      const recent = status?.id ? await requester<Task[]>(apiBasePath + 'tasks') : [];
      if (version !== epoch.current) return;
      setBinding(status?.id ? status : null); setAgents(choices); setTasks(recent);
      if (!selectedByUser.current) setAgent(status?.agent_id ?? undefined);
      setError(previous => previous.startsWith('无法读取') ? '' : previous);
    } catch {
      if (version === epoch.current) setError('无法读取微信助手，请检查网络或应用权限后重试。');
    } finally {
      if (version === epoch.current) setLoading(false);
    }
  }, [apiBasePath, requester]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => { await reload(); if (!disposed) timer = setTimeout(poll, 3000); };
    void poll();
    return () => { disposed = true; clearTimeout(timer); epoch.current += 1; };
  }, [reload]);

  const act = async (path: string, body?: object, method = 'POST') => {
    mutating.current = true; setWorking(true); setError(''); setNotice(''); epoch.current += 1;
    try {
      const result = await requester<Binding>(apiBasePath + path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      selectedByUser.current = false;
      setBinding(result); setAgent(result.agent_id ?? undefined); setCode('');
      setNotice(path === 'login' ? '已请求二维码，连接服务正在处理。' : '设置已更新。');
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } | string[] } }).response?.data;
      setError(Array.isArray(detail) ? detail.join(' ') : detail?.detail || '操作失败，请检查连接状态和配置后重试。');
    } finally { mutating.current = false; setWorking(false); }
  };
  const status = binding?.status || 'unbound';
  const stale = binding && (binding.enabled || status === 'qr_pending') && (!binding.heartbeat_at || Date.now() - new Date(binding.heartbeat_at).getTime() > 120000);
  const canLogin = !!binding?.agent_id && !binding.enabled && !binding.busy;
  return <div className="wechat-assistant">
    <header><Typography.Title level={2}><MessageOutlined aria-hidden /> 微信助手</Typography.Title><Typography.Paragraph type="secondary">绑定个人微信，与自己的智能体对话。需要回答问题或批准操作时，请回到项目会话中处理。</Typography.Paragraph></header>
    <div aria-live="polite" aria-atomic="true">{notice && <Alert type="success" message={notice} showIcon />}</div>
    {error && <Alert type="error" role="alert" message={error} showIcon action={<Button onClick={() => void reload()}>重试</Button>} />}
    {loading ? <Spin tip="正在加载微信助手"><div style={{ minHeight: 180 }} /></Spin> : <>
      <div className="wechat-assistant-grid">
        <Card title="微信连接" extra={<Tag color={status === 'connected' && !stale ? 'success' : 'default'}>{statusLabels[status] || status}</Tag>}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Typography.Text>仅接收扫码账号的私聊消息，首版支持文本。</Typography.Text>
            {binding?.qr_content && <div className="wechat-qr"><QRCode type="svg" value={binding.qr_content} size={220} /><Typography.Text type="secondary">使用微信扫码并确认授权</Typography.Text><Typography.Text type="secondary">有效期至 {time(binding.login_expires_at)}</Typography.Text></div>}
            {status === 'qr_pending' && <div role="status"><Spin size="small" /> 正在获取二维码，请稍候…</div>}
            {status === 'need_verifycode' && <Form layout="vertical" onFinish={() => void act('verify', { login_id: binding?.login_id, code })}>
              <Form.Item label="微信验证码"><Input value={code} onChange={e => setCode(e.target.value)} autoComplete="one-time-code" inputMode="numeric" maxLength={12} /></Form.Item>
              <Button htmlType="submit" type="primary" disabled={!/^\d{4,12}$/.test(code)} loading={working}>提交验证码</Button>
            </Form>}
            {binding?.last_error && <Alert type="warning" showIcon message={binding.last_error} />}
            {stale && <Alert type="warning" showIcon message="连接服务尚未就绪，请确认项目后台正在运行。" />}
            {!binding?.agent_id && <Typography.Text type="secondary">先选择并保存智能体，再扫码绑定。</Typography.Text>}
            <Space wrap>
              {!binding?.enabled && <Button type="primary" disabled={!canLogin || working || status === 'qr_pending'} onClick={() => void act('login')}>{binding?.qr_content || status === 'expired' ? '刷新二维码' : '扫码绑定'}</Button>}
              {binding?.enabled && <Button icon={<ReloadOutlined />} disabled={working} onClick={() => void act('reconnect')}>重新连接</Button>}
              {binding && status !== 'unbound' && <Popconfirm title="解绑微信？" description="将停止收发消息，历史会话会保留。" onConfirm={() => act('unbind')}><Button danger disabled={working}>解绑</Button></Popconfirm>}
            </Space>
            <div className="wechat-times"><span>连接心跳：{time(binding?.heartbeat_at ?? null)}</span><span>最近收取：{time(binding?.received_at ?? null)}</span><span>最近发送：{time(binding?.sent_at ?? null)}</span></div>
          </Space>
        </Card>
        <Card title="智能体与会话">
          <Form layout="vertical" onFinish={() => void act('', { agent_id: agent }, 'PUT')}>
            <Form.Item label="默认智能体" extra="仅显示你有权限使用的智能体；更换后会创建新会话。">
              <Select aria-label="默认智能体" placeholder="请选择智能体" value={agent} disabled={binding?.busy || working} onChange={value => { selectedByUser.current = true; setAgent(value); }} options={agents.map(a => ({ value: a.id, label: a.name }))} showSearch optionFilterProp="label" />
            </Form.Item>
            <Space wrap><Button type="primary" htmlType="submit" loading={working} disabled={!agent || binding?.busy}>保存智能体</Button><Button disabled={!binding?.agent_id || binding.busy || working} onClick={() => void act('new-conversation')}>新建会话</Button>{binding?.conversation_id && <Button onClick={() => openConversation(binding.conversation_id!)}>打开当前会话</Button>}</Space>
          </Form>
          {binding?.busy && <Alert style={{ marginTop: 16 }} type="info" showIcon message="当前任务尚未结束，可打开会话查看进度或处理待办。" />}
          <Typography.Paragraph type="secondary" style={{ marginTop: 20 }}>关闭本页面后，后台会继续收发消息。请保持项目后台和执行服务运行。</Typography.Paragraph>
        </Card>
      </div>
      <Card title="近期任务与回复" extra={<Button onClick={() => void reload()}>刷新</Button>}>
        <List dataSource={tasks} locale={{ emptyText: <Empty description="还没有微信消息。绑定后，在微信中发送一条文字开始对话。" /> }} renderItem={task => <List.Item actions={task.conversation_id ? [<Button key="open" type="link" onClick={() => openConversation(task.conversation_id!)}>打开会话</Button>] : []}>
          <List.Item.Meta title={<Space wrap><Typography.Text>{task.text.slice(0, 100) || '非文本消息'}</Typography.Text><Tag>{taskLabels[task.run_status || task.state] || task.state}</Tag></Space>} description={<Space direction="vertical"><span>{time(task.created_at)}</span>{task.replies.map(reply => <span key={reply.id}>{replyLabels[reply.state] || reply.state}{reply.last_error && ` · ${reply.last_error}`}</span>)}</Space>} />
        </List.Item>} />
      </Card>
    </>}
  </div>;
}

import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Input, List, Popconfirm, Select, Space, Switch, Tag } from 'antd';
import { ArrowLeftOutlined, DesktopOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/services/api';
import { createConnectionApi, loadConnectionCollection } from '@/services/chatConnection';
import { createConversationStore, type Conversation } from '@/stores/useConversationStore';
import ChatContainer from '@/components/Chat/ChatContainer';
import { ChatConnectionContext } from '@/components/Chat/ChatConnectionContext';
import './MyComputerPage.css';

interface Device {
  id: string;
  name: string;
  online: boolean;
  confirmed: boolean;
  last_seen_at: string | null;
}
interface ChatApp { id: number; name: string; kind: string }

function ComputerWorkspace({ device, connectionKnown }: { device: Device; connectionKnown: boolean }) {
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const connection = useMemo(() => ({ deviceId: device.id }), [device.id]);
  const remoteApi = useMemo(() => createConnectionApi(connection), [connection]);
  const store = useMemo(() => createConversationStore(connection), [connection]);
  const { conversations, fetchConversations, isLoading, error } = store();
  const [apps, setApps] = useState<ChatApp[]>([]);
  const [applicationId, setApplicationId] = useState<number | undefined>();
  const [contextReady, setContextReady] = useState(false);
  const [olderConversations, setOlderConversations] = useState<Conversation[]>([]);
  const [nextPage, setNextPage] = useState<number | null>(2);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const online = connectionKnown && device.online && device.confirmed;
  const root = `/apps/my-computer/${device.id}`;

  useEffect(() => {
    setOlderConversations([]);
    setNextPage(conversations.length >= 20 ? 2 : null);
  }, [conversations]);

  useEffect(() => {
    let cancelled = false;
    let checking = false;
    if (!online) { setContextReady(false); return; }
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        await remoteApi.get('/remote-access/context/');
        if (!cancelled) setContextReady(true);
      } catch {
        if (!cancelled) setContextReady(false);
      } finally { checking = false; }
    };
    void check();
    const timer = setInterval(() => void check(), 5000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [online, remoteApi]);

  useEffect(() => {
    let cancelled = false;
    if (online) {
      if (!conversationId) void fetchConversations().catch(() => undefined);
      void loadConnectionCollection<ChatApp>(remoteApi, '/apps/', { kind: 'chat' })
        .then(result => {
          if (!cancelled) setApps(result.filter(app => app.kind === 'chat'));
        }).catch(() => { if (!cancelled) setApps([]); });
    }
    return () => { cancelled = true; };
  }, [online, remoteApi, fetchConversations, conversationId]);

  useEffect(() => () => store.getState().disconnect(), [store]);
  const value = useMemo(() => ({ store, api: remoteApi, remote: true, online: online && contextReady }),
    [store, remoteApi, online, contextReady]);

  return <ChatConnectionContext.Provider value={value}>
    <section className={`my-computer-workspace${conversationId ? ' my-computer-workspace--chat' : ''}`}>
      <header className="my-computer-toolbar">
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(conversationId ? root : '/apps/my-computer')}>
          {conversationId ? '对话列表' : '电脑列表'}
        </Button>
        <strong><DesktopOutlined aria-hidden="true" /> {device.name}</strong>
        <Tag color={online ? 'green' : 'default'}>{!connectionKnown ? '重连中' : online ? '在线' : '离线'}</Tag>
      </header>
      {!online && <Alert showIcon type="warning" message="电脑暂时离线，当前草稿会保留。恢复连接后可继续发送。" />}
      {online && !contextReady && <Alert showIcon type="info" message="正在检查本机访问权限与连接…" />}
      {conversationId ? <ChatContainer
        conversationId={conversationId === 'new' ? null : conversationId}
        createOnFirstSend
        creationContext={{ applicationId }}
        onConversationCreated={id => navigate(`${root}/conversations/${id}`, { replace: true })}
        emptyTitle={applicationId ? apps.find(app => app.id === applicationId)?.name : '在这台电脑上开始对话'}
        emptyDescription="对话和任务保存在电脑上，离开页面后任务会继续运行。"
        suggestions={[]}
      /> : <div className="my-computer-content">
        <Space wrap>
          <Select aria-label="选择电脑上的对话应用" value={applicationId} allowClear placeholder="普通对话"
            onChange={setApplicationId} style={{ minWidth: 200 }} disabled={!value.online}
            options={apps.map(app => ({ value: app.id, label: app.name }))} />
          <Button type="primary" icon={<PlusOutlined />} disabled={!value.online}
            onClick={() => navigate(`${root}/conversations/new`)}>新建对话</Button>
          <Button disabled={!value.online} loading={isLoading} onClick={() => void fetchConversations().catch(() => undefined)}>刷新</Button>
        </Space>
        {error && <Alert type="error" showIcon message={error} />}
        <List loading={isLoading} dataSource={[...conversations, ...olderConversations]}
          locale={{ emptyText: <Empty description={online ? '这台电脑还没有对话' : '电脑离线，暂时无法读取对话'} /> }}
          renderItem={conversation => <List.Item>
            <Button type="text" className="my-computer-conversation" disabled={!value.online}
              onClick={() => navigate(`${root}/conversations/${conversation.id}`)}>
              <span>{conversation.title || '未命名对话'}</span>
              <small>{new Date(conversation.updated_at).toLocaleString('zh-CN')}</small>
            </Button>
          </List.Item>} />
        {nextPage && <Button disabled={!value.online} loading={loadingOlder} onClick={async () => {
          setLoadingOlder(true);
          try {
            const result = await remoteApi.get<{ results: Conversation[]; next: string | null }>('/conversations/', { page: nextPage });
            const knownIds = new Set([...conversations, ...olderConversations].map(item => String(item.id)));
            setOlderConversations(current => [...current, ...result.results
              .filter(item => !knownIds.has(String(item.id))).map(item => ({ ...item, id: String(item.id) }))]);
            setNextPage(result.next ? nextPage + 1 : null);
          } catch {
            // The shared HTTP transport displays the error; retain loaded pages.
          } finally { setLoadingOlder(false); }
        }}>加载更早的对话</Button>}
      </div>}
    </section>
  </ChatConnectionContext.Provider>;
}

export default function MyComputerPage() {
  const navigate = useNavigate();
  const { deviceId } = useParams();
  const [devices, setDevices] = useState<Device[]>([]);
  const [known, setKnown] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [manage, setManage] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let cancelled = false;
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const result = await api.get<Device[]>('/remote/devices/');
        if (!cancelled) {
          setDevices(result); setKnown(true); setLoaded(true);
          setError(current => current === '无法连接服务器，正在重试。' ? '' : current);
        }
      } catch {
        if (!cancelled) { setKnown(false); setError('无法连接服务器，正在重试。'); }
      } finally { loading = false; }
    };
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const claim = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      await api.post('/remote/claim/', { code });
      setCode(''); setManage(true);
      setNotice('配对码已接受，请回到电脑设置页核对并确认绑定账号。');
      setDevices(await api.get<Device[]>('/remote/devices/'));
    } catch {
      setError('配对失败，请检查配对码是否正确、过期或已经使用。');
    } finally { setBusy(false); }
  };

  const device = devices.find(item => item.id === deviceId);
  if (deviceId && device) return <ComputerWorkspace key={device.id} device={device} connectionKnown={known} />;
  if (deviceId) return <div className="my-computer-content">
    <Button onClick={() => navigate('/apps/my-computer')}>返回电脑列表</Button>
    <Alert type="info" message={loaded ? '这台电脑尚未绑定或已被解绑。' : '正在加载电脑…'} />
  </div>;

  return <section className="my-computer-content">
    <header><h1 className="page-title">我的电脑</h1><p className="page-subtitle">一个账号可绑定多台电脑，选择电脑继续对话与任务。</p></header>
    {error && <Alert closable onClose={() => setError('')} showIcon type="error" message={error} />}
    {notice && <Alert showIcon type="success" message={notice} />}
    <Card title="绑定电脑">
      <p>在每台电脑上生成配对码，逐台添加到当前账号。电脑名称可在该电脑的“设置 → 远程访问”中修改。</p>
      <form onSubmit={event => { event.preventDefault(); void claim(); }}>
        <label htmlFor="remote-pairing-code">电脑“设置 → 远程访问”中的配对码</label>
        <div className="my-computer-pairing">
          <Input id="remote-pairing-code" value={code} maxLength={9} autoComplete="off" autoCapitalize="characters"
            placeholder="输入 8 位配对码" onChange={event => setCode(event.target.value.toUpperCase())} />
          <Button type="primary" htmlType="submit" disabled={code.replace('-', '').length !== 8} loading={busy}>配对</Button>
        </div>
      </form>
    </Card>
    <div className="my-computer-toolbar"><h2>电脑列表{loaded ? `（${devices.length}）` : ''}</h2>
      <Space><span>管理电脑</span><Switch aria-label="管理电脑" checked={manage} onChange={setManage} /></Space>
    </div>
    {!devices.length && <Empty description={loaded ? '尚未绑定电脑，请输入电脑上的配对码' : '正在加载电脑…'} />}
    <div className="my-computer-devices">{devices.map(item => <Card key={item.id} title={<span className="my-computer-name"><DesktopOutlined aria-hidden="true" /> {item.name}</span>}>
      <Space direction="vertical" size="middle">
        <Tag color={item.online ? 'green' : 'default'}>{!item.confirmed ? '等待电脑确认' : item.online ? '在线' : '离线'}</Tag>
        <Button type="primary" disabled={!known || !item.online || !item.confirmed} onClick={() => navigate(`/apps/my-computer/${item.id}`)}>查看对话</Button>
        {manage && <Popconfirm title={`解绑“${item.name}”？`} description="此账号将无法继续访问该电脑。"
          onConfirm={async () => {
            await api.delete(`/remote/devices/${item.id}/`);
            setDevices(current => current.filter(value => value.id !== item.id));
          }}><Button danger>解绑</Button></Popconfirm>}
      </Space>
    </Card>)}</div>
  </section>;
}

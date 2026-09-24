import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Input, List, Popconfirm, Select, Switch, Tag } from 'antd';
import { ArrowLeftOutlined, DesktopOutlined, PlusOutlined, MessageOutlined, CodeOutlined, FolderOutlined, RightOutlined } from '@ant-design/icons';
import { useLocation, useParams } from 'react-router-dom';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';
import { api } from '@/services/api';
import { createConnectionApi, loadConnectionCollection } from '@/services/chatConnection';
import { createConversationStore, type Conversation } from '@/stores/useConversationStore';
import ChatContainer from '@/components/Chat/ChatContainer';
import { ChatConnectionContext } from '@/components/Chat/ChatConnectionContext';
import './MyComputerPage.css';
import './RemoteWorkspaceToolbar.css';

const RemoteTerminalPage = lazy(() => import('./RemoteTerminalPage'));
const RemoteFilesPage = lazy(() => import('./RemoteFilesPage'));

interface Device {
  id: string;
  name: string;
  online: boolean;
  confirmed: boolean;
  last_seen_at: string | null;
}
interface ChatApp { id: number; name: string; kind: string }

function ComputerWorkspace({ device, connectionKnown }: { device: Device; connectionKnown: boolean }) {
  const navigate = useApplicationNavigate();
  const { conversationId } = useParams();
  const terminalMode = useLocation().pathname.includes('/terminals');
  const filesMode = useLocation().pathname.replace(/\/+$/, '').endsWith('/files');
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
    if (online && !terminalMode && !filesMode) {
      if (!conversationId) void fetchConversations().catch(() => undefined);
      void loadConnectionCollection<ChatApp>(remoteApi, '/apps/', { kind: 'chat' })
        .then(result => {
          if (!cancelled) setApps(result.filter(app => app.kind === 'chat'));
        }).catch(() => { if (!cancelled) setApps([]); });
    }
    return () => { cancelled = true; };
  }, [online, remoteApi, fetchConversations, conversationId, terminalMode, filesMode]);

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
      <nav className="my-computer-mode" aria-label="电脑工作区">
        <Button icon={<MessageOutlined />} aria-current={!terminalMode && !filesMode ? 'page' : undefined} type={!terminalMode && !filesMode ? 'primary' : 'default'} onClick={() => navigate(root)}>对话</Button>
        <Button icon={<CodeOutlined />} aria-current={terminalMode ? 'page' : undefined} type={terminalMode ? 'primary' : 'default'} onClick={() => navigate(`${root}/terminals`)}>终端</Button>
        <Button icon={<FolderOutlined />} aria-current={filesMode ? 'page' : undefined} type={filesMode ? 'primary' : 'default'} onClick={() => navigate(`${root}/files`)}>文件</Button>
      </nav>
      {!online && !filesMode && <Alert showIcon type="warning" message={terminalMode ? '电脑暂时离线，终端输入已暂停，恢复连接后自动重连。' : '电脑暂时离线，当前草稿会保留。恢复连接后可继续发送。'} />}
      {online && !contextReady && <Alert showIcon type="info" message="正在检查本机访问权限与连接…" />}
      {filesMode ? <Suspense fallback={<div className="my-computer-content">正在加载文件…</div>}>
        <RemoteFilesPage deviceId={device.id} online={online && contextReady} />
      </Suspense> : terminalMode ? <Suspense fallback={<div className="my-computer-content">正在加载终端…</div>}>
        <RemoteTerminalPage deviceId={device.id} online={online && contextReady} />
      </Suspense> : conversationId ? <ChatContainer
        conversationId={conversationId === 'new' ? null : conversationId}
        createOnFirstSend
        creationContext={{ applicationId }}
        onConversationCreated={id => navigate(`${root}/conversations/${id}`, { replace: true })}
        emptyTitle={applicationId ? apps.find(app => app.id === applicationId)?.name : '在这台电脑上开始对话'}
        emptyDescription="对话和任务保存在电脑上，离开页面后任务会继续运行。"
        suggestions={[]}
      /> : <div className="my-computer-content">
        <div className="remote-workspace-toolbar">
          <Select aria-label="选择电脑上的对话应用" value={applicationId} allowClear placeholder="普通对话"
            onChange={setApplicationId} disabled={!value.online}
            options={apps.map(app => ({ value: app.id, label: app.name }))} />
          <Button type="primary" icon={<PlusOutlined />} disabled={!value.online}
            onClick={() => navigate(`${root}/conversations/new`)}>新建对话</Button>
          <Button disabled={!value.online} loading={isLoading} onClick={() => void fetchConversations().catch(() => undefined)}>刷新</Button>
        </div>
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
  const navigate = useApplicationNavigate();
  const { deviceId } = useParams();
  const [devices, setDevices] = useState<Device[]>([]);
  const [known, setKnown] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [manage, setManage] = useState(false);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [pairingOpen, setPairingOpen] = useState<boolean | null>(null);
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
    if (busy || code.replace('-', '').length !== 8) return;
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

  const showPairing = pairingOpen ?? (loaded && devices.length === 0);
  return <section className="my-computer-content my-computer-home">
    <header className="my-computer-heading">
      <div className="my-computer-heading-icon"><DesktopOutlined aria-hidden /></div>
      <div><h1 className="page-title">我的电脑</h1><p className="page-subtitle">电脑在身边，工作随时继续。</p></div>
    </header>
    <div className="my-computer-overview">
      <span>{!loaded ? '正在查找已绑定的电脑…' : !known ? '正在恢复连接…' : <><strong>{devices.filter(item => item.online && item.confirmed).length}</strong> 台在线<span className="my-computer-overview-total"> / {devices.length} 台已绑定</span></>}</span>
      <Button icon={<PlusOutlined />} aria-expanded={showPairing} aria-controls="my-computer-pairing-panel"
        onClick={() => setPairingOpen(!showPairing)}>绑定电脑</Button>
    </div>
    {error && <Alert closable onClose={() => setError('')} showIcon type="error" message={error} />}
    {notice && <Alert showIcon type="success" message={notice} />}
    <Card id="my-computer-pairing-panel" className="my-computer-pairing-panel" title="绑定电脑" hidden={!showPairing}>
      <p>在每台电脑上生成配对码，逐台添加到当前账号。电脑名称可在该电脑的“设置 → 远程访问”中修改。</p>
      <form onSubmit={event => { event.preventDefault(); void claim(); }}>
        <label htmlFor="remote-pairing-code">电脑“设置 → 远程访问”中的配对码</label>
        <div className="my-computer-pairing">
          <Input id="remote-pairing-code" value={code} maxLength={9} autoComplete="off" autoCapitalize="characters" spellCheck={false} disabled={busy}
            placeholder="输入 8 位配对码" onChange={event => setCode(event.target.value.trim().toUpperCase())} />
          <Button type="primary" htmlType="submit" disabled={code.replace('-', '').length !== 8} loading={busy}>配对</Button>
        </div>
      </form>
    </Card>
    <div className="my-computer-toolbar my-computer-list-heading"><h2>电脑列表{loaded ? `（${devices.length}）` : ''}</h2>
      <label className="my-computer-manage" htmlFor="manage-computers"><span>管理电脑</span><Switch id="manage-computers" aria-label="管理电脑" checked={manage} onChange={setManage} /></label>
    </div>
    {!devices.length && <Empty description={loaded ? '尚未绑定电脑，请输入电脑上的配对码' : '正在加载电脑…'} />}
    <div className="my-computer-devices">{devices.map(item => <Card key={item.id} title={<span className="my-computer-name"><DesktopOutlined aria-hidden="true" /> {item.name}</span>}>
      <div className="my-computer-device-status">
        <Tag color={known && item.confirmed && item.online ? 'green' : 'default'}>{!known ? '重连中' : !item.confirmed ? '等待电脑确认' : item.online ? '在线' : '离线'}</Tag>
        <span>{!item.confirmed ? '请在电脑上确认绑定' : !known ? '正在恢复连接' : item.online ? '可以远程访问' : item.last_seen_at ? `最近在线 ${new Date(item.last_seen_at).toLocaleString('zh-CN')}` : '电脑上线后即可连接'}</span>
      </div>
      <div className="my-computer-device-actions">
        <Button className="my-computer-device-chat" type="primary" icon={<MessageOutlined />} disabled={!known || !item.online || !item.confirmed} onClick={() => navigate(`/apps/my-computer/${item.id}`)}>查看对话<RightOutlined aria-hidden /></Button>
        <Button icon={<CodeOutlined />} disabled={!known || !item.online || !item.confirmed} onClick={() => navigate(`/apps/my-computer/${item.id}/terminals`)}>远程终端</Button>
        <Button icon={<FolderOutlined />} disabled={!known || !item.online || !item.confirmed} onClick={() => navigate(`/apps/my-computer/${item.id}/files`)}>文件传输</Button>
        {manage && <Popconfirm title={`解绑“${item.name}”？`} description="此账号将无法继续访问该电脑。"
          onConfirm={async () => {
            await api.delete(`/remote/devices/${item.id}/`);
            setDevices(current => current.filter(value => value.id !== item.id));
          }}><Button danger>解绑</Button></Popconfirm>}
      </div>
    </Card>)}</div>
  </section>;
}

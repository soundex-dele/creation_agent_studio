import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Popconfirm, Select, Space, Tag } from 'antd';
import { useParams } from 'react-router-dom';
import useApplicationNavigate from '@/hooks/useApplicationNavigate';
import { api } from '@/services/api';
import { remotePath } from '@/services/chatConnection';
import { terminalError, terminalKey, terminalPath, terminalPost, terminalStream, TerminalInput,
  type TerminalCapability, type TerminalSession } from '@/services/remoteTerminal';
import type { Terminal } from '@xterm/xterm';
import './RemoteTerminalPage.css';

function TerminalView({ deviceId, sessionId, online, onExit }: {
  deviceId: string; sessionId: string; online: boolean; onExit: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal>();
  const input = useRef<TerminalInput>();
  const onlineRef = useRef(online);
  const onExitRef = useRef(onExit);
  onExitRef.current = onExit;
  const [status, setStatus] = useState('连接中');
  const [error, setError] = useState('');
  const [generation, setGeneration] = useState(0);
  const [ctrl, setCtrl] = useState(false);
  const ctrlRef = useRef(false);
  onlineRef.current = online;
  useEffect(() => {
    if (!online) { input.current?.setOnline(false); setStatus('重连中'); }
  }, [online]);

  useEffect(() => {
    const controller = new AbortController();
    let dispose = () => {};
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let exited = false;
    let activeStream: AbortController | undefined;
    let connected = false;
    setError(''); setStatus('连接中');
    const run = async () => {
      const [{ Terminal: XTerminal }, { FitAddon }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]);
      await import('@xterm/xterm/css/xterm.css');
      if (controller.signal.aborted || !host.current) return;
      const term = new XTerminal({ cursorBlink: true, fontSize: 15, fontFamily: 'Consolas, Menlo, monospace',
        scrollback: 5000, screenReaderMode: true, allowProposedApi: false });
      const fit = new FitAddon();
      term.loadAddon(fit); term.open(host.current); terminal.current = term;
      const sender = new TerminalInput(deviceId, sessionId, failure => {
        setError(terminalError(failure));
        if (terminalError(failure).includes('输入已暂停')) setStatus('输入已暂停');
      });
      input.current = sender;
      let resizeTimer: ReturnType<typeof setTimeout> | undefined;
      let lastSize = '';
      let resizeSending = false;
      const resize = () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(async () => {
          if (controller.signal.aborted) return;
          fit.fit();
          const size = `${term.cols}:${term.rows}`;
          if (!connected || !onlineRef.current || exited || size === lastSize || resizeSending) return;
          resizeSending = true;
          try {
            await terminalPost(deviceId, `${sessionId}/resize/`, { cols: Math.max(2, term.cols), rows: Math.max(2, term.rows) },
              terminalKey(), controller.signal);
            lastSize = size;
          } catch (failure) { if (!controller.signal.aborted) setError(terminalError(failure)); }
          finally { resizeSending = false; if (size !== `${term.cols}:${term.rows}`) resize(); }
        }, 120);
      };
      const observer = new ResizeObserver(resize);
      observer.observe(host.current); window.visualViewport?.addEventListener('resize', resize);
      const dataListener = term.onData(data => {
        if (ctrlRef.current && data.length === 1 && /[a-z@[\\\]^_?]/i.test(data)) {
          data = data === '?' ? '\x7f' : String.fromCharCode(data.toUpperCase().charCodeAt(0) & 31);
          ctrlRef.current = false; setCtrl(false);
        }
        if (connected && onlineRef.current) sender.write(data);
      });
      const checkOnline = setInterval(() => { if (!onlineRef.current) activeStream?.abort(); }, 250);
      dispose = () => {
        clearInterval(checkOnline); clearTimeout(resizeTimer); observer.disconnect();
        window.visualViewport?.removeEventListener('resize', resize);
        sender.dispose(); dataListener.dispose(); term.dispose(); terminal.current = undefined; input.current = undefined;
      };
      resize();
      const connect = async () => {
        if (controller.signal.aborted || exited) return;
        try {
          if (!onlineRef.current) return;
          activeStream = new AbortController();
          await terminalStream(deviceId, sessionId, cursor, activeStream.signal, async event => {
            if (controller.signal.aborted) return;
            if (event.type === 'ready') {
              connected = true; sender.setOnline(true); setStatus(sender.paused ? '输入已暂停' : '在线'); lastSize = ''; resize();
            } else if (event.type === 'output' && event.sequence > cursor) {
              await new Promise<void>(resolve => term.write(event.data, resolve)); cursor = event.sequence;
            } else if (event.type === 'truncated') {
              term.reset(); cursor = event.sequence; setError('较早的输出已超出保留范围，仅显示最近输出。');
            } else if (event.type === 'exit') {
              exited = true; sender.setOnline(false); setStatus(`进程已退出${event.exit_code === null ? '' : `（${event.exit_code}）`}`);
              onExitRef.current();
            }
          });
        } catch (failure) {
          if (controller.signal.aborted) return;
          const code = (failure as { status?: number }).status;
          if ([400, 401, 403, 404, 409, 410].includes(code || 0)) {
            exited = true; setStatus(code === 403 ? '权限关闭' : '会话不可用');
          }
          if (!(failure instanceof DOMException && failure.name === 'AbortError')) setError(terminalError(failure));
        } finally {
          connected = false; sender.setOnline(false);
          if (!controller.signal.aborted && !exited) {
            setStatus('重连中'); reconnectTimer = setTimeout(() => void connect(), 1500);
          }
        }
      };
      void connect();
    };
    void run().catch(failure => { if (!controller.signal.aborted) { setError(terminalError(failure)); setStatus('组件加载失败'); } });
    return () => { controller.abort(); activeStream?.abort(); clearTimeout(reconnectTimer); dispose(); };
  }, [deviceId, sessionId, generation]);

  const sendKey = (value: string) => { if (online) input.current?.write(value); terminal.current?.focus(); };
  return <div className="remote-terminal-view">
    <div className="remote-terminal-status"><Tag color={online && status === '在线' ? 'green' : 'default'}>{online ? status : '重连中'}</Tag>
      <Button onClick={() => setGeneration(value => value + 1)} disabled={!online}>重新连接</Button>
      <span>离开页面后程序继续运行</span></div>
    {error && <Alert type="warning" showIcon message={error} closable onClose={() => setError('')} />}
    <div className="remote-terminal-screen" ref={host} role="region" aria-label="远程终端输出与输入" />
    <div className="remote-terminal-keys" aria-label="终端快捷键">
      <Button disabled={!online || status !== '在线'} aria-pressed={ctrl} type={ctrl ? 'primary' : 'default'} onClick={() => {
        ctrlRef.current = !ctrl; setCtrl(!ctrl); terminal.current?.focus();
      }}>Ctrl</Button>
      {([['Tab', '\t'], ['Esc', '\x1b'], ['↑', '\x1b[A'], ['↓', '\x1b[B'], ['←', '\x1b[D'], ['→', '\x1b[C'], ['Ctrl+C', '\x03']] as const)
        .map(([label, value]) => <Button key={label} aria-label={`发送 ${label}`} disabled={!online || status !== '在线'} onClick={() => sendKey(value)}>{label}</Button>)}
    </div>
  </div>;
}

export default function RemoteTerminalPage({ deviceId, online }: { deviceId: string; online: boolean }) {
  const workspace = useRef<HTMLElement>(null);
  const { sessionId } = useParams();
  const navigate = useApplicationNavigate();
  const root = `/apps/my-computer/${deviceId}/terminals`;
  const [sessions, setSessions] = useState<TerminalSession[]>([]);
  const [capability, setCapability] = useState<TerminalCapability>();
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const creationKey = useRef<string>();
  useEffect(() => {
    const fitViewport = () => {
      if (!workspace.current) return;
      const viewport = window.visualViewport;
      const bottom = viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
      workspace.current.style.maxHeight = `${Math.max(160, bottom - workspace.current.getBoundingClientRect().top - 8)}px`;
    };
    fitViewport();
    window.visualViewport?.addEventListener('resize', fitViewport);
    window.visualViewport?.addEventListener('scroll', fitViewport);
    window.addEventListener('resize', fitViewport);
    return () => {
      window.visualViewport?.removeEventListener('resize', fitViewport);
      window.visualViewport?.removeEventListener('scroll', fitViewport);
      window.removeEventListener('resize', fitViewport);
    };
  }, []);
  useEffect(() => {
    let cancelled = false;
    let checking = false;
    const load = async () => {
      if (!online || checking) return;
      checking = true;
      try {
        const context = await api.get<{ terminal?: TerminalCapability }>(remotePath({ deviceId }, '/remote-access/context/'));
        if (cancelled) return;
        setCapability(context.terminal); setLoaded(true);
        if (context.terminal?.enabled && context.terminal.supported) {
          const result = await api.get<{ sessions: TerminalSession[] }>(terminalPath(deviceId));
          if (!cancelled) setSessions(result.sessions);
        }
      } catch (failure) { if (!cancelled) setError(terminalError(failure)); }
      finally { checking = false; }
    };
    void load(); const timer = setInterval(() => void load(), 5000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [deviceId, online, refresh]);
  const ready = online && Boolean(capability?.enabled && capability.supported);
  const current = sessions.find(session => session.id === sessionId);
  const create = async () => {
    setBusy(true); setError(''); creationKey.current ||= terminalKey();
    try {
      const session = await terminalPost<TerminalSession>(deviceId, '', { cols: 80, rows: 24 }, creationKey.current!);
      creationKey.current = undefined;
      setSessions(previous => [...previous.filter(value => value.id !== session.id), session]);
      navigate(`${root}/${session.id}`);
    } catch (failure) {
      const status = (failure as { response?: { status?: number } }).response?.status;
      if (status && status < 500) creationKey.current = undefined;
      setError(terminalError(failure));
    } finally { setBusy(false); }
  };
  return <section ref={workspace} className="remote-terminal-workspace">
    <Space wrap className="remote-terminal-toolbar">
      <Select aria-label="选择终端会话" placeholder="选择已有终端" value={sessionId} style={{ minWidth: 210 }}
        onChange={id => navigate(`${root}/${id}`)} options={sessions.map((session, index) => ({ value: session.id,
          label: `终端 ${index + 1} · ${session.shell}${session.exited ? ' · 已退出' : ''}` }))} />
      <Button type="primary" disabled={!ready} loading={busy} onClick={() => void create()}>新建终端</Button>
      <Popconfirm title="关闭这个终端？" description="其中运行的程序也会结束。" onConfirm={async () => {
        try {
          await terminalPost(deviceId, `${sessionId}/close/`, {}, terminalKey());
          setSessions(previous => previous.filter(value => value.id !== sessionId)); navigate(root);
        } catch (failure) { setError(terminalError(failure)); }
      }}><Button danger disabled={!ready || !sessionId}>关闭终端</Button></Popconfirm>
      <Button disabled={!online} onClick={() => setRefresh(value => value + 1)}>刷新</Button>
    </Space>
    {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
    {loaded && !capability && <Alert type="info" showIcon message="这台电脑尚不支持远程终端，请升级电脑端。" />}
    {capability && !capability.supported && <Alert type="warning" showIcon message="电脑端的终端组件不可用，请安装终端依赖并重启本机服务。" />}
    {capability && !capability.enabled && <Alert type="info" showIcon message="请在这台电脑的“设置 → 远程访问”中开启“允许远程终端”。" />}
    {sessionId && capability?.enabled && capability.supported
      ? <TerminalView key={sessionId} deviceId={deviceId} sessionId={sessionId} online={ready}
          onExit={() => setRefresh(value => value + 1)} />
      : !sessionId && ready ? <Empty description="新建终端或选择已有会话，继续在这台电脑上操作。" /> : null}
    {current?.exited && <span className="remote-terminal-exit-note">此终端进程已退出，可查看输出或新建终端。</span>}
  </section>;
}

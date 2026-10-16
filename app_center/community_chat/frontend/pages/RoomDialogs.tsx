import { useEffect, useState } from 'react';
import { Avatar, Button, Drawer, Empty, Input, Modal, Popconfirm, Select, Space, Spin, message } from 'antd';
import { chat, errorText, type ChatUser, type RoomDetail, type ChatRoom } from '../services/chat';

function UserPicker({ multiple, onChange, value }: { multiple: boolean; onChange: (ids: number[]) => void; value: number[] }) {
  const [users, setUsers] = useState<ChatUser[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      void chat.users(query).then(result => { if (!cancelled) setUsers(result.users); })
        .catch(error => { if (!cancelled) message.error(errorText(error)); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query]);
  return <Select id="community-users" aria-label="搜索用户" showSearch filterOption={false} loading={loading}
    mode={multiple ? 'multiple' : undefined} value={multiple ? value : value[0]} onSearch={setQuery}
    onChange={(next: number[] | number) => onChange(Array.isArray(next) ? next : [next])}
    options={users.map(u => ({ value: u.id, label: `${u.nickname} (@${u.username})` }))}
    placeholder="输入用户名或昵称" notFoundContent={loading ? <Spin size="small" /> : '没有找到用户'} />;
}

export function NewChatDialog({ kind, onClose, onCreated }: { kind: 'direct' | 'group' | null; onClose: () => void; onCreated: (room: ChatRoom) => void }) {
  const [ids, setIds] = useState<number[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setIds([]); setName(''); }, [kind]);
  const submit = async () => {
    if (!kind || !ids.length || (kind === 'group' && !name.trim())) return;
    setBusy(true);
    try { onCreated(await chat.create(kind, ids, name)); onClose(); }
    catch (error) { message.error(errorText(error)); }
    finally { setBusy(false); }
  };
  return <Modal rootClassName="community-modal" open={!!kind} title={kind === 'group' ? '创建群聊' : '发起私聊'} onCancel={onClose}
    onOk={() => void submit()} confirmLoading={busy} okText="开始聊天" cancelText="取消"
    okButtonProps={{ disabled: !ids.length || (kind === 'group' && !name.trim()) }}>
    <div className="community-dialog-fields">
      {kind === 'group' && <><label htmlFor="community-group-name">群名称</label><Input id="community-group-name" maxLength={100} value={name} onChange={e => setName(e.target.value)} /></>}
      <label htmlFor="community-users">{kind === 'group' ? '邀请成员' : '选择用户'}</label>
      <UserPicker multiple={kind === 'group'} value={ids} onChange={setIds} />
      <p className="community-secondary">本站登录用户可以跨组织交流。{kind === 'group' && '加入群聊后可查看全部历史消息与文件。'}</p>
    </div>
  </Modal>;
}

export function GroupDrawer({ room, me, onClose, onChange }: { room: ChatRoom | null; me: number; onClose: () => void; onChange: () => void }) {
  const [detail, setDetail] = useState<RoomDetail | null>(null);
  const [name, setName] = useState('');
  const [ids, setIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = async (id: string) => {
    setError('');
    try { const result = await chat.detail(id); setDetail(result); setName(result.name); }
    catch (err) { setError(errorText(err)); }
  };
  useEffect(() => {
    setDetail(null); setIds([]);
    if (room) void load(room.id);
  }, [room?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (action: string, extra = {}) => {
    if (!room) return;
    setBusy(true);
    try {
      await chat.manage(room.id, action, extra); onChange();
      if (action === 'close' || action === 'leave') onClose();
      else { await load(room.id); setIds([]); }
    } catch (err) { message.error(errorText(err)); }
    finally { setBusy(false); }
  };
  const owner = detail?.owner_id === me;
  return <Drawer title="群聊详情" open={!!room} onClose={onClose} width="min(100vw, 420px)" rootClassName="community-drawer">
    {error ? <Empty description={error}><Button onClick={() => room && void load(room.id)}>重试</Button></Empty> : !detail ? <Spin /> : <div className="community-dialog-fields">
      <p className="community-secondary">新成员可以查看全部群历史。退群或被移除后无法继续访问消息与附件。</p>
      {owner ? <>
        <label htmlFor="community-rename">群名称</label>
        <Input id="community-rename" value={name} maxLength={100} onChange={e => setName(e.target.value)} />
        <Button loading={busy} disabled={!name.trim() || name === detail.name} onClick={() => void act('rename', { name })}>保存名称</Button>
        <label htmlFor="community-users">添加成员</label>
        <UserPicker multiple={false} value={ids} onChange={setIds} />
        <Button loading={busy} disabled={!ids.length} onClick={() => void act('add', { user_id: ids[0] })}>邀请加入</Button>
      </> : <h3>{detail.name}</h3>}
      <h3>群成员 · {detail.members.length}</h3>
      {detail.members.map(user => <div className="community-member" key={user.id}>
        <Avatar src={user.avatar || undefined}>{user.nickname.slice(0, 1)}</Avatar>
        <span>{user.nickname}<small>@{user.username}{user.id === detail.owner_id ? ' · 群主' : ''}</small></span>
        {owner && user.id !== me && <Space wrap>
          <Popconfirm title={`将群主转让给 ${user.nickname}？`} onConfirm={() => act('transfer', { user_id: user.id })} okText="转让" cancelText="取消"><Button size="small" disabled={busy}>转让</Button></Popconfirm>
          <Popconfirm title={`移除 ${user.nickname}？`} onConfirm={() => act('remove', { user_id: user.id })} okText="移除" cancelText="取消"><Button size="small" danger disabled={busy}>移除</Button></Popconfirm>
        </Space>}
      </div>)}
      <Popconfirm title={owner ? '解散后所有成员将无法访问此群，确定解散？' : '退出后将无法访问此群，确定退出？'}
        onConfirm={() => act(owner ? 'close' : 'leave')} okText="确定" cancelText="取消">
        <Button danger loading={busy}>{owner ? '解散群聊' : '退出群聊'}</Button>
      </Popconfirm>
      {owner && <small className="community-secondary">如需保留群聊并退出，请先向成员转让群主。</small>}
    </div>}
  </Drawer>;
}

import { Avatar, Button, Popconfirm, Progress } from 'antd';
import { FileOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ChatMessage, ChatUser, Draft } from '../services/chat';
import { formatSize } from '../services/chat';
import ChatAttachments from './ChatAttachments';

/** Pending and confirmed messages share one bubble and footer geometry. */
export default function ChatMessageRow({ item, draft, me, onRetry, onWithdraw }: {
  item?: ChatMessage; draft?: Draft; me: ChatUser;
  onRetry: (draft: Draft) => void; onWithdraw: (id: number) => Promise<void>;
}) {
  const author = item?.author || me;
  const mine = author.id === me.id;
  const createdAt = item?.created_at || draft!.created_at;
  const text = item?.text ?? draft?.text;
  const failed = !item && draft?.status === 'failed';
  const canWithdraw = item && !item.withdrawn && Date.now() - Date.parse(item.created_at) <= 120000;
  return <article className={`community-message ${mine ? 'community-message--mine' : ''}`}>
    <Avatar src={author.avatar || undefined}>{author.nickname.slice(0, 1)}</Avatar>
    <div className="community-message-content">
      <div className="community-message-meta"><span>{author.nickname}</span><time dateTime={createdAt}>{new Date(createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</time></div>
      <div className={`community-bubble ${item?.withdrawn ? 'community-bubble--withdrawn' : ''}`}>
        {item?.withdrawn ? '此消息已撤回' : <>
          {text && <p>{text}</p>}
          {item ? item.attachments.map(file => <ChatAttachments key={file.id} file={file} />) : draft?.files.map((file, index) => <div className="community-attachment" key={index}>
            <div className="community-file-row"><FileOutlined aria-hidden="true" /><span className="community-file-label">{file.name}<small>{formatSize(file.size)}</small></span></div>
          </div>)}
        </>}
      </div>
      {mine && !item?.withdrawn && <div className="community-message-footer" aria-live="polite">
        <small>{item ? '已发送' : failed ? '发送失败' : '发送中…'}</small>
        {canWithdraw ? <Popconfirm title="撤回这条消息？" okText="撤回" cancelText="取消" onConfirm={() => onWithdraw(item.id)}><Button type="text" size="small">撤回</Button></Popconfirm>
          : failed ? <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => onRetry(draft!)}>重试发送</Button>
            : <span className="community-message-action-space" aria-hidden="true" />}
      </div>}
      {!item && !!draft?.files.length && draft.status === 'sending' && <Progress percent={draft.progress} size="small" />}
      {failed && <div className="community-send-error" role="status">{draft?.error}</div>}
    </div>
  </article>;
}

import { useEffect, useState } from 'react';
import { Button, Image, message } from 'antd';
import { DownloadOutlined, FileOutlined, ReloadOutlined } from '@ant-design/icons';
import { chat, errorText, formatSize, type ChatFile } from '../services/chat';

export default function ChatAttachments({ file }: { file: ChatFile }) {
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!file.image) return;
    let cancelled = false;
    setFailed(false);
    void chat.access(file.id, true).then(value => { if (!cancelled) setUrl(value); }).catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [file.id, file.image, attempt]);

  const download = async () => {
    setLoading(true);
    try {
      const value = await chat.access(file.id);
      const link = document.createElement('a');
      link.href = value; link.download = file.name; link.rel = 'noreferrer';
      document.body.appendChild(link); link.click(); link.remove();
    } catch (error) { message.error(errorText(error)); }
    finally { setLoading(false); }
  };
  return <div className="community-attachment">
    {file.image && !failed && url && <Image src={url} alt={file.name} loading="lazy" onError={() => setFailed(true)}
      preview={{ onVisibleChange: visible => { if (visible) setAttempt(n => n + 1); } }} />}
    {file.image && failed && <Button icon={<ReloadOutlined />} onClick={() => setAttempt(n => n + 1)}>重新加载图片</Button>}
    <div className="community-file-row">
      <FileOutlined aria-hidden="true" />
      <span className="community-file-label">{file.name}<small>{formatSize(file.size)}</small></span>
      <Button type="text" aria-label={`下载 ${file.name}`} icon={<DownloadOutlined />} loading={loading} onClick={() => void download()} />
    </div>
  </div>;
}

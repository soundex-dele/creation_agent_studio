import { useRef, useState } from 'react';
import { Alert, Button, Modal } from 'antd';
import { readPlaylistFile, type PlaylistDraft } from '../services/playlistJson';

export function JsonPlaylistImport({ onClose, onReady }: { onClose: () => void; onReady: (draft: PlaylistDraft) => void }) {
  const [draft, setDraft] = useState<PlaylistDraft>();
  const [error, setError] = useState(''); const [reading, setReading] = useState(false);
  const generation = useRef(0);
  const close = () => { generation.current += 1; onClose(); };
  return <Modal className="song-modal" title="从 JSON 文件导入歌单" open onCancel={close} footer={null}>
    <p>支持 Playlist Out 导出的歌单，或包含 title、artist、album、version 的歌曲数组。</p>
    <div className="song-upload"><label htmlFor="song-json-file">选择歌单文件</label>
      <input id="song-json-file" type="file" accept=".json,.txt,application/json,text/plain" disabled={reading} onChange={event => {
        const file = event.target.files?.[0]; event.target.value = ''; if (!file) return;
        const current = ++generation.current; setReading(true); setError(''); setDraft(undefined);
        void readPlaylistFile(file).then(value => { if (current === generation.current) setDraft(value); })
          .catch(e => { if (current === generation.current) setError(e instanceof Error ? e.message : '读取失败，请重试。'); })
          .finally(() => { if (current === generation.current) setReading(false); });
      }} />
      <p className="song-muted">JSON 或保存 JSON 内容的 TXT · 最大 5 MB · 最多 500 首</p>
    </div>
    {reading && <p role="status">正在读取歌单…</p>}
    {error && <Alert type="error" message={error} showIcon />}
    {draft && <><p><strong>{draft.name}</strong> · {draft.tracks.length} 首歌曲</p>{draft.notice && <Alert type="warning" message={draft.notice} showIcon />}<p className="song-muted">下一步可修改歌曲信息、去除重复，并选择保存到新建或已有歌单。</p></>}
    <Button type="primary" loading={reading} disabled={!draft} onClick={() => { if (draft) onReady(draft); }}>核对歌单</Button>
  </Modal>;
}

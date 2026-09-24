import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Progress, Select } from 'antd';
import { audioFileError, meetingError, type MeetingClient, type MeetingRecord } from '@/services/meetingAssistant';
import { localDate } from '@/services/ideasTodos';

export function UploadRecording({ client, onClose, onCreated }: { client: MeetingClient; onClose: () => void; onCreated: (record: MeetingRecord) => void }) {
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('meeting');
  const [date, setDate] = useState(localDate());
  const [language, setLanguage] = useState('zh');
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const submit = async () => {
    if (!file || !title.trim() || !date) { setError('请填写标题、录音日期并选择录音文件。'); return; }
    const invalid = audioFileError(file);
    if (invalid) { setError(invalid); return; }
    setBusy(true); setError('');
    const body = new FormData();
    body.append('audio', file); body.append('title', title.trim()); body.append('kind', kind);
    body.append('recorded_on', date); body.append('language', language);
    controller.current = new AbortController();
    try { onCreated(await client.upload(body, setProgress, controller.current.signal)); }
    catch (e) { setError(meetingError(e)); }
    finally { setBusy(false); }
  };
  return <Modal open title="上传录音" onCancel={busy ? undefined : onClose} closable={!busy} maskClosable={!busy}
    footer={<><Button onClick={onClose} disabled={busy}>取消</Button><Button type="primary" htmlType="submit" form="meeting-upload" loading={busy}>上传并分析</Button></>}>
    <form id="meeting-upload" className="meeting-form" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <p className="meeting-muted">上传后自动生成逐字稿和摘要。行动项由你确认后加入待办。</p>
      {error && <Alert type="error" message={error} role="alert" />}
      <label>录音标题<Input value={title} maxLength={200} disabled={busy} onChange={e => setTitle(e.target.value)} required /></label>
      <div className="meeting-form-row"><label>类型<Select aria-label="录音类型" value={kind} disabled={busy} onChange={setKind} options={[{ value: 'meeting', label: '会议' }, { value: 'interview', label: '访谈' }]} /></label>
        <label>录音日期<Input type="date" value={date} disabled={busy} onChange={e => setDate(e.target.value)} required /></label></div>
      <label>转录语言<Select aria-label="转录语言" value={language} onChange={setLanguage} disabled={busy} options={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英语' }, { value: 'auto', label: '自动识别' }]} /></label>
      <label className="meeting-file">选择录音<input type="file" accept=".mp3,.wav,.m4a,.aac,.flac,.ogg" disabled={busy} onChange={e => {
        const selected = e.target.files?.[0] || null;
        setFile(selected); setError(selected ? audioFileError(selected) : '');
        if (selected && !title) setTitle(selected.name.replace(/\.[^.]+$/, '').slice(0, 200));
      }} /></label>
      <p className="meeting-muted">MP3、WAV、M4A、AAC、FLAC、OGG · 最长两小时 · 最大 200 MiB</p>
      {busy && <div role="status"><Progress percent={Math.min(progress, 100)} status="active" /><p>{progress >= 100 ? '正在校验音频，请稍候…' : '正在上传，请保持页面打开…'}</p></div>}
    </form>
  </Modal>;
}

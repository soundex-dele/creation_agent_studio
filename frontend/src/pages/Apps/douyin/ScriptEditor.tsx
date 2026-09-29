import { useEffect, useState } from 'react';
import { Alert, Button, Input, Select, Spin } from 'antd';
import { type DouyinClient, type Script, type ScriptVersion } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { saveResearchBlob } from '@/services/researchAssistant';

export function ScriptEditor({ client, accountId, taskId }: { client: DouyinClient; accountId: string; taskId: string }) {
  const [versions, setVersions] = useState<ScriptVersion[]>([]); const [selected, setSelected] = useState('');
  const [content, setContent] = useState<Script | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [dirty, setDirty] = useState(false); const [saved, setSaved] = useState(false);
  useEffect(() => {
    let active = true;
    void client.versions(accountId, taskId).then((rows) => { if (active) { setVersions(rows); setSelected(rows[0]?.id || ''); setContent(rows[0]?.content || null); } }).catch((e) => { if (active) setError(documentError(e)); });
    return () => { active = false; };
  }, [client, accountId, taskId]);
  function edit(next: Script) { setContent(next); setDirty(true); setSaved(false); }
  return <div className="douyin-form">
    {error && <Alert type="error" message={error} />}
    {saved && <Alert type="success" message="已保存新版本，之前的脚本仍保留。" />}
    {!content ? <Spin /> : <>
      <label>历史版本<Select aria-label="脚本历史版本" value={selected} disabled={dirty || busy} options={versions.map((v) => ({ value: v.id, label: `版本 ${v.revision} · ${new Date(v.created_at).toLocaleString('zh-CN')}` }))} onChange={(id) => { setSelected(id); setContent(versions.find((v) => v.id === id)!.content); setSaved(false); }} /></label>
      <label>标题<Input aria-label="脚本标题" value={content.title} maxLength={2000} onChange={(e) => edit({ ...content, title: e.target.value })} /></label>
      <label>封面短句<Input aria-label="封面短句" value={content.cover} maxLength={2000} onChange={(e) => edit({ ...content, cover: e.target.value })} /></label>
      <label>完整口播稿<Input.TextArea aria-label="完整口播稿" rows={12} value={content.narration} maxLength={20000} onChange={(e) => edit({ ...content, narration: e.target.value })} /></label>
      <h3>分镜与拍摄</h3>
      {content.scenes.map((s, index) => <div className="douyin-scene" key={index}><h4>镜头 {index + 1}</h4>{(['time', 'visual', 'spoken'] as const).map((field) => <label key={field}>{({ time: '时间', visual: '画面', spoken: '口播' })[field]}<Input.TextArea aria-label={`镜头${index + 1}${field}`} value={s[field]} autoSize={{ minRows: 1, maxRows: 8 }} maxLength={4000} onChange={(e) => edit({ ...content, scenes: content.scenes.map((scene, i) => i === index ? { ...scene, [field]: e.target.value } : scene) })} /></label>)}</div>)}
      <label>拍摄清单（每行一项）<Input.TextArea aria-label="拍摄清单" rows={5} value={content.checklist.join('\n')} onChange={(e) => edit({ ...content, checklist: e.target.value.split('\n') })} /></label>
      <div className="douyin-actions"><Button type="primary" loading={busy} disabled={!dirty} onClick={() => {
        setBusy(true); setError(''); void client.saveScript(accountId, taskId, versions[0].revision, content).then((v) => { setVersions((old) => [v, ...old]); setSelected(v.id); setContent(v.content); setDirty(false); setSaved(true); }).catch((e) => setError(documentError(e))).finally(() => setBusy(false));
      }}>保存新版本</Button><Button disabled={dirty || busy} onClick={() => { setError(''); void client.download(accountId, taskId, selected).then((blob) => saveResearchBlob(blob, `${content.title}.md`)).catch((e) => setError(documentError(e))); }}>导出 Markdown</Button>
      {dirty && <Button onClick={() => { setContent(versions.find((v) => v.id === selected)!.content); setDirty(false); }}>撤销本次编辑</Button>}</div>
      {dirty && <small>有未保存修改，请保存后切换版本或导出。</small>}
    </>}
  </div>;
}

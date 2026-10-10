import { useEffect, useState } from 'react';
import { Alert, Button, Input, Select, Spin } from 'antd';
import type { ArticleContent, ResearchClient, ResearchVersion, StyleReview } from '@/services/douyinResearch';
import { documentError } from '@/services/documents';
import { saveResearchBlob } from '@/services/researchAssistant';
import { Field } from './ResearchCommon';

function article(version: ResearchVersion): ArticleContent {
  return { ...(version.content.cover !== undefined && { cover: version.content.cover }), title: version.content.title || '', body: version.content.body || '', notes: version.content.notes || [] };
}

export function ArticleEditor({ client, taskId, onDirty, styleReview }: { client: ResearchClient; taskId: string; onDirty?: (value: boolean) => void; styleReview?: StyleReview }) {
  const [versions, setVersions] = useState<ResearchVersion[]>([]); const [selected, setSelected] = useState('');
  const [content, setContent] = useState<ArticleContent | null>(null); const [dirty, setDirty] = useState(false);
  const [error, setError] = useState(''); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false); const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    void client.versions(taskId).then(rows => {
      if (!alive) return; setVersions(rows);
      if (!rows.length) { setError('文章版本尚未就绪，请刷新版本记录。'); return; }
      setSelected(old => old || rows[0].id); setContent(old => old || article(rows[0])); setError('');
    }).catch(e => { if (alive) setError(documentError(e)); });
    return () => { alive = false; };
  }, [client, taskId, tick]);
  useEffect(() => { onDirty?.(dirty); return () => onDirty?.(false); }, [dirty, onDirty]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await fn(); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } }
  function edit(value: ArticleContent) { setContent(value); setDirty(true); setMessage(''); }
  const reviewApplies = !dirty && versions.find(v => v.id === selected)?.revision === styleReview?.revision;
  return <section className="douyin-form" aria-label="文章编辑器"><h3>文章写作</h3>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setTick(v => v + 1)}>刷新版本记录</Button>} />}{message && <Alert type="success" message={message} />}
    {!content && !error && <Spin />}
    {content && <>
      <Field label="文章历史版本"><Select aria-label="文章历史版本" value={selected} disabled={dirty || busy} options={versions.map(v => ({ value: v.id, label: `版本 ${v.revision} · ${new Date(v.created_at).toLocaleString('zh-CN')}` }))} onChange={id => { const version = versions.find(v => v.id === id); if (version) { setSelected(id); setContent(article(version)); setMessage(''); } }} /></Field>
      {styleReview && <Alert type={reviewApplies && styleReview.status === 'unavailable' ? 'warning' : 'info'}
        message={reviewApplies ? { completed: `生成版本 ${styleReview.revision} 已完成模型文风校对`, unavailable: '文风校对未完成，已保留初稿', not_applicable: '未进行文风校对' }[styleReview.status] : '当前修改未进行文风校对'}
        description={reviewApplies ? `${styleReview.summary} ${styleReview.status === 'completed' ? '模型校对不代表事实或风格已通过人工核验。' : ''}` : `校对记录仅对应生成版本 ${styleReview.revision}，不适用于后续修改。`} />}
      <Field label="文章标题"><Input aria-label="文章标题" maxLength={300} value={content.title} onChange={e => edit({ ...content, title: e.target.value })} /></Field>
      {content.cover !== undefined && <Field label="封面短句"><Input aria-label="封面短句" maxLength={300} value={content.cover} onChange={e => edit({ ...content, cover: e.target.value })} /></Field>}
      <Field label="文章正文"><Input.TextArea aria-label="文章正文" rows={18} maxLength={20000} value={content.body} onChange={e => edit({ ...content, body: e.target.value })} /></Field>
      <p>正文 {content.body.replace(/\s/g, '').length} 字符</p>
      {!!content.notes.length && <Alert type="warning" message="待核实或补充（不包含在复制和导出的文章中）" description={<ul>{content.notes.map((note, i) => <li key={i}>{note}</li>)}</ul>} />}
      <div className="douyin-actions">
        <Button type="primary" loading={busy} disabled={!dirty || !content.title.trim() || !content.body.trim() || !versions.length} onClick={() => void action(async () => { const version = await client.saveVersion(taskId, versions[0].revision, content); setVersions(old => [version, ...old]); setSelected(version.id); setContent(article(version)); setDirty(false); setMessage('文章已保存为新版本。'); })}>保存文章新版本</Button>
        <Button disabled={busy} onClick={() => void action(async () => { if (!navigator.clipboard?.writeText) throw new Error('当前环境不支持自动复制，请在正文输入框中手动选择复制。'); await navigator.clipboard.writeText(content.body); setMessage('当前正文已复制。'); })}>复制正文</Button>
        <Button disabled={dirty || busy} onClick={() => void action(async () => { const blob = await client.editor.download('', taskId, selected); saveResearchBlob(blob, `${content.title}.md`); })}>导出文章 Markdown</Button>
        {dirty && <Button disabled={busy} onClick={() => { const version = versions.find(v => v.id === selected); if (version) setContent(article(version)); setDirty(false); }}>撤销文章修改</Button>}
      </div>{dirty && <p>有未保存的文章修改，请保存后切换账号、任务或版本。</p>}
    </>}
  </section>;
}

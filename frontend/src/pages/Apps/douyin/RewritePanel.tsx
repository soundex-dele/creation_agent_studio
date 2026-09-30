import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Input, Select, Spin } from 'antd';
import { type DouyinClient, type DouyinTask, type Kind, type RewriteVersion, isActive } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { saveResearchBlob } from '@/services/researchAssistant';

export function RewritePanel({ client, accountId, task, busy, onRun }: {
  client: DouyinClient; accountId: string; task: DouyinTask; busy: boolean;
  onRun: (body: { kind: Kind; [key: string]: unknown }) => Promise<void>;
}) {
  const isRewrite = task.kind === 'rewrite';
  const [sourceText, setSourceText] = useState(isRewrite ? task.copy_context?.source_text || '' : task.output.text || '');
  const [requirements, setRequirements] = useState(task.copy_context?.rewrite_requirements || '');
  const [versions, setVersions] = useState<RewriteVersion[]>([]);
  const [selected, setSelected] = useState('');
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(isRewrite && task.status === 'succeeded');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  const dirty = Boolean(selected && text !== versions.find(v => v.id === selected)?.content.text);
  const active = isActive(task);
  const locked = busy || saving || active;
  const sourceId = isRewrite ? task.copy_context?.source_task_id : task.id;
  useEffect(() => {
    if (!isRewrite || task.status !== 'succeeded') return;
    let mounted = true;
    setLoading(true);
    void client.rewriteVersions(accountId, task.id).then(rows => {
      if (!mounted) return;
      setVersions(rows); setSelected(rows[0]?.id || ''); setText(rows[0]?.content.text || ''); setError('');
      if (!rows.length) setError('文案版本暂不可用，请重新加载。');
    }).catch(e => { if (mounted) setError(documentError(e)); }).finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [client, accountId, task.id, task.status, isRewrite, reload]);

  return <div className="douyin-form douyin-rewrite">
    <p className="douyin-hint">来源作品：{task.copy_context?.work_title || '未命名作品'}。保留原主题和事实，重新组织表达。</p>
    {error && <Alert type="error" message={error} action={!dirty && isRewrite ? <Button onClick={() => setReload(v => v + 1)}>重新加载文案</Button> : undefined} />}
    {notice && <Alert type="success" message={notice} />}
    <div className="douyin-rewrite-columns">
      <section className="douyin-form" aria-label="原文与改写要求">
        <h3>校正原文</h3>
        {task.output.transcript_note && <Alert type="info" message={task.output.transcript_note} />}
        <label>口播原文<Input.TextArea aria-label="口播原文" rows={16} maxLength={20000} showCount value={sourceText} disabled={locked} onChange={e => setSourceText(e.target.value)} /></label>
        <label>改写要求（可选）<Input.TextArea aria-label="改写要求" rows={3} maxLength={3000} value={requirements} disabled={locked} placeholder="例如：开头更直接，语气自然，减少书面表达" onChange={e => setRequirements(e.target.value)} /></label>
        <div className="douyin-actions">
          <Button type="primary" loading={busy} disabled={locked || dirty || !sourceId || !sourceText.trim() || sourceText.length > 20000} onClick={() => void onRun({ kind: 'rewrite', work_id: task.work_id, source_task_id: sourceId, source_text: sourceText, rewrite_requirements: requirements })}>{task.status === 'failed' || task.status === 'cancelled' ? '重试改写' : '生成改写文案'}</Button>
          <Button disabled={locked || dirty} onClick={() => void onRun({ kind: 'transcribe', work_id: task.work_id, force: true })}>重新转写</Button>
        </div>
        <small className="douyin-footnote">校正只用于本次改写，不会覆盖原始转写。重新转写会创建新任务。</small>
      </section>
      <section className="douyin-form" aria-label="改写结果">
        <h3>改写文案</h3>
        {loading || active ? <div role="status"><Spin /> {active ? '正在改写文案…' : '正在加载文案…'}</div> : !selected ? <Empty description={isRewrite ? '暂无改写结果，可在左侧重试。' : '校正原文后，生成你的改写文案。'} /> : <>
          <label>历史版本<Select aria-label="文案历史版本" value={selected} disabled={dirty || locked} options={versions.map(v => ({ value: v.id, label: `版本 ${v.revision} · ${new Date(v.created_at).toLocaleString('zh-CN')}` }))} onChange={id => { setSelected(id); setText(versions.find(v => v.id === id)!.content.text); setNotice(''); }} /></label>
          <label>正文<Input.TextArea aria-label="改写正文" rows={20} maxLength={20000} showCount value={text} disabled={saving} onChange={e => { setText(e.target.value); setNotice(''); }} /></label>
          <div className="douyin-actions">
            <Button type="primary" disabled={!dirty || !text.trim() || locked} loading={saving} onClick={() => {
              setSaving(true); setError(''); setNotice('');
              void client.saveRewrite(accountId, task.id, versions[0].revision, { text }).then(v => { setVersions(old => [v, ...old]); setSelected(v.id); setText(v.content.text); setNotice('已保存新版本，之前的文案仍保留。'); }).catch(e => setError(documentError(e))).finally(() => setSaving(false));
            }}>保存文案新版本</Button>
            <Button disabled={saving || !text.trim()} onClick={() => {
              setError(''); setNotice('');
              if (!navigator.clipboard?.writeText) { setError('当前环境无法自动复制，请选中正文手动复制。'); return; }
              void navigator.clipboard.writeText(text).then(() => setNotice('文案已复制。')).catch(() => setError('复制失败，请选中正文手动复制。'));
            }}>复制文案</Button>
            <Button disabled={dirty || locked} onClick={() => { setError(''); void client.download(accountId, task.id, selected).then(blob => saveResearchBlob(blob, `复刻文案-v${versions.find(v => v.id === selected)?.revision}.md`)).catch(e => setError(documentError(e))); }}>导出文案 Markdown</Button>
            {dirty && <Button disabled={saving} onClick={() => { setText(versions.find(v => v.id === selected)!.content.text); setError(''); }}>撤销文案修改</Button>}
          </div>
          {dirty && <small>有未保存修改，请保存后切换版本、导出或重新生成。</small>}
        </>}
      </section>
    </div>
  </div>;
}

import { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { structuredStreamText } from '@/lib/structuredStreamText';
import { isActive, type DouyinTask } from '@/services/douyinBenchmark';
import './GenerationPreview.css';

const labels: Record<string, string> = {
  title: '标题', body: '正文', notes: '待核实事项', topics: '选题', angle: '角度', hook: '开头',
  pillar: '内容支柱', reason: '适合原因', materials_needed: '待补充素材', duplicate_note: '重复提醒',
  content: '分析结果', current_positioning: '历史定位', positioning: '目标定位', audience: '受众推测',
  content_pillars: '内容支柱', content_boundaries: '内容边界', rules: '表达规则', examples: '原文示例',
  avoid: '避免的表达', prompt: '创作提示词', findings: '文风分析', dimension: '维度',
  keep: '建议保留', improve: '建议改善', text: '内容', quote: '原文依据', evidence: '依据',
  claims: '分析结论', narration: '口播稿', cover: '封面短句', scenes: '分镜',
  time: '时间', visual: '画面', spoken: '口播', checklist: '准备事项',
  hooks: '开头', titles: '标题', covers: '封面短句',
  style_features: '文风观察', instruction: '怎么写', when: '适用条件', deviation: '风格偏离',
  article: '校对后的文章', summary: '修订说明',
};

export function GenerationPreview({ task }: { task: Pick<DouyinTask, 'id' | 'status' | 'progress'> }) {
  const preview = task.progress.ai_preview;
  const [open, setOpen] = useState(true);
  const [following, setFollowing] = useState(true);
  const output = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const text = structuredStreamText(preview?.text || '', labels);
  useEffect(() => { setOpen(true); setFollowing(true); follow.current = true; }, [task.id]);
  useEffect(() => {
    if (open && follow.current && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [text, open]);
  if (!preview || task.status === 'succeeded') return null;
  const active = isActive(task);
  const status = !active ? '生成已停止，以下是已收到的未完成内容。'
    : preview.state === 'received' ? '已收到回复，正在校验结果…'
    : text ? '正在接收 AI 回复…' : '等待 AI 返回内容…';
  return <section className="douyin-generation-preview" aria-label="AI 生成预览">
    <div className="douyin-section-title"><strong>AI 返回内容</strong><Button type="text" aria-expanded={open} aria-controls={`generation-${task.id}`} onClick={() => setOpen(value => !value)}>{open ? '收起内容' : '展开内容'}</Button></div>
    <p role="status">{status}</p>
    {open && <><div id={`generation-${task.id}`} className="douyin-generation-output" ref={output} role="region" aria-label="逐步生成的内容" tabIndex={0} onScroll={() => {
      const node = output.current;
      if (node) { follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 32; setFollowing(follow.current); }
    }}>{text || '模型开始输出后会逐步显示；若模型集中返回，内容会在收到后出现。'}</div>
      {!following && <Button onClick={() => { follow.current = true; setFollowing(true); if (output.current) output.current.scrollTop = output.current.scrollHeight; }}>回到最新内容</Button>}
      <p>生成中的内容尚未校验，每约 2.5 秒更新。完成后显示正式结果。</p></>}
  </section>;
}

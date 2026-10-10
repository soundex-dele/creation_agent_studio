import { Button, Empty } from 'antd';
import type { RepoTask, RepoTopic } from '@/services/repoExplainer';

export default function RepoTopicCards({ task, selectedId, disabled, onSelect, onEvidence }: {
  task?: RepoTask; selectedId: string; disabled: boolean;
  onSelect: (topic: RepoTopic) => void; onEvidence: (id: string) => void;
}) {
  if (!task || task.status !== 'succeeded') return <Empty description="导入仓库后即可生成选题，无需先解析功能" />;
  const coverage = task.output.coverage;
  return <>
    <div className="repo-card"><h2>本批选题</h2><p>限定方向：{String(task.options.direction || '不限方向')}</p>
      {coverage && <p>已读取 {coverage.files_read}/{coverage.files_total} 个文件、{coverage.chunks_read}/{coverage.chunks_total} 个片段。{coverage.note}</p>}
    </div>
    <div className="repo-topic-grid">{task.output.topics?.map(topic => <article className="repo-card repo-topic-card" key={topic.id}>
      <h3>{topic.title}</h3><p>{topic.angle}</p><p>适合人群：{topic.audience}</p>
      <h4>内容提纲</h4><ol>{topic.outline.map((item, index) => <li key={index}>{item}</li>)}</ol>
      <h4>源码依据</h4><div className="repo-actions">{topic.evidence_ids.map(id => <Button key={id} onClick={() => onEvidence(id)}>{task.output.evidence?.[id]?.path || id} · {id}</Button>)}</div>
      <h4>待核实事项</h4>{topic.notes.length ? <ul>{topic.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : <p>仅静态读取，实际运行效果仍需验证。</p>}
      <Button type={selectedId === topic.id ? 'primary' : 'default'} aria-pressed={selectedId === topic.id} disabled={disabled}
        onClick={() => onSelect(topic)}>用此选题写文案</Button>
    </article>)}</div>
  </>;
}

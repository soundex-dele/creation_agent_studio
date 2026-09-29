import React from 'react';
import type { AgentActivityState } from '@/entities/run';
import './AgentActivityPanel.css';

const text = (value: unknown): string => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
const warningText = (warning: Record<string, unknown>): string => text(
  warning.message ?? warning.summary ?? (warning.error as Record<string, unknown> | undefined)?.message
    ?? warning.reason ?? warning.method,
);

const isCodexStartupNotice = (warning: Record<string, unknown>): boolean => (
  // Filter at render time so saved conversations receive the same treatment.
  (warning.method == null || ['warning', 'configWarning'].includes(String(warning.method)))
    && /^(?:Codex is ignoring \d+ unrecognized configuration settings?\.|Under-development features enabled:)/i.test(warningText(warning).trim())
);

export default function AgentActivityPanel({ activity }: { activity?: AgentActivityState }) {
  if (!activity) return null;
  const states: Record<string, string> = { pending: '待开始', inProgress: '进行中', completed: '已完成' };
  const agentStates: Record<string, string> = { started: '已启动', interacted: '收到新指令', interrupted: '已中断' };
  const warnings = activity.warnings?.filter(warning => (
    warning.method !== 'mcpServer/startupStatus/updated'
      && !isCodexStartupNotice(warning)
      && !/Model metadata for .+ not found\. Defaulting to fallback metadata/i.test(warningText(warning))
      && !/Codex could not find bubblewrap on PATH\./i.test(warningText(warning))
  )) ?? [];
  const tools = Object.entries(activity.tools ?? {}).filter(([, tool]) => tool.method === 'item/fileChange/patchUpdated');
  const items = Object.values(activity.items ?? {}).filter(item => !['agentMessage', 'plan', 'reasoning'].includes(item.type));
  if (!activity.plan?.plan?.length && !warnings.length && !tools.length && !activity.diff?.diff && !items.length) return null;
  return <div className="agent-activity-panel">
    {!!activity.plan?.plan?.length && <section aria-label="执行步骤" className="agent-plan-progress">
      <strong>执行步骤</strong>
      {activity.plan.explanation && <p>{activity.plan.explanation}</p>}
      <ol>{activity.plan.plan.map((step, index) => <li key={index}>
        <span className={`agent-step-state agent-step-state--${step.status}`}>{states[step.status] ?? step.status}</span>
        <span>{step.step}</span>
      </li>)}</ol>
    </section>}
    {warnings.map((warning, index) => <div className="agent-notice" role="status" key={index}>
      {warningText(warning)}
      {!!warning.details && <details><summary>查看详情</summary><pre>{text(warning.details)}</pre></details>}
    </div>)}
    {tools.map(([id, tool]) => <details key={id} className="agent-activity-detail">
      <summary>文件修改</summary>
      <pre>{text(tool.output ?? tool.patch ?? tool.message ?? tool)}</pre>
    </details>)}
    {!!activity.diff?.diff && <details className="agent-activity-detail">
      <summary>查看本轮代码变更</summary>
      <pre className="agent-diff">{activity.diff.diff.split('\n').map((line, index) => <span key={index}
        className={line.startsWith('+') ? 'agent-diff-add' : line.startsWith('-') ? 'agent-diff-remove' : undefined}>{line}{'\n'}</span>)}</pre>
    </details>}
    {items.map(item =>
      <details key={item.id} className="agent-activity-detail">
        <summary>{item.type === 'contextCompaction' ? '上下文已压缩'
          : item.type === 'subAgentActivity' ? `${item.agentNickname || item.agentRole || item.agentPath || '子任务'} · ${agentStates[item.kind ?? ''] || item.status || '执行中'}` : '审查结果'}</summary>
        <pre>{item.summary?.join('\n\n') || item.review || item.text || agentStates[item.kind ?? ''] || item.status || ''}</pre>
      </details>)}
  </div>;
}

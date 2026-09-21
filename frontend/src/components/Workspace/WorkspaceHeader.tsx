import type { ReactNode } from 'react';
import './WorkspaceHeader.css';

interface WorkspaceHeaderProps {
  icon: ReactNode;
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
  loading?: boolean;
  metrics: { label: string; value: number; hint: string }[];
}

export default function WorkspaceHeader({
  icon, eyebrow, title, description, action, loading, metrics,
}: WorkspaceHeaderProps) {
  return (
    <header className="workspace-header">
      <div className="workspace-header-main">
        <div className="workspace-header-copy">
          <div className="workspace-eyebrow"><span aria-hidden="true">{icon}</span>{eyebrow}</div>
          <h1 className="page-title">{title}</h1>
          <p className="page-subtitle">{description}</p>
        </div>
        {action && <div className="workspace-header-action">{action}</div>}
      </div>
      <dl className="workspace-metrics" aria-label={`${title}概览`} aria-busy={loading}>
        {metrics.map((metric) => (
          <div className="workspace-metric" key={metric.label}>
            <dt>{metric.label}<span>{metric.hint}</span></dt>
            <dd>{loading ? '—' : metric.value.toLocaleString('zh-CN')}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

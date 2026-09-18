import type { ReactNode } from 'react';
import { ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import './CapabilityHubPage.css';

export interface CapabilityHubItem {
  path: string;
  title: string;
  description: string;
  icon: ReactNode;
  eyebrow: string;
}

export default function CapabilityHubPage({
  eyebrow,
  title,
  description,
  items,
}: {
  eyebrow: string;
  title: string;
  description: string;
  items: CapabilityHubItem[];
}) {
  const navigate = useNavigate();
  return <div className="capability-hub animate-fade-in">
    <header className="capability-hub-heading">
      <span>{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
    <div className="capability-hub-grid">
      {items.map((item) => <button type="button" key={item.path} onClick={() => navigate(item.path)}>
        <span className="capability-hub-icon" aria-hidden="true">{item.icon}</span>
        <span className="capability-hub-copy">
          <small>{item.eyebrow}</small>
          <strong>{item.title}</strong>
          <span>{item.description}</span>
        </span>
        <ArrowRightOutlined className="capability-hub-arrow" aria-hidden="true" />
      </button>)}
    </div>
  </div>;
}

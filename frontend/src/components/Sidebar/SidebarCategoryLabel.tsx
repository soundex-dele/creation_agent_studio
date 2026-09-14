import type { ReactNode } from 'react';

interface SidebarCategoryLabelProps {
  label: string;
  count: number;
  countUnit: string;
  icon?: ReactNode;
}

const SidebarCategoryLabel = ({
  label,
  count,
  countUnit,
  icon,
}: SidebarCategoryLabelProps) => (
  <span className="sidebar-menu-label">
    <span className="sidebar-menu-label-text">
      {icon ? <span className="sidebar-menu-label-icon" aria-hidden="true">{icon}</span> : null}
      {label}
    </span>
    <span className="sidebar-menu-count" aria-label={`${count} 个${countUnit}`}>
      {count}
    </span>
  </span>
);

export default SidebarCategoryLabel;

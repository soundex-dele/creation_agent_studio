import { useLocation } from 'react-router-dom';
import AgentCategoriesSidebar from './AgentCategoriesSidebar';
import TemplateHistorySidebar from './TemplateHistorySidebar';
import AppHistorySidebar from './AppHistorySidebar';
import ProjectListSidebar from './ProjectListSidebar';
import HomeApplicationsSidebar from './HomeApplicationsSidebar';
import './Sidebar.css';

export const hasSidebarContent = (path: string) => (
  path === '/'
  || path === ''
  || path.startsWith('/agents')
  || path.startsWith('/applications')
  || path.startsWith('/apps')
  || path.startsWith('/templates')
  || path.startsWith('/workspace')
);

const Sidebar = () => {
  const location = useLocation();
  const path = location.pathname;

  const renderSidebar = () => {
    if (path === '/' || path === '') {
      return <HomeApplicationsSidebar />;
    }
    if (path.startsWith('/agents')) {
      return <AgentCategoriesSidebar />;
    }
    if (path.startsWith('/applications') || path.startsWith('/apps/case-library')) {
      return <HomeApplicationsSidebar />;
    }
    if (path.startsWith('/templates')) {
      return <TemplateHistorySidebar />;
    }
    if (path.startsWith('/apps')) {
      return <AppHistorySidebar />;
    }
    if (path.startsWith('/workspace')) {
      return <ProjectListSidebar />;
    }
    return null;
  };

  return (
    <aside className="app-sidebar">
      {renderSidebar()}
    </aside>
  );
};

export default Sidebar;

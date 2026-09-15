import { useLocation, useNavigate } from 'react-router-dom';
import AgentCategoriesSidebar from './AgentCategoriesSidebar';
import TemplateHistorySidebar from './TemplateHistorySidebar';
import AppHistorySidebar from './AppHistorySidebar';
import ProjectListSidebar from './ProjectListSidebar';
import ConversationHistory from '../ConversationHistory/ConversationHistory';
import HomeApplicationsSidebar from './HomeApplicationsSidebar';
import './Sidebar.css';

const Sidebar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname;

  const renderSidebar = () => {
    if (path === '/' || path === '') {
      return <HomeApplicationsSidebar />;
    }
    if (path.startsWith('/chat')) {
      return (
        <ConversationHistory
          activeConversationId={new URLSearchParams(location.search).get('conversation')}
          onConversationSelect={(id: string) => {
            navigate(id ? `/chat?conversation=${id}` : '/chat');
          }}
        />
      );
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

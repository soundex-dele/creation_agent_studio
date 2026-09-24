import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, useLocation, useParams } from 'react-router-dom';
import { MainLayout, AuthLayout } from '@/layouts';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { ProtectedRoute, PublicRoute } from './guards';

const HomePage = lazy(() => import('@/pages/Home/HomePage'));
const TaskCenterPage = lazy(() => import('@/pages/Tasks/TaskCenterPage'));
const BuildPage = lazy(() => import('@/pages/Hubs/BuildPage'));
const ResourceLibraryPage = lazy(() => import('@/pages/Hubs/ResourceLibraryPage'));
const ChatPage = lazy(() => import('@/pages/Chat/ChatPage'));
const LoginPage = lazy(() => import('@/pages/Auth/LoginPage'));
const RegisterPage = lazy(() => import('@/pages/Auth/RegisterPage'));
const SsoCallbackPage = lazy(() => import('@/pages/Auth/SsoCallbackPage'));
const AgentsPage = lazy(() => import('@/pages/Agents/AgentsPage'));
const AgentDetailPage = lazy(() => import('@/pages/Agents/AgentDetailPage'));
const TemplatesPage = lazy(() => import('@/pages/Templates/TemplatesPage'));
const TemplateDetailPage = lazy(() => import('@/pages/Templates/TemplateDetailPage'));
const AppsPage = lazy(() => import('@/pages/Apps/AppsPage'));
const AppDetailPage = lazy(() => import('@/pages/Apps/AppDetailPage'));
const MyComputerPage = lazy(() => import('@/pages/Apps/MyComputerPage'));
const DurableApplicationRuntimePage = lazy(() => import('@/pages/Apps/DurableApplicationRuntimePage'));
const ChatApplicationRuntimePage = lazy(() => import('@/pages/Apps/ChatApplicationRuntimePage'));
const WorkspacePage = lazy(() => import('@/pages/Workspace/WorkspacePage'));
const WorkflowsPage = lazy(() => import('@/pages/Workflows/WorkflowsPage'));
const WorkflowEditorPage = lazy(() => import('@/pages/Workflows/WorkflowEditorPage'));
const WorkflowRunnerPage = lazy(() => import('@/pages/Workflows/WorkflowRunnerPage'));
const WorkflowManualRunnerPage = lazy(() => import('@/pages/Workflows/WorkflowManualRunnerPage'));
const SkillsPage = lazy(() => import('@/pages/Skills/SkillsPage'));
const EnterprisePage = lazy(() => import('@/pages/Enterprise/EnterprisePage'));
const StudyWithMethodPage = lazy(() => import('@/pages/StudyWithMethod/StudyWithMethodPage'));
const CreationMasterPage = lazy(() => import('@/pages/Apps/CreationMasterPage'));
const WechatAssistantPage = lazy(() => import('@/pages/Apps/WechatAssistantPage'));
const CreationToolboxPage = lazy(() => import('@/pages/Apps/CreationToolboxPage'));
const IdeasTodosPage = lazy(() => import('@/pages/Apps/IdeasTodosPage'));
const DocumentsPage = lazy(() => import('@/pages/Apps/DocumentsPage'));
const ResearchAssistantPage = lazy(() => import('@/pages/Apps/ResearchAssistantPage'));
const MeetingAssistantPage = lazy(() => import('@/pages/Apps/MeetingAssistantPage'));
const AIDrawingPage = lazy(() => import('@/pages/Apps/AIDrawingPage'));
const MyDrivePage = lazy(() => import('@/pages/Apps/MyDrivePage'));
const ProfilePage = lazy(() => import('@/pages/Profile/ProfilePage'));
const SettingsPage = lazy(() => import('@/pages/Settings/SettingsPage'));
const AccountManagementPage = lazy(() => import('@/pages/Settings/AccountManagementPage'));
const KnowledgePage = lazy(() => import('@/pages/Knowledge/KnowledgePage'));
const DelegatesPage = lazy(() => import('@/pages/Delegates/DelegatesPage'));
const DelegateEditorPage = lazy(() => import('@/pages/Delegates/DelegateEditorPage'));
const DelegateTaskPage = lazy(() => import('@/pages/Delegates/DelegateTaskPage'));
const AutomationsPage = lazy(() => import('@/pages/Automations/AutomationsPage'));
const AutomationEditorPage = lazy(() => import('@/pages/Automations/AutomationEditorPage'));
const AutomationDetailPage = lazy(() => import('@/pages/Automations/AutomationDetailPage'));

const page = (element: ReactNode) => (
  <Suspense fallback={<div style={{ padding: 32 }}>正在加载…</div>}>{element}</Suspense>
);

const LegacyTemplateRedirect = () => {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={id ? `/apps/case-library/${id}` : '/apps/case-library'} replace />;
};

const ApplicationShell = ({ children, fullBleed = false }: {
  children: ReactNode;
  fullBleed?: boolean;
}) => {
  const location = useLocation();
  const { showPlatformChrome } = resolveApplicationPresentation(
    new URLSearchParams(location.search),
  );
  return (
    <MainLayout
      hideHeader={!showPlatformChrome}
      hideSidebar={!showPlatformChrome}
      fullBleed={fullBleed}
    >
      {children}
    </MainLayout>
  );
};

const router = createBrowserRouter([
  ...['/apps/my-computer', '/apps/my-computer/:deviceId', '/apps/my-computer/:deviceId/conversations/:conversationId',
    '/apps/my-computer/:deviceId/terminals', '/apps/my-computer/:deviceId/terminals/:sessionId', '/apps/my-computer/:deviceId/files'].map(path => ({
    path,
    element: <ProtectedRoute><MainLayout hideSidebar fullBleed>{page(<MyComputerPage />)}</MainLayout></ProtectedRoute>,
  })),
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <MainLayout>
          {page(<HomePage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
    index: true,
  },
  {
    path: '/tasks',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<TaskCenterPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/build',
    element: <ProtectedRoute><MainLayout hideSidebar fullBleed>{page(<BuildPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/resources',
    element: <ProtectedRoute><MainLayout hideSidebar fullBleed>{page(<ResourceLibraryPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/delegates',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<DelegatesPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/delegates/new',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<DelegateEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/delegates/:id',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<DelegateEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/delegates/:id/tasks/:conversationId',
    element: <ProtectedRoute><MainLayout hideSidebar fullBleed>{page(<DelegateTaskPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/chat',
    element: (
      <ProtectedRoute>
        <MainLayout>
          {page(<ChatPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/agents',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<AgentsPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/agents/:id',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<AgentDetailPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/templates',
    element: (
      <ProtectedRoute>
        <LegacyTemplateRedirect />
      </ProtectedRoute>
    ),
  },
  {
    path: '/templates/:id',
    element: (
      <ProtectedRoute>
        <LegacyTemplateRedirect />
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<AppsPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/case-library',
    element: (
      <ProtectedRoute>
        <ApplicationShell>
          {page(<TemplatesPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/case-library/:id',
    element: (
      <ProtectedRoute>
        <ApplicationShell>
          {page(<TemplateDetailPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/:id',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<AppDetailPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/chat',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<ChatApplicationRuntimePage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/run',
    element: (
      <ProtectedRoute>
        <ApplicationShell>
          {page(<DurableApplicationRuntimePage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/study-with-method',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<StudyWithMethodPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/creation-master',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<CreationMasterPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/wechat-assistant',
    element: <ProtectedRoute><ApplicationShell fullBleed>{page(<WechatAssistantPage />)}</ApplicationShell></ProtectedRoute>,
  },
  {
    path: '/applications/:applicationId/creation-toolbox',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<CreationToolboxPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/meeting-assistant',
    element: <ProtectedRoute><ApplicationShell fullBleed>{page(<MeetingAssistantPage />)}</ApplicationShell></ProtectedRoute>,
  },
  {
    path: '/applications/:applicationId/research-assistant',
    element: <ProtectedRoute><ApplicationShell fullBleed>{page(<ResearchAssistantPage />)}</ApplicationShell></ProtectedRoute>,
  },
  {
    path: '/applications/:applicationId/documents',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<DocumentsPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/ai-drawing',
    element: <ProtectedRoute><ApplicationShell fullBleed>{page(<AIDrawingPage />)}</ApplicationShell></ProtectedRoute>,
  },
  {
    path: '/applications/:applicationId/my-drive',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<MyDrivePage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/ideas-todos',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<IdeasTodosPage />)}
        </ApplicationShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/knowledge',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<KnowledgePage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/skills',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<SkillsPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/workflows',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<WorkflowsPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/workflows/new',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<WorkflowEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/workflows/:id/edit',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<WorkflowEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/workflows/:id/manual',
    element: <ProtectedRoute><MainLayout hideSidebar hideHeader fullBleed>{page(<WorkflowManualRunnerPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/runs/:runId',
    element: <ProtectedRoute><MainLayout hideSidebar hideHeader>{page(<WorkflowRunnerPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/workspace',
    element: (
      <ProtectedRoute>
        <MainLayout>
          {page(<WorkspacePage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/workspace/:id',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<WorkspacePage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/automations',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<AutomationsPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/automations/new',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<AutomationEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/automations/:id/edit',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<AutomationEditorPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/automations/:id',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<AutomationDetailPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/enterprise',
    element: <ProtectedRoute requiredRole="admin"><MainLayout>{page(<EnterprisePage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/profile',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<ProfilePage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/settings',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<SettingsPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/settings/accounts',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<AccountManagementPage />)}</MainLayout></ProtectedRoute>,
  },
  {
    path: '/auth/sso/callback',
    element: <AuthLayout>{page(<SsoCallbackPage />)}</AuthLayout>,
  },
  {
    path: '/auth/login',
    element: <AuthLayout><PublicRoute>{page(<LoginPage />)}</PublicRoute></AuthLayout>,
  },
  {
    path: '/auth/register',
    element: <AuthLayout><PublicRoute>{page(<RegisterPage />)}</PublicRoute></AuthLayout>,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

export default router;

import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, useLocation, useParams } from 'react-router-dom';
import { MainLayout, AuthLayout } from '@/layouts';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { ProtectedRoute, PublicRoute } from './guards';

const HomePage = lazy(() => import('@/pages/Home/HomePage'));
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
const DurableApplicationRuntimePage = lazy(() => import('@/pages/Apps/DurableApplicationRuntimePage'));
const ChatApplicationRuntimePage = lazy(() => import('@/pages/Apps/ChatApplicationRuntimePage'));
const WorkspacePage = lazy(() => import('@/pages/Workspace/WorkspacePage'));
const WorkflowsPage = lazy(() => import('@/pages/Workflows/WorkflowsPage'));
const WorkflowEditorPage = lazy(() => import('@/pages/Workflows/WorkflowEditorPage'));
const WorkflowRunnerPage = lazy(() => import('@/pages/Workflows/WorkflowRunnerPage'));
const WorkflowManualRunnerPage = lazy(() => import('@/pages/Workflows/WorkflowManualRunnerPage'));
const SkillsPage = lazy(() => import('@/pages/Skills/SkillsPage'));
const EnterprisePage = lazy(() => import('@/pages/Enterprise/EnterprisePage'));
const ContactsPage = lazy(() => import('@/pages/Contacts/ContactsPage'));
const CreationMasterPage = lazy(() => import('@/pages/Apps/CreationMasterPage'));
const WeMDPage = lazy(() => import('@/pages/Apps/WeMDPage'));
const ProfilePage = lazy(() => import('@/pages/Profile/ProfilePage'));
const SettingsPage = lazy(() => import('@/pages/Settings/SettingsPage'));
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
        <MainLayout>
          {page(<AgentsPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/agents/:id',
    element: (
      <ProtectedRoute>
        <MainLayout>
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
        <MainLayout>
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
        <MainLayout>
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
    path: '/applications/:applicationId/contacts',
    element: (
      <ProtectedRoute>
        <ApplicationShell>
          {page(<ContactsPage />)}
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
    path: '/applications/:applicationId/wemd',
    element: (
      <ProtectedRoute>
        <ApplicationShell fullBleed>
          {page(<WeMDPage />)}
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
    element: <ProtectedRoute><MainLayout>{page(<EnterprisePage />)}</MainLayout></ProtectedRoute>,
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

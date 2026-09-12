import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { MainLayout, AuthLayout } from '@/layouts';
import { ProtectedRoute, PublicRoute } from './guards';

const HomePage = lazy(() => import('@/pages/Home/HomePage'));
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
const WorkspacePage = lazy(() => import('@/pages/Workspace/WorkspacePage'));
const WorkflowsPage = lazy(() => import('@/pages/Workflows/WorkflowsPage'));
const WorkflowEditorPage = lazy(() => import('@/pages/Workflows/WorkflowEditorPage'));
const WorkflowRunnerPage = lazy(() => import('@/pages/Workflows/WorkflowRunnerPage'));
const SkillsPage = lazy(() => import('@/pages/Skills/SkillsPage'));
const EnterprisePage = lazy(() => import('@/pages/Enterprise/EnterprisePage'));

const page = (element: ReactNode) => (
  <Suspense fallback={<div style={{ padding: 32 }}>正在加载…</div>}>{element}</Suspense>
);

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
        <MainLayout>
          {page(<TemplatesPage />)}
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/templates/:id',
    element: (
      <ProtectedRoute>
        <MainLayout>
          {page(<TemplateDetailPage />)}
        </MainLayout>
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
    path: '/applications/:applicationId/run',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          {page(<DurableApplicationRuntimePage />)}
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
    path: '/workflows/:id/edit',
    element: <ProtectedRoute><MainLayout hideSidebar>{page(<WorkflowEditorPage />)}</MainLayout></ProtectedRoute>,
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
    path: '/enterprise',
    element: <ProtectedRoute><MainLayout>{page(<EnterprisePage />)}</MainLayout></ProtectedRoute>,
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

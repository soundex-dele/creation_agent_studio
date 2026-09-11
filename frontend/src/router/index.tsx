import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { MainLayout, AuthLayout } from '@/layouts';
import { ProtectedRoute, PublicRoute } from './guards';

// Pages
import HomePage from '@/pages/Home/HomePage';
import LoginPage from '@/pages/Auth/LoginPage';
import RegisterPage from '@/pages/Auth/RegisterPage';
import SsoCallbackPage from '@/pages/Auth/SsoCallbackPage';
import AgentsPage from '@/pages/Agents/AgentsPage';
import AgentDetailPage from '@/pages/Agents/AgentDetailPage';
import TemplatesPage from '@/pages/Templates/TemplatesPage';
import TemplateDetailPage from '@/pages/Templates/TemplateDetailPage';
import AppsPage from '@/pages/Apps/AppsPage';
import AppDetailPage from '@/pages/Apps/AppDetailPage';
import ChatApplicationEditPage from '@/pages/Apps/ChatApplicationEditPage';
import ApplicationRuntimePage from '@/pages/Apps/ApplicationRuntimePage';
import DurableApplicationRuntimePage from '@/pages/Apps/DurableApplicationRuntimePage';
import WorkspacePage from '@/pages/Workspace/WorkspacePage';
import WorkflowsPage from '@/pages/Workflows/WorkflowsPage';
import WorkflowEditorPage from '@/pages/Workflows/WorkflowEditorPage';
import WorkflowRunnerPage from '@/pages/Workflows/WorkflowRunnerPage';
import SkillsPage from '@/pages/Skills/SkillsPage';
const EnterprisePage = lazy(() => import('@/pages/Enterprise/EnterprisePage'));

const enterpriseElement = (
  <ProtectedRoute>
    <MainLayout>
      <Suspense fallback={<div style={{ padding: 32 }}>正在加载企业控制台…</div>}>
        <EnterprisePage />
      </Suspense>
    </MainLayout>
  </ProtectedRoute>
);

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <HomePage />
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
          <AgentsPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/agents/:id',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <AgentDetailPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/templates',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <TemplatesPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/templates/:id',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <TemplateDetailPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <AppsPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/:id',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <AppDetailPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/:id/run',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar hideHeader>
          <ApplicationRuntimePage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/applications/:applicationId/run',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          <DurableApplicationRuntimePage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/apps/:id/edit',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <ChatApplicationEditPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/skills',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          <SkillsPage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/workflows',
    element: <ProtectedRoute><MainLayout hideSidebar><WorkflowsPage /></MainLayout></ProtectedRoute>,
  },
  {
    path: '/workflows/:id/edit',
    element: <ProtectedRoute><MainLayout hideSidebar><WorkflowEditorPage /></MainLayout></ProtectedRoute>,
  },
  {
    path: '/workflow-runs/:runId',
    element: <ProtectedRoute><MainLayout hideSidebar hideHeader><WorkflowRunnerPage /></MainLayout></ProtectedRoute>,
  },
  {
    path: '/workspace',
    element: (
      <ProtectedRoute>
        <MainLayout>
          <WorkspacePage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/workspace/:id',
    element: (
      <ProtectedRoute>
        <MainLayout hideSidebar>
          <WorkspacePage />
        </MainLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: '/enterprise',
    element: enterpriseElement,
  },
  {
    path: '/auth/sso/callback',
    element: <AuthLayout><SsoCallbackPage /></AuthLayout>,
  },
  {
    path: '/auth/login',
    element: <AuthLayout><PublicRoute><LoginPage /></PublicRoute></AuthLayout>,
  },
  {
    path: '/auth/register',
    element: <AuthLayout><PublicRoute><RegisterPage /></PublicRoute></AuthLayout>,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

export default router;

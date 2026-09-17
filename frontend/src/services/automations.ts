import { api } from './api';
import { tenantApiRoot } from './tenantContext';
import type { Automation, AutomationInvocation, AutomationTarget, AutomationTargetType } from '@/types/automation';

const root = (organizationId: string) => `${tenantApiRoot(organizationId)}/automations`;

export const automationApi = {
  list: (organizationId: string, params?: Record<string, unknown>) =>
    api.get<Automation[]>(root(organizationId), params),
  get: (organizationId: string, id: number) =>
    api.get<Automation>(`${root(organizationId)}/${id}`),
  create: (organizationId: string, payload: Record<string, unknown>) =>
    api.post<Automation>(root(organizationId), payload),
  update: (organizationId: string, id: number, payload: Record<string, unknown>) =>
    api.patch<Automation>(`${root(organizationId)}/${id}`, payload),
  archive: (organizationId: string, id: number) =>
    api.delete(`${root(organizationId)}/${id}`),
  action: (organizationId: string, id: number, action: string, payload: Record<string, unknown> = {}) =>
    api.post<Automation | AutomationInvocation>(`${root(organizationId)}/${id}/${action}`, payload),
  invocations: (organizationId: string, id: number) =>
    api.get<AutomationInvocation[]>(`${root(organizationId)}/${id}/invocations`),
  targets: (organizationId: string, type: AutomationTargetType) =>
    api.get<AutomationTarget[]>(`${tenantApiRoot(organizationId)}/automation-targets`, { type }),
  preview: (organizationId: string, payload: Record<string, unknown>) =>
    api.post<{ next_runs: string[] }>(`${root(organizationId)}/schedule-preview`, payload),
};

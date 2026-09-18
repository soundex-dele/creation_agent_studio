import type { RunStreamHandle, RunStreamOptions } from './runStream';
import { streamRunEvents } from './runStream';
import { api } from './api';
import type { ApplicationDefinition } from '@/types/application';
import { tenantApiRoot } from './tenantContext';


export interface RunResource {
  id: string;
  organization_id: string;
  parent_id?: string | null;
  node_key?: string;
  status: string;
  version: number;
  next_event_sequence: number;
  definition_snapshot: Record<string, unknown>;
  input: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  source_type?: string;
  source_id?: string;
  executor_kind?: string;
  executor_key?: string;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  pending_input_request_id?: string | null;
  pending_input_kind?: string;
  error_code?: string;
  error_message?: string;
  can_delete?: boolean;
  task_type?: string;
  task_title?: string;
  trigger_type?: string;
  automation_id?: number | null;
  workflow_id?: string | null;
  application_id?: string | null;
  conversation_id?: string | null;
}

export interface RunArtifact {
  id: string;
  run_id: string;
  kind: string;
  content_hash: string;
  mime_type: string;
  size: number;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ApplicationRuntimeDescriptor {
  organization_id: string;
  application_id: string;
  name: string;
  slug: string;
  description: string;
  deployment_id: string;
  deployment_version: number;
  revision_id: string;
  revision_no: number;
  content_hash: string;
  schema_version: number;
  definition: ApplicationDefinition;
}

export interface CursorPage<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface RuntimeClientOptions {
  organizationId: string;
  applicationId: string;
}

export function createApplicationRuntimeClient({
  organizationId,
  applicationId,
}: RuntimeClientOptions) {
  const root = tenantApiRoot(organizationId);
  return {
    organizationId,
    applicationId,

    startRun: async (
      input: Record<string, unknown>,
      idempotencyKey: string,
    ): Promise<RunResource> => api.post<RunResource>(
      `${root}/applications/${applicationId}/runs`,
      { input },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    ) as Promise<RunResource>,

    subscribeRun: (
      runId: string,
      callbacks: Pick<RunStreamOptions, 'onEvent' | 'onSnapshot' | 'onError' | 'onConnectionChange'>,
    ): RunStreamHandle => streamRunEvents({
      organizationId,
      runId,
      ...callbacks,
    }),

    sendCommand: async (
      runId: string,
      command: {
        type: 'answer' | 'grant_permission' | 'deny_permission' | 'cancel';
        idempotency_key: string;
        input_request_id?: string | null;
        expected_run_version?: number | null;
        payload?: Record<string, unknown>;
      },
    ): Promise<Record<string, unknown>> => api.post<Record<string, unknown>>(
      `${root}/runs/${runId}/commands`,
      command,
    ) as Promise<Record<string, unknown>>,

    listArtifacts: async (runId: string): Promise<CursorPage<RunArtifact>> =>
      api.get<CursorPage<RunArtifact>>(`${root}/runs/${runId}/artifacts`),

    getArtifactAccess: async (
      runId: string,
      artifactId: string,
    ): Promise<{ artifact_id: string; url: string; expires_at: string }> =>
      api.get<{ artifact_id: string; url: string; expires_at: string }>(
        `${root}/runs/${runId}/artifacts/${artifactId}/access`,
      ),
  };
}

export async function loadApplicationRuntime(
  organizationId: string,
  applicationId: string,
): Promise<ApplicationRuntimeDescriptor> {
  return api.get<ApplicationRuntimeDescriptor>(
    `${tenantApiRoot(organizationId)}/applications/${applicationId}/runtime`,
  );
}

export type ApplicationRuntimeClient = ReturnType<typeof createApplicationRuntimeClient>;

import type { RunStreamHandle, RunStreamOptions } from './runStream';
import { streamRunEvents } from './runStream';
import { api } from './api';


export type DeploymentEnvironment = 'development' | 'staging' | 'production';

export interface RunResource {
  id: string;
  organization_id: string;
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
  environment: DeploymentEnvironment;
  deployment_id: string;
  deployment_version: number;
  revision_id: string;
  revision_no: number;
  content_hash: string;
  schema_version: number;
  definition: Record<string, unknown>;
}

export interface CursorPage<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface RuntimeClientOptions {
  organizationId: string;
  applicationId: string;
  environment?: DeploymentEnvironment;
}

export function createApplicationRuntimeClient({
  organizationId,
  applicationId,
  environment = 'production',
}: RuntimeClientOptions) {
  const root = `/organizations/${organizationId}`;
  return {
    organizationId,
    applicationId,
    environment,

    startRun: async (
      input: Record<string, unknown>,
      idempotencyKey: string,
    ): Promise<RunResource> => api.post<RunResource>(
      `${root}/applications/${applicationId}/runs`,
      { environment, input },
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
  environment: DeploymentEnvironment = 'production',
): Promise<ApplicationRuntimeDescriptor> {
  return api.get<ApplicationRuntimeDescriptor>(
    `/organizations/${organizationId}/applications/${applicationId}/runtime`,
    { environment },
  );
}

export type ApplicationRuntimeClient = ReturnType<typeof createApplicationRuntimeClient>;

import { api } from './api';
import type { CursorPage, RunArtifact } from './applicationRuntime';
import { tenantApiRoot } from './tenantContext';
import { API_BASE_URL } from './apiBaseUrl';

export interface RunArtifactAccess {
  artifact_id: string;
  url: string;
  content_path?: string | null;
  expires_at: string;
}

export function resolveArtifactAccessUrl(access: Pick<RunArtifactAccess, 'url' | 'content_path'>, baseUrl = API_BASE_URL): string {
  // Only platform-issued content paths are rebased. External storage signatures
  // and their origins must remain untouched, and receive no platform auth headers.
  if (!access.content_path?.startsWith('/api/v1/')) return access.url;
  return `${baseUrl.replace(/\/+$/, '')}${access.content_path.slice('/api/v1'.length)}`;
}

export async function listRunArtifacts(organizationId: string, runId: string, includeDescendants = false) {
  const artifacts: RunArtifact[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: CursorPage<RunArtifact> = await api.get(
      `${tenantApiRoot(organizationId)}/runs/${runId}/artifacts`,
      { include_descendants: includeDescendants, ...(cursor ? { cursor } : {}) },
    );
    artifacts.push(...page.results.filter((item) => item.kind !== 'checkpoint'));
    cursor = page.next ? new URL(page.next, 'http://localhost').searchParams.get('cursor') : null;
    if (cursor && seen.has(cursor)) throw new Error('文件列表分页异常，请刷新重试');
    if (cursor) seen.add(cursor);
  } while (cursor);
  return artifacts;
}

export async function getRunArtifactAccess(organizationId: string, artifact: Pick<RunArtifact, 'id' | 'run_id'>) {
  const access = await api.get<RunArtifactAccess>(
    `${tenantApiRoot(organizationId)}/runs/${artifact.run_id}/artifacts/${artifact.id}/access`,
  );
  return { ...access, url: resolveArtifactAccessUrl(access) };
}

export function canPreviewArtifact(artifact: RunArtifact) {
  return ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'].includes(artifact.mime_type);
}

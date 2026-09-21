import { api } from './api';
import type { CursorPage, RunArtifact } from './applicationRuntime';
import { tenantApiRoot } from './tenantContext';

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

export function getRunArtifactAccess(organizationId: string, artifact: Pick<RunArtifact, 'id' | 'run_id'>) {
  return api.get<{ url: string; expires_at: string }>(
    `${tenantApiRoot(organizationId)}/runs/${artifact.run_id}/artifacts/${artifact.id}/access`,
  );
}

export function canPreviewArtifact(artifact: RunArtifact) {
  return ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'].includes(artifact.mime_type);
}

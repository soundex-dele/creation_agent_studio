import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import type { RunArtifact } from '../applicationRuntime';
import { canPreviewArtifact, getRunArtifactAccess, listRunArtifacts } from '../runArtifacts';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../tenantContext', () => ({ tenantApiRoot: (id: string) => `/organizations/${id}` }));

const artifact = { id: 'image', run_id: 'child', kind: 'result', mime_type: 'image/png' } as RunArtifact;

describe('run artifacts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads all descendant pages while excluding internal checkpoints', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      results: [artifact, { ...artifact, id: 'checkpoint', kind: 'checkpoint' }],
      next: 'http://localhost:8080/api/v1/organizations/org/runs/root/artifacts?cursor=next-page',
    }).mockResolvedValueOnce({ results: [{ ...artifact, id: 'second' }], next: null });
    expect((await listRunArtifacts('org', 'root', true)).map((item) => item.id)).toEqual(['image', 'second']);
    expect(api.get).toHaveBeenLastCalledWith('/organizations/org/runs/root/artifacts', {
      include_descendants: true, cursor: 'next-page',
    });
  });

  it('uses the producing child run when obtaining a download URL', async () => {
    vi.mocked(api.get).mockResolvedValue({ url: '/signed-download', expires_at: '2026-09-21' });
    await getRunArtifactAccess('org', artifact);
    expect(api.get).toHaveBeenCalledWith('/organizations/org/runs/child/artifacts/image/access');
  });

  it('previews raster images but keeps HTML and SVG as downloads', () => {
    expect(canPreviewArtifact(artifact)).toBe(true);
    expect(canPreviewArtifact({ ...artifact, mime_type: 'text/html' })).toBe(false);
    expect(canPreviewArtifact({ ...artifact, mime_type: 'image/svg+xml' })).toBe(false);
  });
});

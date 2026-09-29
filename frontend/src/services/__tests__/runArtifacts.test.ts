import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import type { RunArtifact } from '../applicationRuntime';
import { canPreviewArtifact, getRunArtifactAccess, listRunArtifacts, resolveArtifactAccessUrl } from '../runArtifacts';
import { createApplicationRuntimeClient } from '../applicationRuntime';

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

  it('loads platform artifacts through the API proxy rather than the internal backend host', async () => {
    const content_path = '/api/v1/organizations/org/runs/run/artifacts/html/content?token=signed%2Bvalue';
    vi.mocked(api.get).mockResolvedValue({ artifact_id: 'html', url: `http://127.0.0.1:8080${content_path}`, content_path, expires_at: '2026-09-29' });
    const runtime = createApplicationRuntimeClient({ organizationId: 'org', applicationId: '33' });
    const access = await runtime.getArtifactAccess('run', 'html');
    expect(access.url).toBe(content_path);
    expect(api.get).toHaveBeenCalledWith('/organizations/org/runs/run/artifacts/html/access');
  });

  it('honors an explicitly configured HTTPS API host and preserves the signed query', () => {
    expect(resolveArtifactAccessUrl({ url: 'http://backend:8080/internal', content_path: '/api/v1/runs/run/artifacts/video/content?token=a%2Bb' }, 'https://api.example.test/proxy/api/v1/'))
      .toBe('https://api.example.test/proxy/api/v1/runs/run/artifacts/video/content?token=a%2Bb');
  });

  it('does not rewrite external storage signatures or legacy responses', () => {
    const url = 'https://storage.example.test/video.mp4?X-Amz-Signature=original';
    expect(resolveArtifactAccessUrl({ url, content_path: null })).toBe(url);
    expect(resolveArtifactAccessUrl({ url })).toBe(url);
  });
});

import { describe, expect, it } from 'vitest';
import {
  applicationPath,
  applicationRendererRegistry,
} from '../applicationCatalog';

describe('application renderer registry', () => {
  it('opens the catalog-provided case library with its registered renderer', () => {
    const app = {
      id: 'case-library', applicationId: 11, kind: 'custom' as const, rendererKey: 'case-library',
    };
    expect(applicationPath(app)).toBe('/apps/case-library?entry=apps');
    expect(applicationPath(app, 'home')).toBe('/apps/case-library?entry=home');
    expect(applicationRendererRegistry['case-library']).toBeTypeOf('function');
  });

  it('opens catalog applications directly in their runtime', () => {
    expect(applicationPath({
      id: 'writer', applicationId: 12, kind: 'chat', rendererKey: 'chat',
    })).toBe('/applications/12/chat?slug=writer&entry=apps');
    expect(applicationPath({
      id: 'contacts', applicationId: 13, kind: 'custom', rendererKey: 'contacts',
    })).toBe('/applications/13/contacts?entry=apps');
    expect(applicationPath({
      id: 'transcribe', applicationId: 14, kind: 'task', rendererKey: 'batch-transcribe',
    })).toBe('/applications/14/run?entry=apps');
  });
});

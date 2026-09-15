import { describe, expect, it } from 'vitest';
import {
  applicationPath,
  CASE_LIBRARY_APP,
  mergeBuiltInApplications,
  mergeBuiltInCategories,
} from '../applicationCatalog';

describe('application catalog built-ins', () => {
  it('adds the case library once and opens it under the applications route', () => {
    expect(mergeBuiltInApplications([])).toEqual([CASE_LIBRARY_APP]);
    expect(mergeBuiltInApplications([CASE_LIBRARY_APP])).toHaveLength(1);
    expect(applicationPath(CASE_LIBRARY_APP)).toBe('/apps/case-library?entry=apps');
    expect(applicationPath(CASE_LIBRARY_APP, 'home')).toBe('/apps/case-library?entry=home');
  });

  it('adds the built-in application to an existing category count', () => {
    const categories = mergeBuiltInCategories([
      { slug: 'knowledge', name: '知识', app_count: 2 },
    ]);
    expect(categories[0].app_count).toBe(3);
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

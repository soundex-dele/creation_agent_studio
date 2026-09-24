import { describe, expect, it } from 'vitest';
import {
  applicationPath,
  applicationRendererRegistry,
} from '../applicationCatalog';

describe('application renderer registry', () => {
  it('opens My Drive from either catalog entry', () => {
    const app = { id: 'my-drive', applicationId: 26, kind: 'custom' as const, rendererKey: 'my-drive' };
    expect(applicationPath(app)).toBe('/applications/26/my-drive?entry=apps');
    expect(applicationPath(app, 'home')).toBe('/applications/26/my-drive?entry=home');
  });
  it('opens Ideas & Todos with a dedicated renderer from either catalog entry', () => {
    const app = { id: 'ideas-todos', applicationId: 25, kind: 'custom' as const, rendererKey: 'ideas-todos' };
    expect(applicationPath(app)).toBe('/applications/25/ideas-todos?entry=apps');
    expect(applicationPath(app, 'home')).toBe('/applications/25/ideas-todos?entry=home');
  });
  it('opens Creation Master with its registered React renderer', () => {
    expect(applicationPath({
      id: 'creation-master', applicationId: 15, kind: 'custom', rendererKey: 'creation-master',
    })).toBe('/applications/15/creation-master?entry=apps');
  });

  it('opens Creation Toolbox with its registered React renderer', () => {
    expect(applicationPath({
      id: 'creation-toolbox', applicationId: 18, kind: 'custom', rendererKey: 'creation-toolbox',
    })).toBe('/applications/18/creation-toolbox?entry=apps');
  });

  it('opens Skill-backed generators as guided chat applications', () => {
    [
      'wechat-html-optimizer',
      'article-html-illustrator',
      'html-cover-generator',
      'wechat-viral-article',
      'gzh-design',
    ]
      .forEach((id, index) => {
        const applicationId = 17 + index;
        expect(applicationPath({
          id, applicationId, kind: 'chat', rendererKey: 'chat',
        })).toBe(`/applications/${applicationId}/chat?slug=${id}&entry=apps`);
      });
  });

  it('opens the catalog-provided case library with its registered renderer', () => {
    const app = {
      id: 'case-library', applicationId: 11, kind: 'custom' as const, rendererKey: 'case-library',
    };
    expect(applicationPath(app)).toBe('/apps/case-library?entry=apps');
    expect(applicationPath(app, 'home')).toBe('/apps/case-library?entry=home');
    expect(applicationRendererRegistry['case-library']).toBeTypeOf('function');
  });

  it('opens 学之有道 in its dedicated learning runtime', () => {
    const app = {
      id: 'study-with-method', applicationId: 21, kind: 'custom' as const,
      rendererKey: 'study-with-method',
    };
    expect(applicationPath(app)).toBe('/applications/21/study-with-method?entry=apps');
    expect(applicationRendererRegistry['study-with-method']).toBeTypeOf('function');
  });

  it('opens catalog applications directly in their runtime', () => {
    expect(applicationPath({
      id: 'writer', applicationId: 12, kind: 'chat', rendererKey: 'chat',
    })).toBe('/applications/12/chat?slug=writer&entry=apps');
    expect(applicationPath({
      id: 'transcribe', applicationId: 14, kind: 'task', rendererKey: 'batch-transcribe',
    })).toBe('/applications/14/run?entry=apps');
  });
});

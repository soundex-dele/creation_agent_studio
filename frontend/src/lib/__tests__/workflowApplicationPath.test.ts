import { describe, expect, it } from 'vitest';

import type { WorkflowStep } from '@/types';
import { workflowApplicationPath } from '../workflowApplicationPath';


function step(rendererKey: string, kind: 'chat' | 'custom' = 'custom'): WorkflowStep {
  return {
    id: 'step-1',
    key: 'draft',
    order: 1,
    config: {},
    depends_on: [],
    condition: {},
    max_attempts: 1,
    application_id: 6,
    application: {
      id: 6,
      kind,
      renderer_key: rendererKey,
      application_slug: rendererKey,
      application_name: '测试应用',
    } as WorkflowStep['application'],
  };
}

describe('workflow application path', () => {
  it('opens Creation Master with its dedicated renderer inside the workflow', () => {
    expect(workflowApplicationPath(step('creation-master'))).toBe(
      '/applications/6/creation-master?embedded=1',
    );
  });

  it('does not mark Creation Master as embedded when opened in a new window', () => {
    expect(workflowApplicationPath(step('creation-master'), false)).toBe(
      '/applications/6/creation-master',
    );
  });

  it('opens Creation Toolbox with its dedicated renderer inside the workflow', () => {
    expect(workflowApplicationPath(step('creation-toolbox'))).toBe(
      '/applications/6/creation-toolbox?embedded=1',
    );
  });

  it('opens 学之有道 with its dedicated renderer', () => {
    expect(workflowApplicationPath(step('study-with-method'))).toBe(
      '/applications/6/study-with-method?embedded=1',
    );
  });

  it('opens Skill-backed generators as chat applications', () => {
    expect(workflowApplicationPath(step('wechat-html-optimizer', 'chat'))).toBe(
      '/applications/6/chat?slug=wechat-html-optimizer&embedded=1',
    );
    expect(workflowApplicationPath(step('article-html-illustrator', 'chat'), false)).toBe(
      '/applications/6/chat?slug=article-html-illustrator',
    );
    expect(workflowApplicationPath(step('html-cover-generator', 'chat'))).toBe(
      '/applications/6/chat?slug=html-cover-generator&embedded=1',
    );
  });
});

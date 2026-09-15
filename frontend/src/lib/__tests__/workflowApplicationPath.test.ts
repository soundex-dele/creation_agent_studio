import { describe, expect, it } from 'vitest';

import type { WorkflowStep } from '@/types';
import { workflowApplicationPath } from '../workflowApplicationPath';


function step(rendererKey: string): WorkflowStep {
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
      kind: 'custom',
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
});

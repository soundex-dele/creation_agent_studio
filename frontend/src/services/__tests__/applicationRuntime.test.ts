import { describe, expect, it } from 'vitest';

import { createApplicationRuntimeClient } from '../applicationRuntime';


describe('createApplicationRuntimeClient', () => {
  it('does not expose a deployment environment selector', () => {
    const client = createApplicationRuntimeClient({
      organizationId: 'organization-id',
      applicationId: 'application-id',
    });

    expect(client).not.toHaveProperty('environment');
  });
});

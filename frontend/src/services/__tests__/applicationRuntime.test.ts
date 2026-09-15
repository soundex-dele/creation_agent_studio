import { describe, expect, it } from 'vitest';

import { resolveDefaultDeploymentEnvironment } from '../applicationRuntime';


describe('resolveDefaultDeploymentEnvironment', () => {
  it('uses development for the Vite development server', () => {
    expect(resolveDefaultDeploymentEnvironment(undefined, true)).toBe('development');
  });

  it('uses production for an ordinary production build', () => {
    expect(resolveDefaultDeploymentEnvironment(undefined, false)).toBe('production');
  });

  it('allows packaged builds to select an environment explicitly', () => {
    expect(resolveDefaultDeploymentEnvironment('development', false)).toBe('development');
    expect(resolveDefaultDeploymentEnvironment('staging', false)).toBe('staging');
  });

  it('ignores unsupported configured values', () => {
    expect(resolveDefaultDeploymentEnvironment('invalid', true)).toBe('development');
    expect(resolveDefaultDeploymentEnvironment('invalid', false)).toBe('production');
  });
});

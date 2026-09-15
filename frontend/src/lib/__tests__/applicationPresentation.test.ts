import { describe, expect, it } from 'vitest';

import { resolveApplicationPresentation } from '../applicationPresentation';

describe('application presentation', () => {
  it('lets the platform own navigation for home launches', () => {
    expect(resolveApplicationPresentation(new URLSearchParams('entry=home'))).toEqual({
      entry: 'home',
      embedded: false,
      showPlatformChrome: true,
      showApplicationHeader: false,
    });
  });

  it('lets the application own navigation for catalog launches', () => {
    expect(resolveApplicationPresentation(new URLSearchParams('entry=apps'))).toEqual({
      entry: 'apps',
      embedded: false,
      showPlatformChrome: false,
      showApplicationHeader: true,
    });
  });

  it('leaves navigation to the workflow shell for embedded launches', () => {
    expect(resolveApplicationPresentation(new URLSearchParams('embedded=1'))).toEqual({
      entry: 'apps',
      embedded: true,
      showPlatformChrome: false,
      showApplicationHeader: false,
    });
  });
});

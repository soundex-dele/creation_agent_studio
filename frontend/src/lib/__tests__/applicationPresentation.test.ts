import { describe, expect, it } from 'vitest';

import {
  applicationNavigationPath,
  applicationWindowPath,
  resolveApplicationPresentation,
} from '../applicationPresentation';
import { applicationPath, applicationRendererRegistry } from '../applicationCatalog';

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

  it.each(['', 'entry=home', 'entry=apps', 'embedded=1'])(
    'hides both navigation shells in standalone windows (%s)', (query) => {
      const presentation = resolveApplicationPresentation(new URLSearchParams(`${query}&standalone=1`));
      expect(presentation.showPlatformChrome).toBe(false);
      expect(presentation.showApplicationHeader).toBe(false);
    },
  );

  it.each(Object.keys(applicationRendererRegistry))(
    'opens the %s renderer without platform or application navigation', (rendererKey) => {
      const path = applicationPath({ id: 'example', applicationId: 12, rendererKey, kind: 'custom' });
      const target = new URL(applicationWindowPath(path), 'https://studio.test');
      expect(target.pathname).toBe(path.split('?')[0]);
      expect(target.searchParams.get('entry')).toBe('apps');
      expect(target.searchParams.get('standalone')).toBe('1');
      expect(resolveApplicationPresentation(target.searchParams)).toMatchObject({
        showPlatformChrome: false,
        showApplicationHeader: false,
      });
    },
  );

  it('preserves destination query parameters and fragments in new windows', () => {
    expect(applicationWindowPath('/chat?conversation=42&entry=home#message'))
      .toBe('/chat?conversation=42&entry=apps&standalone=1#message');
  });

  it('keeps launch presentation across internal navigation without copying page state', () => {
    const current = new URLSearchParams('entry=apps&standalone=1&conversation=old&slug=writer');
    const path = applicationNavigationPath('/chat?conversation=new', current);
    expect(path).toBe('/chat?conversation=new&entry=apps&standalone=1');
    expect(applicationNavigationPath('/apps/my-computer', new URLSearchParams()))
      .toBe('/apps/my-computer');
  });
});

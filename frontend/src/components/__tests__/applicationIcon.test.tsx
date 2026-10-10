import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ApplicationIcon from '../ApplicationIcon';

describe('repository application icon', () => {
  it.each([
    { id: 'repo-explainer', icon: 'code' },
    { id: '39', rendererKey: 'repo-explainer', icon: 'code' },
  ])('renders an SVG instead of the manifest icon name', app => {
    const html = renderToStaticMarkup(<ApplicationIcon app={app} />);
    expect(html).toContain('<svg');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('width="1em"');
    expect(html).not.toContain('>code<');
  });
});

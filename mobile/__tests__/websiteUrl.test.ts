import { normalizeWebsiteUrl } from '../src/websiteUrl';
import { classifyBrowserNavigation } from '../src/navigationPolicy';

const scriptUrl = ['java', 'script:1'].join('');

describe('user-selected websites', () => {
  it.each([
    [
      ' https://server.example.com/apps/123?mode=mobile#latest ',
      'https://server.example.com/apps/123?mode=mobile#latest',
    ],
    ['example.com/path', 'https://example.com/path'],
    ['//example.com', 'https://example.com/'],
    ['example.com:8443/path', 'https://example.com:8443/path'],
    ['http://192.168.1.20:3030/app', 'http://192.168.1.20:3030/app'],
    ['http://localhost:3030', 'http://localhost:3030/'],
    ['[::1]:8443', 'https://[::1]:8443/'],
  ])('normalizes %s without losing the destination', (input, expected) => {
    expect(normalizeWebsiteUrl(input)).toBe(expected);
  });

  it.each([
    '',
    '   ',
    'not a website',
    scriptUrl,
    'data:text/html,test',
    'file:///tmp/test',
    'intent://test',
    'ftp://example.com',
    'https://',
    'https://user:password@example.com',
  ])('rejects %s', input => {
    expect(normalizeWebsiteUrl(input)).toBeNull();
  });

  it('keeps cross-domain redirects inside the app', () => {
    expect(
      classifyBrowserNavigation('https://login.example.com/authorize'),
    ).toBe('internal');
    expect(classifyBrowserNavigation('http://192.168.1.20:3030')).toBe(
      'internal',
    );
    expect(classifyBrowserNavigation('mailto:help@example.com')).toBe(
      'external',
    );
    expect(classifyBrowserNavigation(scriptUrl)).toBe('blocked');
    expect(classifyBrowserNavigation('file:///tmp/test')).toBe('blocked');
  });
});

import {
  classifyNavigation,
  isSafeExternalUrl,
  resolveDeepLink,
} from '../src/navigationPolicy';

const APP_ORIGIN = 'https://studio.example.com';

describe('navigation policy', () => {
  it('keeps same-origin pages inside the webview', () => {
    expect(classifyNavigation(`${APP_ORIGIN}/apps/123`, APP_ORIGIN)).toBe('internal');
  });

  it('allows explicitly trusted authentication origins inside the webview', () => {
    expect(classifyNavigation(
      'https://login.example.com/oauth',
      APP_ORIGIN,
      ['https://login.example.com'],
    )).toBe('internal');
  });

  it('sends ordinary web links to the system browser', () => {
    expect(classifyNavigation('https://openai.com', APP_ORIGIN)).toBe('external');
    expect(classifyNavigation(
      'https://studio.example.com.evil.example/apps',
      APP_ORIGIN,
    )).toBe('external');
  });

  it('blocks script and local-file navigation', () => {
    expect(classifyNavigation(['java', 'script:alert(1)'].join(''), APP_ORIGIN)).toBe('blocked');
    expect(classifyNavigation('file:///etc/passwd', APP_ORIGIN)).toBe('blocked');
  });

  it('maps custom deep links to same-origin web routes', () => {
    expect(resolveDeepLink(
      'agentstudio://open?path=%2Fapps%2F123%3Fentry%3Dmobile',
      APP_ORIGIN,
    )).toBe('https://studio.example.com/apps/123?entry=mobile');
  });

  it('rejects unsafe custom deep-link paths', () => {
    expect(resolveDeepLink('agentstudio://open?path=https://evil.example', APP_ORIGIN)).toBeNull();
    expect(resolveDeepLink('agentstudio://open?path=//evil.example', APP_ORIGIN)).toBeNull();
  });

  it('only exposes safe protocols to native Linking', () => {
    expect(isSafeExternalUrl('mailto:support@example.com')).toBe(true);
    expect(isSafeExternalUrl('tel:+8610000')).toBe(true);
    expect(isSafeExternalUrl('data:text/html,bad')).toBe(false);
  });
});

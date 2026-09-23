import React from 'react';
import { Linking } from 'react-native';
import TestRenderer, { act } from 'react-test-renderer';
import { WebView } from 'react-native-webview';

import { WebAppScreen } from '../src/WebAppScreen';

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: { fetch: jest.fn(async () => ({ isConnected: true })) },
  useNetInfo: () => ({ isConnected: true }),
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: require('react-native').View,
}));
jest.mock('react-native-webview', () => {
  const ReactModule = require('react');
  return { WebView: ReactModule.forwardRef(() => null) };
});

const origin = 'https://server.example.com';
const navigation = (path: string, loading: boolean, canGoBack = false) => ({
  url: `${origin}${path}`,
  loading,
  canGoBack,
  canGoForward: false,
  title: 'Website',
  target: 1,
  lockIdentifier: 0,
});

describe('WebView loading state', () => {
  let renderer: TestRenderer.ReactTestRenderer;
  const webView = () => renderer.root.findByType(WebView);
  const loadingOverlays = () =>
    renderer.root.findAllByProps({ accessibilityLabel: '页面加载中' });

  beforeEach(async () => {
    jest.spyOn(Linking, 'getInitialURL').mockResolvedValue(null);
    await act(async () => {
      renderer = TestRenderer.create(
        <WebAppScreen startUrl={origin} onClose={jest.fn()} />,
      );
    });
  });

  afterEach(async () => {
    await act(async () => {
      renderer.unmount();
    });
    jest.restoreAllMocks();
  });

  it('does not cover SPA navigation or back with an endless loading overlay', async () => {
    await act(async () => {
      webView().props.onLoadEnd();
    });
    expect(loadingOverlays()).toHaveLength(0);

    // Android doUpdateVisitedHistory emits load-start for History API changes,
    // even though the document is already loaded and no load-end will follow.
    for (const path of ['/apps', '/apps/123', '/']) {
      const event = navigation(path, false, path !== '/');
      await act(async () => {
        webView().props.onLoadStart({ nativeEvent: event });
        webView().props.onNavigationStateChange(event);
      });
      expect(loadingOverlays()).toHaveLength(0);
      expect(
        renderer.root.findAllByProps({
          accessibilityLabel: `当前网址：${origin}${path}`,
        }),
      ).not.toHaveLength(0);
    }
  });

  it('shows loading for a real document navigation and clears at completed progress', async () => {
    await act(async () => {
      webView().props.onLoadEnd();
    });
    await act(async () => {
      webView().props.onLoadStart({
        nativeEvent: navigation('/another-page', true),
      });
    });
    expect(loadingOverlays().length).toBeGreaterThan(0);
    await act(async () => {
      webView().props.onLoadProgress({ nativeEvent: { progress: 1 } });
    });
    expect(loadingOverlays()).toHaveLength(0);
  });

  it('clears the overlay when navigation state says the document has finished', async () => {
    await act(async () => {
      webView().props.onNavigationStateChange(navigation('/apps', false));
    });
    expect(loadingOverlays()).toHaveLength(0);
  });
});

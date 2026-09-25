import React from 'react';
import {
  AppState,
  Alert,
  BackHandler,
  Linking,
  Modal,
  Platform,
  type AppStateStatus,
} from 'react-native';
import { useNetInfo } from '@react-native-community/netinfo';
import TestRenderer, { act } from 'react-test-renderer';
import { WebView } from 'react-native-webview';

import { WebAppScreen } from '../src/WebAppScreen';
import { SettingsScreen } from '../src/SettingsScreen';
import { ConnectionProblem } from '../src/ConnectionProblem';
import {
  loadCredentials,
  saveCredentials,
  clearCredentials,
} from '../src/credentialStorage';

jest.mock('../src/credentialStorage', () => ({
  createCredentialToken: () => 'a'.repeat(64),
  loadCredentials: jest.fn(),
  saveCredentials: jest.fn(),
  clearCredentials: jest.fn(),
}));

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: { fetch: jest.fn(async () => ({ isConnected: true })) },
  useNetInfo: jest.fn(() => ({ isConnected: true })),
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: require('react-native').View,
}));
jest.mock('react-native-webview', () => {
  const ReactModule = require('react');
  return {
    WebView: ReactModule.forwardRef((_props: unknown, ref: unknown) => {
      const handle = ReactModule.useMemo(
        () => ({
          reload: jest.fn(),
          goBack: jest.fn(),
          injectJavaScript: jest.fn(),
        }),
        [],
      );
      ReactModule.useImperativeHandle(ref, () => handle);
      return null;
    }),
  };
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
  const onClose = jest.fn();
  const press = (label: string) =>
    renderer.root
      .findAll(node => typeof node.props.onPress === 'function')
      .find(button => button.props.accessibilityLabel === label)!
      .props.onPress();
  const webView = () => renderer.root.findByType(WebView);
  const loadingOverlays = () =>
    renderer.root.findAllByProps({ accessibilityLabel: '页面加载中' });

  beforeEach(async () => {
    jest.clearAllMocks();
    jest
      .mocked(useNetInfo)
      .mockReturnValue({ isConnected: true } as ReturnType<typeof useNetInfo>);
    onClose.mockClear();
    jest.spyOn(Linking, 'getInitialURL').mockResolvedValue(null);
    await act(async () => {
      renderer = TestRenderer.create(
        <WebAppScreen startUrl={origin} onClose={onClose} />,
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
      ).toHaveLength(0);
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

  it('opens settings from its icon and returns without remounting the web page', async () => {
    const page = webView();
    await act(async () => press('设置'));
    expect(renderer.root.findAllByType(SettingsScreen)).toHaveLength(1);
    expect(webView()).toBe(page);
    await act(async () =>
      renderer.root.findByType(SettingsScreen).props.onBack(),
    );
    expect(renderer.root.findAllByType(SettingsScreen)).toHaveLength(0);
    expect(webView()).toBe(page);
  });

  it('keeps iOS downloads inside the app and dismisses the page loading overlay', async () => {
    const originalOS = Platform.OS;
    Platform.OS = 'ios';
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue();
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    try {
      await act(async () => {
        webView().props.onLoadStart({
          nativeEvent: navigation('/report', true),
        });
        webView().props.onFileDownload({
          nativeEvent: { downloadUrl: `${origin}/report` },
        });
      });
      expect(open).not.toHaveBeenCalled();
      expect(alert).toHaveBeenCalledWith(
        '已开始下载',
        expect.stringContaining('设置'),
      );
      expect(loadingOverlays()).toHaveLength(0);
    } finally {
      Platform.OS = originalOS;
    }
  });

  it('opens, switches and closes independent windows without remounting existing pages', async () => {
    const first = webView();
    expect(first.props.setSupportMultipleWindows).toBe(true);
    await act(async () => {
      first.props.onOpenWindow({
        nativeEvent: { targetUrl: `${origin}/apps/1` },
      });
    });
    expect(renderer.root.findAllByType(WebView)).toHaveLength(2);
    const second = renderer.root.findAllByType(WebView)[1];
    expect(second.props.source.uri).toBe(`${origin}/apps/1`);
    expect(
      renderer.root.findByProps({ testID: 'window-1' }).props.pointerEvents,
    ).toBe('auto');
    await act(async () => {
      second.props.onNavigationStateChange({
        ...navigation('/apps/1', false),
        title: '应用 A',
      });
      press('切换窗口 (2)');
    });
    expect(renderer.root.findByType(Modal).props.visible).toBe(true);
    await act(async () => press('切换到首页'));
    expect(renderer.root.findByType(Modal).props.visible).toBe(false);
    expect(renderer.root.findAllByType(WebView)[0]).toBe(first);
    expect(
      renderer.root.findByProps({ testID: 'window-0' }).props.pointerEvents,
    ).toBe('auto');
    await act(async () => press('切换窗口 (2)'));
    await act(async () => press('关闭应用 A'));
    expect(renderer.root.findAllByType(WebView)).toHaveLength(1);
    expect(renderer.root.findAllByType(WebView)[0]).toBe(first);
    await act(async () => press('关闭首页'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('refreshes only the active window and keeps background errors isolated', async () => {
    const first = webView();
    const firstHandle = first.props.ref.current;
    await act(async () =>
      first.props.onOpenWindow({
        nativeEvent: { targetUrl: `${origin}/apps/2` },
      }),
    );
    const second = renderer.root.findAllByType(WebView)[1];
    const secondHandle = second.props.ref.current;
    await act(async () => {
      first.props.onError({
        nativeEvent: { description: 'Background failure' },
      });
      second.props.onLoadEnd();
      press('刷新');
    });
    expect(secondHandle.reload).toHaveBeenCalledTimes(1);
    expect(firstHandle.reload).not.toHaveBeenCalled();
    expect(
      renderer.root
        .findByProps({ testID: 'window-1' })
        .findAllByProps({ accessibilityLabel: '页面加载中' }),
    ).toHaveLength(0);
    await act(async () => press('更换网址'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not create windows for blocked schemes and sends telephone links to the system', async () => {
    const external = jest
      .spyOn(Linking, 'openURL')
      .mockResolvedValue(undefined);
    await act(async () => {
      webView().props.onOpenWindow({
        nativeEvent: { targetUrl: ['java', 'script:alert(1)'].join('') },
      });
      webView().props.onOpenWindow({ nativeEvent: { targetUrl: 'tel:12345' } });
    });
    expect(renderer.root.findAllByType(WebView)).toHaveLength(1);
    expect(external).toHaveBeenCalledWith('tel:12345');
  });

  it('requests the full server home in only the active window, including after an error and repeated presses', async () => {
    const serverUrl = `${origin}/studio?tenant=example#home`;
    await act(async () => renderer.unmount());
    await act(async () => {
      renderer = TestRenderer.create(
        <WebAppScreen startUrl={serverUrl} onClose={onClose} />,
      );
    });
    const first = webView();
    await act(async () =>
      first.props.onOpenWindow({
        nativeEvent: { targetUrl: `${origin}/apps/2` },
      }),
    );
    const second = renderer.root.findAllByType(WebView)[1];
    await act(async () => {
      second.props.onNavigationStateChange(navigation('/apps/2', false, true));
      second.props.onError({
        nativeEvent: { description: 'Connection failed' },
      });
    });
    await act(async () => press('主页'));
    const home = renderer.root.findAllByType(WebView)[1];
    expect(home).not.toBe(second);
    expect(home.props.source.uri).toBe(serverUrl);
    expect(renderer.root.findAllByType(WebView)[0]).toBe(first);
    expect(
      renderer.root.findByProps({ testID: 'window-1' }).props.pointerEvents,
    ).toBe('auto');
    await act(async () => press('主页'));
    expect(renderer.root.findAllByType(WebView)[1]).not.toBe(home);
    expect(renderer.root.findAllByType(WebView)[1].props.source.uri).toBe(
      serverUrl,
    );
    expect(renderer.root.findAllByType(WebView)).toHaveLength(2);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('uses Android back for active page history, then closes the active window', async () => {
    const originalOS = Platform.OS;
    Platform.OS = 'android';
    const back = jest.spyOn(BackHandler, 'addEventListener');
    try {
      await act(async () =>
        webView().props.onOpenWindow({
          nativeEvent: { targetUrl: `${origin}/apps/3` },
        }),
      );
      const second = renderer.root.findAllByType(WebView)[1];
      const handle = second.props.ref.current;
      await act(async () =>
        second.props.onNavigationStateChange(
          navigation('/apps/3', false, true),
        ),
      );
      await act(async () => {
        (back.mock.calls[back.mock.calls.length - 1][1] as () => boolean)();
      });
      expect(handle.goBack).toHaveBeenCalledTimes(1);
      expect(renderer.root.findAllByType(WebView)).toHaveLength(2);
      await act(async () =>
        second.props.onNavigationStateChange(
          navigation('/apps/3', false, false),
        ),
      );
      await act(async () => {
        (back.mock.calls[back.mock.calls.length - 1][1] as () => boolean)();
      });
      expect(renderer.root.findAllByType(WebView)).toHaveLength(1);
      expect(
        renderer.root.findByProps({ testID: 'window-0' }).props.pointerEvents,
      ).toBe('auto');
      expect(onClose).not.toHaveBeenCalled();
    } finally {
      Platform.OS = originalOS;
    }
  });

  it('recreates the failed destination on manual retry instead of reloading an error document', async () => {
    const page = webView();
    const failedUrl = `${origin}/apps/2?mode=mobile`;
    const preventDefault = jest.fn();
    await act(async () =>
      page.props.onError({
        preventDefault,
        nativeEvent: {
          url: failedUrl,
          code: -6,
          description: 'Connection refused',
        },
      }),
    );
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(renderer.root.findByType(ConnectionProblem).props.url).toBe(
      failedUrl,
    );
    await act(async () =>
      page.props.onLoadStart({
        nativeEvent: { ...navigation('/', false), url: 'about:blank' },
      }),
    );
    // A native error page is not a new HTTP navigation.
    expect(renderer.root.findByType(ConnectionProblem).props.url).toBe(
      failedUrl,
    );
    await act(async () => press('重新加载页面'));
    expect(webView()).not.toBe(page);
    expect(webView().props.source.uri).toBe(failedUrl);
    expect(renderer.root.findAllByType(ConnectionProblem)).toHaveLength(0);
  });

  it('recovers when the network returns without remounting a healthy page', async () => {
    const originalOS = Platform.OS;
    Platform.OS = 'android';
    try {
      const page = webView();
      await act(async () =>
        page.props.onError({
          nativeEvent: {
            url: origin,
            code: -6,
            description: 'Connection refused',
          },
        }),
      );
      jest
        .mocked(useNetInfo)
        .mockReturnValue({ isConnected: false } as ReturnType<
          typeof useNetInfo
        >);
      await act(async () =>
        renderer.update(<WebAppScreen startUrl={origin} onClose={onClose} />),
      );
      expect(webView()).toBe(page);
      jest
        .mocked(useNetInfo)
        .mockReturnValue({ isConnected: true } as ReturnType<
          typeof useNetInfo
        >);
      await act(async () =>
        renderer.update(<WebAppScreen startUrl={origin} onClose={onClose} />),
      );
      expect(webView()).not.toBe(page);
      const healthy = webView();
      jest
        .mocked(useNetInfo)
        .mockReturnValue({ isConnected: false } as ReturnType<
          typeof useNetInfo
        >);
      await act(async () =>
        renderer.update(<WebAppScreen startUrl={origin} onClose={onClose} />),
      );
      jest
        .mocked(useNetInfo)
        .mockReturnValue({ isConnected: true } as ReturnType<
          typeof useNetInfo
        >);
      await act(async () =>
        renderer.update(<WebAppScreen startUrl={origin} onClose={onClose} />),
      );
      expect(webView()).toBe(healthy);
    } finally {
      Platform.OS = originalOS;
    }
  });

  it('retries failures that arrive after foregrounding at most twice and leaves healthy pages intact', async () => {
    jest.useFakeTimers();
    const originalOS = Platform.OS;
    const originalState = AppState.currentState;
    Platform.OS = 'android';
    AppState.currentState = 'background';
    let appStateChanged!: (state: AppStateStatus) => void;
    jest
      .spyOn(AppState, 'addEventListener')
      .mockImplementation((_event, handler) => {
        appStateChanged = handler;
        return { remove: jest.fn() };
      });
    try {
      await act(async () => renderer.unmount());
      await act(async () => {
        renderer = TestRenderer.create(
          <WebAppScreen startUrl={origin} onClose={onClose} />,
        );
      });
      const page = webView();
      await act(async () => appStateChanged('active'));
      expect(webView()).toBe(page);
      const fail = async () =>
        act(async () =>
          webView().props.onError({
            nativeEvent: {
              url: origin,
              code: -6,
              description: 'Connection refused',
            },
          }),
        );
      await fail();
      await act(async () => jest.advanceTimersByTime(1500));
      expect(webView()).not.toBe(page);
      const second = webView();
      await fail();
      await act(async () => jest.advanceTimersByTime(3000));
      expect(webView()).not.toBe(second);
      const third = webView();
      await fail();
      await act(async () => jest.advanceTimersByTime(6000));
      expect(webView()).toBe(third);
      expect(renderer.root.findAllByType(ConnectionProblem)).toHaveLength(1);
    } finally {
      Platform.OS = originalOS;
      AppState.currentState = originalState;
      jest.useRealTimers();
    }
  });

  it('requires the selected origin and private bridge token to access passwords', async () => {
    const credentialMessage = {
      type: 'credentials',
      action: 'load',
      token: 'a'.repeat(64),
      requestId: 'test-1',
    };
    jest
      .mocked(loadCredentials)
      .mockResolvedValue({ username: 'alice', password: 'test-secret' });
    for (const [url, token] of [
      ['https://other.example.com/auth/login', credentialMessage.token],
      [`${origin}/auth/login`, 'b'.repeat(64)],
      [`${origin}/apps/1`, credentialMessage.token],
    ]) {
      await act(async () =>
        webView().props.onMessage({
          nativeEvent: {
            url,
            data: JSON.stringify({ ...credentialMessage, token }),
          },
        }),
      );
    }
    expect(loadCredentials).not.toHaveBeenCalled();
    await act(async () =>
      webView().props.onMessage({
        nativeEvent: {
          url: `${origin}/auth/login`,
          data: JSON.stringify(credentialMessage),
        },
      }),
    );
    expect(loadCredentials).toHaveBeenCalledWith(origin);
    const script =
      webView().props.ref.current.injectJavaScript.mock.calls[0][0];
    expect(script).toContain(`window.location.origin === "${origin}"`);
    expect(script).toContain('completeCredentialRequest');
    for (const action of ['save', 'clear']) {
      await act(async () =>
        webView().props.onMessage({
          nativeEvent: {
            url: `${origin}/auth/login`,
            data: JSON.stringify({
              ...credentialMessage,
              action,
              username: 'alice',
              password: 'test-secret',
            }),
          },
        }),
      );
    }
    expect(saveCredentials).toHaveBeenCalledWith(
      origin,
      expect.objectContaining({ username: 'alice', password: 'test-secret' }),
    );
    expect(clearCredentials).toHaveBeenCalledWith(origin);
  });
});

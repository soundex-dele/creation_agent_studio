import NetInfo, { useNetInfo } from '@react-native-community/netinfo';
import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  Linking,
  Platform,
  Share,
  StyleSheet,
  useColorScheme,
  View,
} from 'react-native';
import { WebView as NativeWebView } from 'react-native-webview';
import type {
  AndroidWebViewProps,
  FileDownloadEvent,
  IOSWebViewProps,
  ShouldStartLoadRequest,
  WebViewSharedProps,
  WebViewErrorEvent,
  WebViewHttpErrorEvent,
  WebViewMessageEvent,
  WebViewNavigation,
  WebViewOpenWindowEvent,
} from 'react-native-webview/lib/WebViewTypes';

import { APP_CONFIG } from './appConfig';
import { ConnectionProblem } from './ConnectionProblem';
import {
  nativeBridgeBootstrap,
  parseNativeBridgeMessage,
} from './nativeBridge';
import {
  classifyNavigation,
  classifyBrowserNavigation,
  isSafeExternalUrl,
} from './navigationPolicy';
import { COLORS } from './theme';
import {
  describeWebViewError,
  isRecoverableWebViewError,
} from './webViewErrors';
import {
  createCredentialToken,
  loadCredentials,
  saveCredentials,
  clearCredentials,
} from './credentialStorage';

interface LoadProblem {
  detail: string;
  url: string;
  recoverable: boolean;
}

interface WebViewHandle {
  goBack: () => void;
  injectJavaScript: (script: string) => void;
  reload: () => void;
}

type MobileWebViewProps = WebViewSharedProps &
  Pick<
    AndroidWebViewProps,
    | 'allowFileAccess'
    | 'allowUniversalAccessFromFileURLs'
    | 'domStorageEnabled'
    | 'mixedContentMode'
    | 'onOpenWindow'
    | 'onRenderProcessGone'
    | 'setSupportMultipleWindows'
    | 'thirdPartyCookiesEnabled'
  > &
  Pick<
    IOSWebViewProps,
    | 'allowsBackForwardNavigationGestures'
    | 'contentInsetAdjustmentBehavior'
    | 'mediaCapturePermissionGrantType'
    | 'onContentProcessDidTerminate'
    | 'onFileDownload'
    | 'sharedCookiesEnabled'
  >;

const WebView = NativeWebView as unknown as React.ForwardRefExoticComponent<
  MobileWebViewProps & React.RefAttributes<WebViewHandle>
>;

async function openExternalUrl(url: string): Promise<void> {
  if (!isSafeExternalUrl(url)) return;
  try {
    await Linking.openURL(url);
  } catch {
    Alert.alert('无法打开链接', '设备上没有可以处理这个链接的应用。');
  }
}

export interface WebWindowHandle {
  goBack: () => void;
  reload: () => void;
  navigate: (url: string) => void;
}

interface WebWindowProps {
  startUrl: string;
  appOrigin: string;
  onNavigationChange: (navigation: WebViewNavigation) => void;
  onOpenWindow: (url: string) => void;
  active?: boolean;
  onChangeServer?: () => void;
}

export const WebWindow = React.forwardRef<WebWindowHandle, WebWindowProps>(
  function WebWindowContent(
    {
      startUrl,
      appOrigin,
      onNavigationChange,
      onOpenWindow,
      active = true,
      onChangeServer,
    },
    ref,
  ) {
    const webViewRef = useRef<WebViewHandle>(null);
    const netInfo = useNetInfo();
    const dark = useColorScheme() === 'dark';
    const colors = dark ? COLORS.dark : COLORS.light;
    const [sourceUrl, setSourceUrl] = useState(startUrl);
    const [loadVersion, setLoadVersion] = useState(0);
    const [currentUrl, setCurrentUrl] = useState(startUrl);
    const requestedUrl = useRef(startUrl);
    const [loading, setLoading] = useState(true);
    const [retrying, setRetrying] = useState(false);
    const [problem, setProblem] = useState<LoadProblem | null>(null);
    // An Internet reachability probe can fail even when a LAN website is reachable.
    const offline = netInfo.isConnected === false;
    const [credentialToken] = useState(createCredentialToken);
    const resumeRecovery = useRef({ expiresAt: 0, attempts: 0 });
    const [resumeCycle, setResumeCycle] = useState(0);
    const [foreground, setForeground] = useState(
      AppState.currentState !== 'background' &&
        AppState.currentState !== 'inactive',
    );

    const reloadPage = useCallback(() => {
      if (problem) {
        // A failed load or dead renderer may no longer have a reloadable document.
        setSourceUrl(problem.url);
        requestedUrl.current = problem.url;
        setCurrentUrl(problem.url);
        setProblem(null);
        setLoading(true);
        setLoadVersion(version => version + 1);
        return;
      }
      webViewRef.current?.reload();
    }, [problem]);

    const previousConnected = useRef(netInfo.isConnected);
    const previousActive = useRef(active);
    useEffect(() => {
      const restored =
        previousConnected.current === false && netInfo.isConnected === true;
      const selected = !previousActive.current && active;
      previousConnected.current = netInfo.isConnected;
      previousActive.current = active;
      if (
        foreground &&
        active &&
        !offline &&
        problem?.recoverable &&
        (restored || selected)
      )
        reloadPage();
    }, [active, foreground, netInfo.isConnected, offline, problem, reloadPage]);

    useEffect(() => {
      let previousState = AppState.currentState;
      const subscription = AppState.addEventListener('change', state => {
        const resumed = previousState !== 'active' && state === 'active';
        previousState = state;
        setForeground(state === 'active');
        if (resumed) {
          // WebView can report a failed connection just after resume, before Wi-Fi is ready.
          resumeRecovery.current = {
            expiresAt: Date.now() + 15000,
            attempts: 0,
          };
          setResumeCycle(cycle => cycle + 1);
        }
      });
      return () => subscription.remove();
    }, []);

    useEffect(() => {
      if (
        !active ||
        !foreground ||
        offline ||
        !problem?.recoverable ||
        resumeRecovery.current.attempts >= 2 ||
        Date.now() >= resumeRecovery.current.expiresAt
      )
        return;
      const timer = setTimeout(() => {
        resumeRecovery.current.attempts += 1;
        reloadPage();
      }, 1500 * (resumeRecovery.current.attempts + 1));
      return () => clearTimeout(timer);
    }, [active, foreground, offline, problem, reloadPage, resumeCycle]);

    const injectedJavaScript = useMemo(
      () => nativeBridgeBootstrap(Platform.OS, credentialToken, appOrigin),
      [credentialToken, appOrigin],
    );

    const loadInternalUrl = useCallback((url: string) => {
      if (webViewRef.current) {
        webViewRef.current.injectJavaScript(
          `window.location.assign(${JSON.stringify(url)}); true;`,
        );
        return;
      }
      setSourceUrl(url);
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        goBack: () => webViewRef.current?.goBack(),
        reload: reloadPage,
        navigate: url => {
          setProblem(null);
          loadInternalUrl(url);
        },
      }),
      [loadInternalUrl, reloadPage],
    );

    const retry = useCallback(async () => {
      setRetrying(true);
      try {
        const state = await NetInfo.fetch();
        if (state.isConnected === false) return;
        reloadPage();
      } catch {
        setProblem({
          detail: '无法检查网络连接，请稍后重试。',
          url: requestedUrl.current,
          recoverable: true,
        });
      } finally {
        setRetrying(false);
      }
    }, [reloadPage]);

    const handleNavigationRequest = useCallback(
      (request: ShouldStartLoadRequest) => {
        const decision = classifyBrowserNavigation(request.url);
        if (decision === 'internal') return true;
        if (decision === 'external')
          openExternalUrl(request.url).catch(() => undefined);
        return false;
      },
      [],
    );

    const handleNavigationChange = useCallback(
      (navigation: WebViewNavigation) => {
        onNavigationChange(navigation);
        if (/^https?:\/\//i.test(navigation.url)) {
          setCurrentUrl(navigation.url);
          requestedUrl.current = navigation.url;
        }
        setLoading(navigation.loading);
      },
      [onNavigationChange],
    );

    const handleMessage = useCallback(
      async (event: WebViewMessageEvent) => {
        // Visiting another website does not grant it access to this site's bridge.
        if (
          !/^https?:\/\//i.test(event.nativeEvent.url) ||
          classifyNavigation(
            event.nativeEvent.url,
            appOrigin,
            APP_CONFIG.trustedAuthOrigins,
          ) !== 'internal'
        )
          return;
        const message = parseNativeBridgeMessage(event.nativeEvent.data);
        if (!message) return;

        if (message.type === 'credentials') {
          // Credentials belong only to the selected server, never SSO or external sites.
          const sender = new URL(event.nativeEvent.url);
          if (sender.origin !== appOrigin || message.token !== credentialToken)
            return;
          let result: {
            credentials?: { username: string; password: string } | null;
            error?: string;
          } = {};
          try {
            if (message.action === 'load') {
              if (sender.pathname.replace(/\/$/, '') !== '/auth/login') return;
              result = { credentials: await loadCredentials(appOrigin) };
            } else if (message.action === 'save') {
              await saveCredentials(appOrigin, message);
            } else {
              await clearCredentials(appOrigin);
            }
          } catch {
            result = { error: '无法访问设备保存的密码，请重试。' };
          }
          webViewRef.current?.injectJavaScript(`
            if (window.location.origin === ${JSON.stringify(
              appOrigin,
            )} && window.AgentStudioNative) {
              window.AgentStudioNative.completeCredentialRequest(${JSON.stringify(
                credentialToken,
              )}, ${JSON.stringify(message.requestId)}, ${JSON.stringify(
            result,
          )});
            }
            true;
          `);
          return;
        }

        if (message.type === 'reload') {
          reloadPage();
          return;
        }
        if (message.type === 'openExternal') {
          await openExternalUrl(message.url);
          return;
        }
        await Share.share({
          title: message.title,
          message: message.url
            ? `${message.message}\n${message.url}`
            : message.message,
          url: message.url,
        });
      },
      [appOrigin, credentialToken, reloadPage],
    );

    const handleLoadError = useCallback((event: WebViewErrorEvent) => {
      // Use our recovery screen instead of the library's raw Domain: undefined page.
      event.preventDefault?.();
      const { code, description, url } = event.nativeEvent;
      const failedUrl = /^https?:\/\//i.test(url) ? url : requestedUrl.current;
      requestedUrl.current = failedUrl;
      setLoading(false);
      setProblem({
        detail: describeWebViewError(Platform.OS, code, description, failedUrl),
        url: failedUrl,
        recoverable: isRecoverableWebViewError(Platform.OS, code),
      });
    }, []);

    const handleHttpError = useCallback(
      (event: WebViewHttpErrorEvent) => {
        const { statusCode, url } = event.nativeEvent;
        if (statusCode >= 500 && url === currentUrl) {
          setLoading(false);
          setProblem({
            detail: `服务器返回了 HTTP ${statusCode}。`,
            url,
            recoverable: false,
          });
        }
      },
      [currentUrl],
    );

    const handleOpenWindow = useCallback(
      (event: WebViewOpenWindowEvent) => {
        const targetUrl = event.nativeEvent.targetUrl;
        const decision = classifyBrowserNavigation(targetUrl);
        if (decision === 'internal') onOpenWindow(targetUrl);
        if (decision === 'external')
          openExternalUrl(targetUrl).catch(() => undefined);
      },
      [onOpenWindow],
    );

    return (
      <View style={styles.webContent}>
        <WebView
          key={loadVersion}
          ref={webViewRef}
          source={{ uri: sourceUrl }}
          style={[styles.webView, { backgroundColor: colors.background }]}
          // Route every scheme through our policy instead of WebView opening it automatically.
          originWhitelist={['*']}
          applicationNameForUserAgent={APP_CONFIG.userAgentSuffix}
          webviewDebuggingEnabled={__DEV__}
          injectedJavaScriptBeforeContentLoaded={injectedJavaScript}
          injectedJavaScript={injectedJavaScript}
          javaScriptEnabled
          domStorageEnabled
          sharedCookiesEnabled
          thirdPartyCookiesEnabled={false}
          allowFileAccess={false}
          allowUniversalAccessFromFileURLs={false}
          mixedContentMode="never"
          setSupportMultipleWindows
          contentInsetAdjustmentBehavior="never"
          allowsBackForwardNavigationGestures
          mediaCapturePermissionGrantType="grantIfSameHostElsePrompt"
          onShouldStartLoadWithRequest={handleNavigationRequest}
          onNavigationStateChange={handleNavigationChange}
          onMessage={handleMessage}
          onOpenWindow={handleOpenWindow}
          onFileDownload={(event: FileDownloadEvent) => {
            openExternalUrl(event.nativeEvent.downloadUrl).catch(
              () => undefined,
            );
          }}
          onLoadStart={event => {
            // Android also emits this for pushState/popstate, without a load-end event.
            if (/^https?:\/\//i.test(event.nativeEvent.url)) {
              requestedUrl.current = event.nativeEvent.url;
              setLoading(event.nativeEvent.loading);
              setProblem(null);
            }
          }}
          onLoadProgress={event => {
            if (event.nativeEvent.progress >= 1) setLoading(false);
          }}
          onLoadEnd={() => setLoading(false)}
          onError={handleLoadError}
          renderError={() => <View />}
          renderLoading={() => <View />}
          onHttpError={handleHttpError}
          onContentProcessDidTerminate={() => {
            setProblem({
              detail: '网页进程已停止，请重新加载。',
              url: requestedUrl.current,
              recoverable: true,
            });
          }}
          onRenderProcessGone={() => {
            setProblem({
              detail: '网页进程异常退出，请重新加载。',
              url: requestedUrl.current,
              recoverable: true,
            });
          }}
        />

        {loading && !problem && !offline ? (
          <View
            accessibilityLabel="页面加载中"
            accessibilityRole="progressbar"
            style={[
              styles.loadingOverlay,
              { backgroundColor: colors.background },
            ]}
          >
            <ActivityIndicator color={colors.primary} size="large" />
          </View>
        ) : null}

        {problem || offline ? (
          <ConnectionProblem
            detail={problem?.detail}
            url={problem?.url || currentUrl}
            onChangeServer={onChangeServer}
            offline={offline}
            retrying={retrying}
            onRetry={retry}
          />
        ) : null}
      </View>
    );
  },
);

const styles = StyleSheet.create({
  webView: {
    flex: 1,
  },
  webContent: { flex: 1 },
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

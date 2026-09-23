import NetInfo, { useNetInfo } from '@react-native-community/netinfo';
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  Linking,
  Platform,
  Pressable,
  Share,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
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
  resolveDeepLink,
} from './navigationPolicy';
import { COLORS } from './theme';

interface LoadProblem {
  detail: string;
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

interface WebAppScreenProps {
  startUrl: string;
  onClose: () => void;
}

export function WebAppScreen({
  startUrl,
  onClose,
}: WebAppScreenProps): React.JSX.Element {
  const webViewRef = useRef<WebViewHandle>(null);
  const netInfo = useNetInfo();
  const dark = useColorScheme() === 'dark';
  const colors = dark ? COLORS.dark : COLORS.light;
  const appOrigin = new URL(startUrl).origin;
  const [sourceUrl, setSourceUrl] = useState(startUrl);
  const [currentUrl, setCurrentUrl] = useState(startUrl);
  const [canGoBack, setCanGoBack] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [problem, setProblem] = useState<LoadProblem | null>(null);
  // An Internet reachability probe can fail even when a LAN website is reachable.
  const offline = netInfo.isConnected === false;

  const injectedJavaScript = useMemo(
    () => nativeBridgeBootstrap(Platform.OS),
    [],
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

  const navigateFromDeepLink = useCallback(
    (incomingUrl: string) => {
      const resolved = resolveDeepLink(
        incomingUrl,
        appOrigin,
        APP_CONFIG.customUrlScheme,
      );
      if (!resolved) return;
      setProblem(null);
      loadInternalUrl(resolved);
    },
    [appOrigin, loadInternalUrl],
  );

  useEffect(() => {
    Linking.getInitialURL().then(url => {
      if (url) navigateFromDeepLink(url);
    });
    const subscription = Linking.addEventListener('url', event => {
      navigateFromDeepLink(event.url);
    });
    return () => subscription.remove();
  }, [navigateFromDeepLink]);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const subscription = BackHandler.addEventListener(
      'hardwareBackPress',
      () => {
        if (canGoBack) webViewRef.current?.goBack();
        else onClose();
        return true;
      },
    );
    return () => subscription.remove();
  }, [canGoBack, onClose]);

  const retry = useCallback(async () => {
    setRetrying(true);
    try {
      const state = await NetInfo.fetch();
      if (state.isConnected === false) return;
      setProblem(null);
      webViewRef.current?.reload();
    } catch {
      setProblem({ detail: '无法检查网络连接，请稍后重试。' });
    } finally {
      setRetrying(false);
    }
  }, []);

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
      setCanGoBack(navigation.canGoBack);
      if (navigation.url) setCurrentUrl(navigation.url);
      setLoading(navigation.loading);
    },
    [],
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

      if (message.type === 'reload') {
        setProblem(null);
        webViewRef.current?.reload();
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
    [appOrigin],
  );

  const handleLoadError = useCallback((event: WebViewErrorEvent) => {
    setLoading(false);
    setProblem({ detail: event.nativeEvent.description || '网络请求失败。' });
  }, []);

  const handleHttpError = useCallback(
    (event: WebViewHttpErrorEvent) => {
      const { statusCode, url } = event.nativeEvent;
      if (statusCode >= 500 && url === currentUrl) {
        setLoading(false);
        setProblem({ detail: `服务器返回了 HTTP ${statusCode}。` });
      }
    },
    [currentUrl],
  );

  const handleOpenWindow = useCallback(
    (event: WebViewOpenWindowEvent) => {
      const targetUrl = event.nativeEvent.targetUrl;
      const decision = classifyBrowserNavigation(targetUrl);
      if (decision === 'internal') loadInternalUrl(targetUrl);
      if (decision === 'external')
        openExternalUrl(targetUrl).catch(() => undefined);
    },
    [loadInternalUrl],
  );

  return (
    <SafeAreaView
      edges={['top', 'bottom', 'left', 'right']}
      style={[styles.safeArea, { backgroundColor: colors.surface }]}
    >
      <View style={[styles.toolbar, { borderBottomColor: colors.border }]}>
        <Text
          accessibilityLabel={`当前网址：${currentUrl}`}
          numberOfLines={1}
          ellipsizeMode="middle"
          style={[styles.address, { color: colors.text }]}
        >
          {currentUrl}
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="更换网址"
          onPress={onClose}
          style={({ pressed }) => [
            styles.changeButton,
            { opacity: pressed ? 0.65 : 1 },
          ]}
        >
          <Text style={[styles.changeLabel, { color: colors.primary }]}>
            更换网址
          </Text>
        </Pressable>
      </View>
      <View style={styles.webContent}>
        <WebView
          ref={webViewRef}
          source={{ uri: sourceUrl }}
          style={[styles.webView, { backgroundColor: colors.background }]}
          // Route every scheme through our policy instead of WebView opening it automatically.
          originWhitelist={['*']}
          applicationNameForUserAgent={APP_CONFIG.userAgentSuffix}
          webviewDebuggingEnabled={__DEV__}
          injectedJavaScriptBeforeContentLoaded={injectedJavaScript}
          javaScriptEnabled
          domStorageEnabled
          sharedCookiesEnabled
          thirdPartyCookiesEnabled={false}
          allowFileAccess={false}
          allowUniversalAccessFromFileURLs={false}
          mixedContentMode="never"
          setSupportMultipleWindows={false}
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
            setLoading(event.nativeEvent.loading);
            setProblem(null);
          }}
          onLoadProgress={event => {
            if (event.nativeEvent.progress >= 1) setLoading(false);
          }}
          onLoadEnd={() => setLoading(false)}
          onError={handleLoadError}
          onHttpError={handleHttpError}
          onContentProcessDidTerminate={() => {
            setProblem({ detail: '网页进程已停止，请重新加载。' });
          }}
          onRenderProcessGone={() => {
            setProblem({ detail: '网页进程异常退出，请重新加载。' });
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
            offline={offline}
            retrying={retrying}
            onRetry={retry}
          />
        ) : null}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  webView: {
    flex: 1,
  },
  webContent: { flex: 1 },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  address: { flex: 1, fontSize: 14, lineHeight: 22 },
  changeButton: {
    minHeight: 48,
    justifyContent: 'center',
    paddingHorizontal: 8,
  },
  changeLabel: { fontSize: 15, fontWeight: '600' },
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

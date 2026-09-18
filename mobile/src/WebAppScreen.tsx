import NetInfo, {useNetInfo} from '@react-native-community/netinfo';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  Linking,
  Platform,
  Share,
  StyleSheet,
  useColorScheme,
  View,
} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import {WebView as NativeWebView} from 'react-native-webview';
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

import {APP_CONFIG, appStartUrl} from './appConfig';
import {ConnectionProblem} from './ConnectionProblem';
import {nativeBridgeBootstrap, parseNativeBridgeMessage} from './nativeBridge';
import {
  classifyNavigation,
  isSafeExternalUrl,
  resolveDeepLink,
} from './navigationPolicy';
import {COLORS} from './theme';

interface LoadProblem {
  detail: string;
}

interface WebViewHandle {
  goBack: () => void;
  injectJavaScript: (script: string) => void;
  reload: () => void;
}

type MobileWebViewProps = WebViewSharedProps
  & Pick<AndroidWebViewProps,
    | 'allowFileAccess'
    | 'allowUniversalAccessFromFileURLs'
    | 'domStorageEnabled'
    | 'mixedContentMode'
    | 'onOpenWindow'
    | 'onRenderProcessGone'
    | 'setSupportMultipleWindows'
    | 'thirdPartyCookiesEnabled'>
  & Pick<IOSWebViewProps,
    | 'allowsBackForwardNavigationGestures'
    | 'contentInsetAdjustmentBehavior'
    | 'mediaCapturePermissionGrantType'
    | 'onContentProcessDidTerminate'
    | 'onFileDownload'
    | 'sharedCookiesEnabled'>;

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

export function WebAppScreen(): React.JSX.Element {
  const webViewRef = useRef<WebViewHandle>(null);
  const netInfo = useNetInfo();
  const dark = useColorScheme() === 'dark';
  const colors = dark ? COLORS.dark : COLORS.light;
  const [sourceUrl, setSourceUrl] = useState(appStartUrl);
  const [currentUrl, setCurrentUrl] = useState(appStartUrl);
  const [canGoBack, setCanGoBack] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [problem, setProblem] = useState<LoadProblem | null>(null);
  const offline = netInfo.isConnected === false || netInfo.isInternetReachable === false;

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

  const navigateFromDeepLink = useCallback((incomingUrl: string) => {
    const resolved = resolveDeepLink(
      incomingUrl,
      APP_CONFIG.appOrigin,
      APP_CONFIG.customUrlScheme,
    );
    if (!resolved) return;
    setProblem(null);
    loadInternalUrl(resolved);
  }, [loadInternalUrl]);

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
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!canGoBack) return false;
      webViewRef.current?.goBack();
      return true;
    });
    return () => subscription.remove();
  }, [canGoBack]);

  const retry = useCallback(async () => {
    setRetrying(true);
    const state = await NetInfo.fetch();
    const stillOffline = state.isConnected === false || state.isInternetReachable === false;
    if (!stillOffline) {
      setProblem(null);
      webViewRef.current?.reload();
    }
    setRetrying(false);
  }, []);

  const handleNavigationRequest = useCallback((request: ShouldStartLoadRequest) => {
    const decision = classifyNavigation(
      request.url,
      APP_CONFIG.appOrigin,
      APP_CONFIG.trustedAuthOrigins,
    );
    if (decision === 'internal') return true;
    if (decision === 'external') openExternalUrl(request.url).catch(() => undefined);
    return false;
  }, []);

  const handleNavigationChange = useCallback((navigation: WebViewNavigation) => {
    setCanGoBack(navigation.canGoBack);
    if (navigation.url) setCurrentUrl(navigation.url);
  }, []);

  const handleMessage = useCallback(async (event: WebViewMessageEvent) => {
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
  }, []);

  const handleLoadError = useCallback((event: WebViewErrorEvent) => {
    setLoading(false);
    setProblem({detail: event.nativeEvent.description || '网络请求失败。'});
  }, []);

  const handleHttpError = useCallback((event: WebViewHttpErrorEvent) => {
    const {statusCode, url} = event.nativeEvent;
    if (statusCode >= 500 && url === currentUrl) {
      setLoading(false);
      setProblem({detail: `服务器返回了 HTTP ${statusCode}。`});
    }
  }, [currentUrl]);

  const handleOpenWindow = useCallback((event: WebViewOpenWindowEvent) => {
    const targetUrl = event.nativeEvent.targetUrl;
    const decision = classifyNavigation(
      targetUrl,
      APP_CONFIG.appOrigin,
      APP_CONFIG.trustedAuthOrigins,
    );
    if (decision === 'internal') loadInternalUrl(targetUrl);
    if (decision === 'external') openExternalUrl(targetUrl).catch(() => undefined);
  }, [loadInternalUrl]);

  return (
    <SafeAreaView
      edges={['top', 'left', 'right']}
      style={[styles.safeArea, {backgroundColor: colors.surface}]}
    >
      <WebView
        ref={webViewRef}
        source={{uri: sourceUrl}}
        style={[styles.webView, {backgroundColor: colors.background}]}
        originWhitelist={['http://*', 'https://*']}
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
          openExternalUrl(event.nativeEvent.downloadUrl).catch(() => undefined);
        }}
        onLoadStart={() => setLoading(true)}
        onLoadEnd={() => setLoading(false)}
        onError={handleLoadError}
        onHttpError={handleHttpError}
        onContentProcessDidTerminate={() => {
          setProblem({detail: '网页进程已停止，请重新加载。'});
        }}
        onRenderProcessGone={() => {
          setProblem({detail: '网页进程异常退出，请重新加载。'});
        }}
      />

      {loading && !problem && !offline ? (
        <View
          accessibilityLabel="页面加载中"
          accessibilityRole="progressbar"
          style={[styles.loadingOverlay, {backgroundColor: colors.background}]}
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

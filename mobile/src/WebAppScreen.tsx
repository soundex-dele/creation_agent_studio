import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  BackHandler,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { APP_CONFIG } from './appConfig';
import { resolveDeepLink } from './navigationPolicy';
import { COLORS } from './theme';
import { WebWindow, type WebWindowHandle } from './WebWindow';
import { SettingsScreen } from './SettingsScreen';
import {
  House,
  RotateCw,
  Globe,
  Settings,
  PanelsTopLeft,
  X,
} from 'lucide-react-native';

interface BrowserWindow {
  id: number;
  loadVersion: number;
  sourceUrl: string;
  url: string;
  title: string;
  canGoBack: boolean;
}

function createWindow(id: number, url: string): BrowserWindow {
  return {
    id,
    loadVersion: 0,
    sourceUrl: url,
    url,
    title: '',
    canGoBack: false,
  };
}

interface WebAppScreenProps {
  startUrl: string;
  onClose: () => void;
}

export function WebAppScreen({
  startUrl,
  onClose,
}: WebAppScreenProps): React.JSX.Element {
  const colors = useColorScheme() === 'dark' ? COLORS.dark : COLORS.light;
  const appOrigin = new URL(startUrl).origin;
  const [windows, setWindows] = useState(() => [createWindow(0, startUrl)]);
  const [activeId, setActiveId] = useState(0);
  const [showWindows, setShowWindows] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const nextId = useRef(1);
  const windowRefs = useRef(new Map<number, WebWindowHandle>());
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const activeWindow = windows.find(window => window.id === activeId);

  const openWindow = useCallback((url: string) => {
    const id = nextId.current++;
    setWindows(previous => [...previous, createWindow(id, url)]);
    setActiveId(id);
  }, []);

  const closeWindow = useCallback(
    (id: number) => {
      const remaining = windows.filter(window => window.id !== id);
      if (!remaining.length) {
        setShowWindows(false);
        onClose();
        return;
      }
      if (id === activeId) {
        const index = windows.findIndex(window => window.id === id);
        setActiveId(remaining[Math.max(0, index - 1)].id);
      }
      setWindows(remaining);
    },
    [activeId, onClose, windows],
  );

  useEffect(() => {
    let mounted = true;
    const navigate = (incomingUrl: string) => {
      if (!mounted) return;
      const url = resolveDeepLink(
        incomingUrl,
        appOrigin,
        APP_CONFIG.customUrlScheme,
      );
      if (url) windowRefs.current.get(activeIdRef.current)?.navigate(url);
    };
    Linking.getInitialURL()
      .then(url => {
        if (url) navigate(url);
      })
      .catch(() => undefined);
    const subscription = Linking.addEventListener('url', event =>
      navigate(event.url),
    );
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, [appOrigin]);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const subscription = BackHandler.addEventListener(
      'hardwareBackPress',
      () => {
        if (activeWindow?.canGoBack) windowRefs.current.get(activeId)?.goBack();
        else closeWindow(activeId);
        return true;
      },
    );
    return () => subscription.remove();
  }, [activeId, activeWindow?.canGoBack, closeWindow]);

  return (
    <SafeAreaView
      edges={['top', 'bottom', 'left', 'right']}
      style={[styles.screen, { backgroundColor: colors.surface }]}
    >
      <View style={[styles.toolbar, { borderBottomColor: colors.border }]}>
        {[
          {
            label: '主页',
            icon: House,
            action: () =>
              setWindows(previous =>
                previous.map(window =>
                  window.id === activeId
                    ? {
                        ...createWindow(window.id, startUrl),
                        loadVersion: window.loadVersion + 1,
                      }
                    : window,
                ),
              ),
          },
          {
            label: '刷新',
            icon: RotateCw,
            action: () => windowRefs.current.get(activeId)?.reload(),
          },
          { label: '更换网址', icon: Globe, action: onClose },
          {
            label: '设置',
            icon: Settings,
            action: () => setShowSettings(true),
          },
          {
            label: `切换窗口 (${windows.length})`,
            icon: PanelsTopLeft,
            badge: windows.length,
            action: () => setShowWindows(true),
          },
        ].map(button => (
          <Pressable
            key={button.label}
            accessibilityRole="button"
            accessibilityLabel={button.label}
            onPress={button.action}
            style={({ pressed }) => [
              styles.toolbarButton,
              { opacity: pressed ? 0.6 : 1 },
            ]}
          >
            <View
              accessible={false}
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            >
              <button.icon
                size={24}
                color={colors.primary}
                accessible={false}
              />
              {button.badge !== undefined ? (
                <View
                  style={[styles.badge, { backgroundColor: colors.primary }]}
                >
                  <Text style={[styles.badgeText, { color: colors.onPrimary }]}>
                    {button.badge > 99 ? '99+' : button.badge}
                  </Text>
                </View>
              ) : null}
            </View>
          </Pressable>
        ))}
      </View>
      <View style={styles.screen}>
        {windows.map(window => (
          <View
            // A fresh WebView requests home even after a load failure or on the same URL.
            key={`${window.id}:${window.loadVersion}`}
            testID={`window-${window.id}`}
            // Keep inactive WebViews mounted so switching preserves forms and history.
            style={[
              styles.window,
              window.id !== activeId && styles.hiddenWindow,
            ]}
            pointerEvents={window.id === activeId ? 'auto' : 'none'}
            accessibilityElementsHidden={window.id !== activeId}
            importantForAccessibility={
              window.id === activeId ? 'auto' : 'no-hide-descendants'
            }
          >
            <WebWindow
              ref={handle => {
                if (handle) windowRefs.current.set(window.id, handle);
                else windowRefs.current.delete(window.id);
              }}
              startUrl={window.sourceUrl}
              appOrigin={appOrigin}
              active={window.id === activeId}
              onChangeServer={onClose}
              onOpenWindow={openWindow}
              onNavigationChange={navigation =>
                setWindows(previous =>
                  previous.map(item =>
                    item.id === window.id
                      ? {
                          ...item,
                          url: navigation.url || item.url,
                          title: navigation.title || '',
                          canGoBack: navigation.canGoBack,
                        }
                      : item,
                  ),
                )
              }
            />
          </View>
        ))}
      </View>
      <Modal
        visible={showWindows}
        transparent
        animationType="fade"
        onRequestClose={() => setShowWindows(false)}
      >
        <SafeAreaView style={styles.modalBackdrop}>
          <View
            accessibilityViewIsModal
            style={[styles.windowList, { backgroundColor: colors.surface }]}
          >
            <View style={styles.listHeader}>
              <Text
                accessibilityRole="header"
                style={[styles.heading, { color: colors.text }]}
              >
                窗口列表 ({windows.length})
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="关闭窗口列表"
                onPress={() => setShowWindows(false)}
                style={({ pressed }) => [
                  styles.closeButton,
                  { opacity: pressed ? 0.6 : 1 },
                ]}
              >
                <X size={24} color={colors.primary} accessible={false} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={styles.listContent}>
              {windows.map((window, index) => {
                const title =
                  window.title ||
                  (window.id === 0 ? '首页' : `窗口 ${index + 1}`);
                const selected = window.id === activeId;
                return (
                  <View
                    key={window.id}
                    style={[
                      styles.listRow,
                      {
                        borderColor: selected ? colors.primary : colors.border,
                      },
                    ]}
                  >
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`切换到${title}`}
                      accessibilityState={{ selected }}
                      onPress={() => {
                        setActiveId(window.id);
                        setShowWindows(false);
                      }}
                      style={({ pressed }) => [
                        styles.windowOption,
                        { opacity: pressed ? 0.6 : 1 },
                      ]}
                    >
                      <Text
                        numberOfLines={1}
                        style={[styles.windowTitle, { color: colors.text }]}
                      >
                        {title}
                      </Text>
                      <Text
                        numberOfLines={2}
                        style={[styles.windowUrl, { color: colors.muted }]}
                      >
                        {window.url}
                      </Text>
                      {selected ? (
                        <Text
                          style={[
                            styles.currentLabel,
                            { color: colors.primary },
                          ]}
                        >
                          当前窗口
                        </Text>
                      ) : null}
                    </Pressable>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`关闭${title}`}
                      onPress={() => closeWindow(window.id)}
                      style={({ pressed }) => [
                        styles.closeButton,
                        { opacity: pressed ? 0.6 : 1 },
                      ]}
                    >
                      <Text
                        style={[styles.buttonLabel, { color: colors.error }]}
                      >
                        关闭
                      </Text>
                    </Pressable>
                  </View>
                );
              })}
            </ScrollView>
          </View>
        </SafeAreaView>
      </Modal>
      {showSettings ? (
        <Modal
          visible
          animationType="slide"
          onRequestClose={() => setShowSettings(false)}
        >
          <SettingsScreen onBack={() => setShowSettings(false)} />
        </Modal>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  toolbar: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  toolbarButton: {
    flex: 1,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  badge: {
    position: 'absolute',
    right: -10,
    top: -6,
    minWidth: 17,
    height: 17,
    paddingHorizontal: 3,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 10, fontWeight: '700' },
  buttonLabel: { fontSize: 15, fontWeight: '600', textAlign: 'center' },
  window: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 },
  hiddenWindow: { display: 'none' },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    padding: 20,
  },
  windowList: {
    maxHeight: '85%',
    width: '100%',
    maxWidth: 560,
    alignSelf: 'center',
    borderRadius: 20,
    padding: 16,
  },
  listHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
  },
  heading: { flex: 1, fontSize: 20, fontWeight: '700' },
  listContent: { gap: 12 },
  listRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
    borderRadius: 12,
    paddingRight: 8,
  },
  windowOption: { flex: 1, minHeight: 64, padding: 12, gap: 4 },
  windowTitle: { fontSize: 16, fontWeight: '600' },
  windowUrl: { fontSize: 13, lineHeight: 20 },
  currentLabel: { fontSize: 13, fontWeight: '600' },
  closeButton: {
    minHeight: 48,
    minWidth: 48,
    paddingHorizontal: 8,
    justifyContent: 'center',
  },
});

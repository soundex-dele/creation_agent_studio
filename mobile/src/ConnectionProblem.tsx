import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { COLORS } from './theme';
import { connectionAddress } from './webViewErrors';

interface ConnectionProblemProps {
  detail?: string;
  offline: boolean;
  retrying: boolean;
  onRetry: () => void;
  url?: string;
  onChangeServer?: () => void;
}

export function ConnectionProblem({
  detail,
  offline,
  retrying,
  onRetry,
  url,
  onChangeServer,
}: ConnectionProblemProps): React.JSX.Element {
  const dark = useColorScheme() === 'dark';
  const colors = dark ? COLORS.dark : COLORS.light;

  return (
    <SafeAreaView
      accessibilityLiveRegion="polite"
      style={[styles.safeArea, { backgroundColor: colors.background }]}
    >
      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <View
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            style={[styles.statusMark, { borderColor: colors.primary }]}
          />
          <Text style={[styles.title, { color: colors.text }]}>
            {offline ? '当前无法连接网络' : '页面暂时无法打开'}
          </Text>
          <Text style={[styles.description, { color: colors.muted }]}>
            {offline
              ? '请检查 Wi-Fi 或移动网络，恢复连接后重试。'
              : detail || '服务器没有正常响应，请稍后重新加载。'}
          </Text>
          {url ? (
            <Text selectable style={[styles.address, { color: colors.muted }]}>
              {connectionAddress(url)}
            </Text>
          ) : null}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="重新加载页面"
            disabled={retrying}
            onPress={onRetry}
            style={({ pressed }) => [
              styles.retryButton,
              {
                backgroundColor: colors.primary,
                opacity: pressed || retrying ? 0.72 : 1,
              },
            ]}
          >
            {retrying ? (
              <ActivityIndicator color={colors.onPrimary} />
            ) : (
              <Text style={[styles.retryLabel, { color: colors.onPrimary }]}>
                重新加载
              </Text>
            )}
          </Pressable>
          {onChangeServer ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="更换服务器网址"
              onPress={onChangeServer}
              style={({ pressed }) => [
                styles.changeButton,
                { opacity: pressed ? 0.65 : 1 },
              ]}
            >
              <Text style={[styles.retryLabel, { color: colors.primary }]}>
                更换网址
              </Text>
            </Pressable>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  scroll: { width: '100%' },
  content: { flexGrow: 1, alignItems: 'center', justifyContent: 'center' },
  safeArea: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    alignItems: 'center',
    paddingVertical: 32,
  },
  statusMark: {
    width: 56,
    height: 56,
    marginBottom: 24,
    borderWidth: 6,
    borderRadius: 28,
    opacity: 0.82,
  },
  title: {
    marginBottom: 12,
    fontSize: 22,
    fontWeight: '700',
    lineHeight: 30,
    textAlign: 'center',
  },
  description: {
    maxWidth: 340,
    marginBottom: 28,
    fontSize: 16,
    lineHeight: 24,
    textAlign: 'center',
  },
  retryButton: {
    minWidth: 144,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    borderRadius: 12,
  },
  retryLabel: {
    fontSize: 16,
    fontWeight: '600',
  },
  address: {
    fontSize: 14,
    lineHeight: 22,
    textAlign: 'center',
    marginBottom: 20,
  },
  changeButton: {
    minHeight: 48,
    paddingHorizontal: 24,
    justifyContent: 'center',
    marginTop: 8,
  },
});

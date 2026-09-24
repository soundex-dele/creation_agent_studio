import React, { useRef, useState } from 'react';
import {
  Keyboard,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { COLORS } from './theme';
import { normalizeWebsiteUrl } from './websiteUrl';

interface WebsiteEntryScreenProps {
  initialUrl: string;
  initialError?: string;
  history?: string[];
  onOpen: (url: string) => Promise<void>;
}

export function WebsiteEntryScreen({
  initialUrl,
  initialError = '',
  history = [],
  onOpen,
}: WebsiteEntryScreenProps): React.JSX.Element {
  const colors = useColorScheme() === 'dark' ? COLORS.dark : COLORS.light;
  const [address, setAddress] = useState(initialUrl);
  const [error, setError] = useState(initialError);
  const [focused, setFocused] = useState(false);
  const [saving, setSaving] = useState(false);
  const submitting = useRef(false);

  const openWebsite = async (selectedAddress = address) => {
    if (submitting.current) return;
    const url = normalizeWebsiteUrl(selectedAddress);
    if (!url) {
      setError('请输入有效的网站地址，例如 https://example.com');
      return;
    }
    submitting.current = true;
    setSaving(true);
    setError('');
    try {
      await onOpen(url);
      Keyboard.dismiss();
    } catch {
      setError('网址未能保存，请重试。');
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  };

  return (
    <SafeAreaView
      style={[styles.screen, { backgroundColor: colors.background }]}
    >
      <KeyboardAvoidingView
        style={styles.screen}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.form}>
            <Text style={[styles.brand, { color: colors.primary }]}>
              AGENT STUDIO
            </Text>
            <Text
              accessibilityRole="header"
              style={[styles.title, { color: colors.text }]}
            >
              打开你的网站
            </Text>
            <Text style={[styles.description, { color: colors.muted }]}>
              输入网址，即可在 APP 内访问部署在服务器上的网页。
            </Text>
            <Text
              nativeID="website-address-label"
              style={[styles.label, { color: colors.text }]}
            >
              网站地址
            </Text>
            <TextInput
              accessibilityLabel="网站地址"
              accessibilityLabelledBy="website-address-label"
              accessibilityHint="输入域名或完整的 HTTP、HTTPS 网址"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              returnKeyType="go"
              placeholder="https://example.com"
              placeholderTextColor={colors.muted}
              selectionColor={colors.primary}
              value={address}
              editable={!saving}
              onChangeText={value => {
                setAddress(value);
                setError('');
              }}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onSubmitEditing={() => openWebsite()}
              style={[
                styles.input,
                {
                  color: colors.text,
                  backgroundColor: colors.surface,
                  borderColor: error
                    ? colors.error
                    : focused
                    ? colors.primary
                    : colors.border,
                },
              ]}
            />
            <Text
              accessibilityLiveRegion="polite"
              style={[
                styles.hint,
                { color: error ? colors.error : colors.muted },
              ]}
            >
              {error || '支持完整网址、路径和端口；省略协议时默认使用 HTTPS。'}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={saving ? '正在保存网址' : '打开网页'}
              accessibilityState={{ disabled: saving, busy: saving }}
              disabled={saving}
              onPress={() => openWebsite()}
              style={({ pressed }) => [
                styles.openButton,
                {
                  backgroundColor: colors.primary,
                  opacity: pressed || saving ? 0.75 : 1,
                },
              ]}
            >
              {saving ? (
                <ActivityIndicator color={colors.onPrimary} />
              ) : (
                <Text style={[styles.openLabel, { color: colors.onPrimary }]}>
                  打开网页
                </Text>
              )}
            </Pressable>
            <Text style={[styles.footer, { color: colors.muted }]}>
              自动记住网址，下次启动直接打开。可随时在顶部更换。
            </Text>
            {history.length > 0 ? (
              <View style={styles.history}>
                <Text
                  accessibilityRole="header"
                  style={[styles.label, { color: colors.text }]}
                >
                  历史服务器
                </Text>
                {history.map((url, index) => (
                  <Pressable
                    key={url}
                    accessibilityRole="button"
                    accessibilityLabel={`连接历史服务器：${url}`}
                    accessibilityState={{ disabled: saving }}
                    disabled={saving}
                    onPress={() => {
                      setAddress(url);
                      return openWebsite(url);
                    }}
                    style={({ pressed }) => [
                      styles.historyItem,
                      {
                        backgroundColor: colors.surface,
                        borderColor: colors.border,
                        opacity: pressed || saving ? 0.65 : 1,
                      },
                    ]}
                  >
                    <Text
                      numberOfLines={2}
                      style={[styles.historyUrl, { color: colors.text }]}
                    >
                      {url}
                    </Text>
                    <Text style={[styles.historyHint, { color: colors.muted }]}>
                      {index === 0 ? '最近使用 · 点击连接' : '点击连接'}
                    </Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingVertical: 40,
  },
  form: { width: '100%', maxWidth: 480, alignSelf: 'center' },
  brand: {
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 2,
    marginBottom: 20,
  },
  title: { fontSize: 30, lineHeight: 40, fontWeight: '700', marginBottom: 12 },
  description: { fontSize: 16, lineHeight: 26, marginBottom: 36 },
  label: { fontSize: 16, fontWeight: '600', marginBottom: 10 },
  input: {
    minHeight: 56,
    borderWidth: 1.5,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  hint: { fontSize: 14, lineHeight: 22, marginTop: 10, marginBottom: 24 },
  openButton: {
    minHeight: 52,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 14,
  },
  openLabel: { fontSize: 16, fontWeight: '600' },
  footer: { fontSize: 14, lineHeight: 22, textAlign: 'center', marginTop: 20 },
  history: { marginTop: 32, gap: 8 },
  historyItem: {
    minHeight: 64,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 12,
    padding: 14,
    gap: 4,
  },
  historyUrl: { fontSize: 16, lineHeight: 24 },
  historyHint: { fontSize: 13, lineHeight: 20 },
});

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  downloadPercent,
  downloadStatus,
  formatBytes,
  listDownloads,
  supportsDownloadProgress,
  type DownloadTask,
} from './downloads';
import { COLORS } from './theme';
import { ArrowLeft } from 'lucide-react-native';

export function SettingsScreen({
  onBack,
}: {
  onBack: () => void;
}): React.JSX.Element {
  const colors = useColorScheme() === 'dark' ? COLORS.dark : COLORS.light;
  const [tasks, setTasks] = useState<DownloadTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refreshRef = useRef<() => void>(() => {});
  const supported = supportsDownloadProgress();

  useEffect(() => {
    if (!supported) {
      setLoading(false);
      return;
    }
    let mounted = true;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let appState = AppState.currentState;
    const refresh = async () => {
      if (!mounted || inFlight || (appState && appState !== 'active')) return;
      clearTimeout(timer);
      inFlight = true;
      try {
        const downloads = await listDownloads();
        if (mounted) {
          setTasks(downloads);
          setError('');
        }
      } catch {
        if (mounted) setError('无法更新下载进度，请重试。');
      } finally {
        inFlight = false;
        if (mounted) {
          setLoading(false);
          if (!appState || appState === 'active')
            timer = setTimeout(refresh, 1000);
        }
      }
    };
    refreshRef.current = refresh;
    refresh();
    const subscription = AppState.addEventListener('change', state => {
      appState = state;
      clearTimeout(timer);
      if (state === 'active') refresh();
    });
    return () => {
      mounted = false;
      clearTimeout(timer);
      subscription.remove();
    };
  }, [supported]);

  const refresh = useCallback(() => refreshRef.current(), []);

  return (
    <SafeAreaView
      style={[styles.screen, { backgroundColor: colors.background }]}
    >
      <View
        style={[
          styles.header,
          { backgroundColor: colors.surface, borderBottomColor: colors.border },
        ]}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="返回网页"
          onPress={onBack}
          style={({ pressed }) => [
            styles.button,
            { opacity: pressed ? 0.6 : 1 },
          ]}
        >
          <ArrowLeft size={24} color={colors.primary} accessible={false} />
        </Pressable>
        <Text
          accessibilityRole="header"
          style={[styles.title, { color: colors.text }]}
        >
          设置
        </Text>
      </View>
      <View style={styles.intro}>
        <Text
          accessibilityRole="header"
          style={[styles.heading, { color: colors.text }]}
        >
          文件下载
        </Text>
        <Text style={[styles.description, { color: colors.muted }]}>
          {supported
            ? '查看本 APP 的系统下载任务，进度每秒自动更新。'
            : '当前平台的下载由系统处理，暂不支持在 APP 内查看进度。'}
        </Text>
      </View>
      {error ? (
        <View style={styles.error}>
          <Text
            accessibilityRole="alert"
            style={[styles.description, { color: colors.error }]}
          >
            {error}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="重试读取下载进度"
            onPress={refresh}
            style={styles.button}
          >
            <Text style={[styles.buttonText, { color: colors.primary }]}>
              重试
            </Text>
          </Pressable>
        </View>
      ) : null}
      {loading ? (
        <View style={styles.empty} accessibilityLabel="正在读取下载任务">
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : supported ? (
        <FlatList
          data={tasks}
          keyExtractor={task => task.id}
          contentContainerStyle={styles.list}
          ListEmptyComponent={
            !error ? (
              <View style={styles.empty}>
                <Text style={[styles.heading, { color: colors.text }]}>
                  暂无下载任务
                </Text>
                <Text style={[styles.description, { color: colors.muted }]}>
                  在网页中开始文件下载后，可在这里查看进度。
                </Text>
              </View>
            ) : undefined
          }
          renderItem={({ item }) => {
            const percent = downloadPercent(item);
            const active = ['pending', 'running', 'paused'].includes(
              item.status,
            );
            return (
              <View
                testID={`download-${item.id}`}
                style={[
                  styles.card,
                  {
                    backgroundColor: colors.surface,
                    borderColor: colors.border,
                  },
                ]}
              >
                <Text
                  numberOfLines={2}
                  style={[styles.filename, { color: colors.text }]}
                >
                  {item.filename}
                </Text>
                <View style={styles.progressRow}>
                  <Text
                    style={[
                      styles.status,
                      {
                        color:
                          item.status === 'failed'
                            ? colors.error
                            : colors.primary,
                      },
                    ]}
                  >
                    {downloadStatus(item)}
                  </Text>
                  {percent !== undefined ? (
                    <Text style={[styles.percent, { color: colors.text }]}>
                      {percent}%
                    </Text>
                  ) : active ? (
                    <ActivityIndicator color={colors.primary} size="small" />
                  ) : null}
                </View>
                {item.status !== 'failed' ? (
                  <View
                    accessibilityRole="progressbar"
                    accessibilityLabel={`${item.filename}下载进度`}
                    accessibilityValue={
                      percent === undefined
                        ? { text: '总大小未知' }
                        : { min: 0, max: 100, now: percent }
                    }
                    style={[
                      styles.track,
                      { backgroundColor: colors.background },
                    ]}
                  >
                    {percent !== undefined ? (
                      <View
                        style={[
                          styles.fill,
                          {
                            width: `${percent}%`,
                            backgroundColor: colors.primary,
                          },
                        ]}
                      />
                    ) : null}
                  </View>
                ) : null}
                <Text style={[styles.description, { color: colors.muted }]}>
                  {formatBytes(item.downloadedBytes)} /{' '}
                  {item.totalBytes <= 0 && item.status !== 'completed'
                    ? '大小未知'
                    : formatBytes(item.totalBytes)}
                </Text>
              </View>
            );
          }}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  button: {
    minHeight: 48,
    minWidth: 48,
    paddingHorizontal: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  buttonText: { fontSize: 16, fontWeight: '600' },
  title: { fontSize: 20, fontWeight: '700' },
  intro: { padding: 20, gap: 8 },
  heading: { fontSize: 18, fontWeight: '600' },
  description: { fontSize: 14, lineHeight: 22 },
  list: { paddingHorizontal: 20, paddingBottom: 24, gap: 12, flexGrow: 1 },
  card: {
    padding: 16,
    gap: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 14,
  },
  filename: { fontSize: 16, fontWeight: '600', lineHeight: 24 },
  progressRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  status: { flex: 1, fontSize: 14, lineHeight: 22 },
  percent: { fontSize: 14, fontWeight: '600' },
  track: { height: 6, borderRadius: 3, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 3 },
  empty: {
    flex: 1,
    padding: 24,
    gap: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  error: {
    paddingHorizontal: 20,
    paddingBottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
  },
});

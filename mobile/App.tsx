import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  StatusBar,
  StyleSheet,
  useColorScheme,
  View,
} from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { WebAppScreen } from './src/WebAppScreen';
import { WebsiteEntryScreen } from './src/WebsiteEntryScreen';
import { COLORS } from './src/theme';
import { loadWebsiteUrl, saveWebsiteUrl } from './src/websiteStorage';

function App(): React.JSX.Element {
  const isDarkMode = useColorScheme() === 'dark';
  const [websiteUrl, setWebsiteUrl] = useState<string | null>(null);
  const [lastUrl, setLastUrl] = useState('');
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState('');

  useEffect(() => {
    let active = true;
    loadWebsiteUrl()
      .then(url => {
        if (!active || !url) return;
        setLastUrl(url);
        setWebsiteUrl(url);
      })
      .catch(() => {
        if (active) setRestoreError('无法读取已保存的网址，请重新输入。');
      })
      .finally(() => {
        if (active) setRestoring(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const openWebsite = async (url: string) => {
    await saveWebsiteUrl(url);
    setRestoreError('');
    setLastUrl(url);
    setWebsiteUrl(url);
  };

  return (
    <SafeAreaProvider>
      <View
        style={[
          styles.container,
          {
            backgroundColor: isDarkMode
              ? COLORS.dark.surface
              : COLORS.light.surface,
          },
        ]}
      >
        <StatusBar barStyle={isDarkMode ? 'light-content' : 'dark-content'} />
        {restoring ? (
          <View
            style={styles.restoring}
            accessibilityLabel="正在打开网站"
            accessibilityRole="progressbar"
          >
            <ActivityIndicator
              color={isDarkMode ? COLORS.dark.primary : COLORS.light.primary}
            />
          </View>
        ) : websiteUrl ? (
          <WebAppScreen
            key={websiteUrl}
            startUrl={websiteUrl}
            onClose={() => setWebsiteUrl(null)}
          />
        ) : (
          <WebsiteEntryScreen
            initialUrl={lastUrl}
            initialError={restoreError}
            onOpen={openWebsite}
          />
        )}
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  restoring: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});

export default App;

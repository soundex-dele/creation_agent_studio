import {Platform} from 'react-native';

/**
 * Replace this origin before producing a store build. Keeping the web app and
 * Django API on one HTTPS origin preserves the existing HttpOnly refresh-cookie
 * session inside WKWebView and Android WebView.
 */
const PRODUCTION_APP_ORIGIN = 'https://studio.example.com';

const DEVELOPMENT_APP_ORIGIN = Platform.select({
  android: 'http://10.0.2.2:3030',
  ios: 'http://localhost:3030',
  default: 'http://localhost:3030',
});

export const APP_CONFIG = Object.freeze({
  appOrigin: __DEV__ ? DEVELOPMENT_APP_ORIGIN : PRODUCTION_APP_ORIGIN,
  /** Add exact HTTPS origins only when an embedded SSO provider is required. */
  trustedAuthOrigins: [] as readonly string[],
  customUrlScheme: 'agentstudio',
  userAgentSuffix: 'AgentStudioMobile/1.0',
});

export function appStartUrl(): string {
  return new URL('/', APP_CONFIG.appOrigin).toString();
}

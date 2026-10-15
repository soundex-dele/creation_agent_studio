import { defineConfig } from 'vitest/config';
import path from 'path';
import { applicationAliases, applicationPackages } from './applicationPackages';

export default defineConfig({
  root: path.resolve(__dirname, '..'),
  server: { fs: { allow: [path.resolve(__dirname, '..')] } },
  esbuild: { jsx: 'automatic' },
  plugins: [applicationPackages()],
  resolve: { dedupe: ['react', 'react-dom'], alias: {
    ...applicationAliases,
    'react': path.resolve(__dirname, './node_modules/react'),
    'react-dom': path.resolve(__dirname, './node_modules/react-dom'),
    '@': path.resolve(__dirname, './src'),
    'antd': path.resolve(__dirname, './node_modules/antd'),
    '@ant-design/icons': path.resolve(__dirname, './node_modules/@ant-design/icons'),
    '@phosphor-icons/react': path.resolve(__dirname, './node_modules/@phosphor-icons/react'),
    '@wechat-assistant': path.resolve(__dirname, '../app_center/wechat_assistant/react/src'),
    '@creation-toolbox': path.resolve(__dirname, '../app_center/creation_toolbox/react/src'),
  } },
  test: { environment: 'node', include: ['frontend/src/**/__tests__/**/*.test.{ts,tsx}', 'app_center/*/frontend/**/__tests__/**/*.test.{ts,tsx}'] },
});

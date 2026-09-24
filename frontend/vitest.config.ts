import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  resolve: { dedupe: ['react', 'react-dom'], alias: {
    'react': path.resolve(__dirname, './node_modules/react'),
    'react-dom': path.resolve(__dirname, './node_modules/react-dom'),
    '@': path.resolve(__dirname, './src'),
    'antd': path.resolve(__dirname, './node_modules/antd'),
    '@ant-design/icons': path.resolve(__dirname, './node_modules/@ant-design/icons'),
    '@wechat-assistant': path.resolve(__dirname, '../backend/app_center/wechat_assistant/react/src'),
    '@creation-toolbox': path.resolve(__dirname, '../backend/app_center/creation_toolbox/react/src'),
  } },
  test: { environment: 'node', include: ['src/**/__tests__/**/*.test.{ts,tsx}'] },
});

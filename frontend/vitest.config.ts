import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  resolve: { alias: {
    '@': path.resolve(__dirname, './src'),
    '@creation-toolbox': path.resolve(__dirname, '../backend/app_center/creation_toolbox/react/src'),
  } },
  test: { environment: 'node', include: ['src/**/__tests__/**/*.test.ts'] },
});

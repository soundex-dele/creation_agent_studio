import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@creation-master': process.env.VITE_EXCLUDE_CREATION_MASTER === 'true'
        ? path.resolve(__dirname, './src/stubs/creation-master')
        : path.resolve(__dirname, '../backend/app_center/creation_master/react/src'),
      '@creation-toolbox': path.resolve(__dirname, '../backend/app_center/creation_toolbox/react/src'),
      '@newmedia-workbench': path.resolve(__dirname, '../backend/app_center/newmedia_workbench/react/src'),
      '@phosphor-icons/react': path.resolve(__dirname, './node_modules/@phosphor-icons/react'),
      'lucide-react': path.resolve(__dirname, './node_modules/lucide-react/dist/esm/lucide-react.js'),
    },
  },
  build: {
    chunkSizeWarningLimit: 550,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const marker = '/node_modules/';
          const normalized = id.replace(/\\/g, '/');
          const index = normalized.lastIndexOf(marker);
          if (index < 0) return undefined;
          const parts = normalized.slice(index + marker.length).split('/');
          const packageName = parts[0].startsWith('@')
            ? `${parts[0]}-${parts[1]}`
            : parts[0];
          if (packageName === 'antd') return 'vendor-antd';
          if (
            packageName.startsWith('rc-')
            || packageName.startsWith('@rc-component-')
            || packageName.startsWith('@ant-design-')
          ) return 'vendor-antd-runtime';
          if (
            packageName === 'react'
            || packageName === 'react-dom'
            || packageName === 'react-router'
            || packageName === 'react-router-dom'
            || packageName === 'scheduler'
          ) return 'vendor-react';
          if (
            packageName === 'axios'
            || packageName === 'react-markdown'
            || packageName === 'zustand'
          ) return 'vendor-common';
          return undefined;
        },
      },
    },
  },
  server: {
    port: 3030,
    fs: {
      allow: [path.resolve(__dirname, '..')],
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
        changeOrigin: true,
      },
      '/media': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    }
  }
})

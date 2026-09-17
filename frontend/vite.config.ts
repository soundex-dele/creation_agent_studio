import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

const wemdRoot = path.resolve(__dirname, '../backend/app_center/WeMD')
const wemdPublicRoot = path.resolve(wemdRoot, 'apps/web/public')
const wemdWebPackagePath = path.resolve(wemdRoot, 'apps/web/package.json')
const wemdCorePackagePath = path.resolve(wemdRoot, 'packages/core/package.json')
const wemdAvailable = [
  wemdWebPackagePath,
  wemdCorePackagePath,
  wemdPublicRoot,
  path.resolve(wemdRoot, 'apps/web/src/main.tsx'),
  path.resolve(wemdRoot, 'packages/core/src/index.ts'),
].every((requiredPath) => fs.existsSync(requiredPath))

type PackageMetadata = {
  version?: string
  dependencies?: Record<string, string>
}

const readPackageMetadata = (packagePath: string): PackageMetadata => JSON.parse(
  fs.readFileSync(packagePath, 'utf-8'),
)
const wemdPackage = wemdAvailable ? readPackageMetadata(wemdWebPackagePath) : {}
const wemdCorePackage = wemdAvailable ? readPackageMetadata(wemdCorePackagePath) : {}
const wemdDependencyNames = new Set([
  ...Object.keys(wemdPackage.dependencies ?? {}),
  ...Object.keys(wemdCorePackage.dependencies ?? {}),
])

const contentTypes: Record<string, string> = {
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

/** Merge WeMD's standalone public assets into the host dev server and build. */
function wemdPublicAssets() {
  const files = (directory: string): string[] => fs.readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const absolute = path.join(directory, entry.name)
      return entry.isDirectory() ? files(absolute) : [absolute]
    })

  return {
    name: 'wemd-public-assets',
    configureServer(server: { middlewares: { use: (handler: Function) => void } }) {
      server.middlewares.use((request: { url?: string }, response: {
        setHeader: (name: string, value: string) => void
        end: (body: Buffer) => void
      }, next: () => void) => {
        const pathname = decodeURIComponent((request.url ?? '').split('?', 1)[0])
        const relative = pathname.replace(/^\/+/, '')
        const candidate = path.resolve(wemdPublicRoot, relative)
        if (!relative || !candidate.startsWith(`${wemdPublicRoot}${path.sep}`)) {
          next()
          return
        }
        try {
          if (!fs.statSync(candidate).isFile()) {
            next()
            return
          }
          response.setHeader('Content-Type', contentTypes[path.extname(candidate)] ?? 'application/octet-stream')
          response.end(fs.readFileSync(candidate))
        } catch {
          next()
        }
      })
    },
    generateBundle() {
      for (const absolute of files(wemdPublicRoot)) {
        this.emitFile({
          type: 'asset',
          fileName: path.relative(wemdPublicRoot, absolute).replace(/\\/g, '/'),
          source: fs.readFileSync(absolute),
        })
      }
    },
  }
}

/** Resolve WeMD's bare imports from the host install instead of its source tree. */
function wemdHostDependencies() {
  const resolverAnchor = path.resolve(__dirname, 'src/main.tsx')
  return {
    name: 'wemd-host-dependencies',
    enforce: 'pre' as const,
    async resolveId(source: string, importer?: string) {
      if (
        !importer?.startsWith(wemdRoot)
        || source === '@wemd/core'
        || source.startsWith('.')
        || source.startsWith('/')
        || source.startsWith('\0')
      ) {
        return null
      }
      return this.resolve(source, resolverAnchor, { skipSelf: true })
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    ...(wemdAvailable ? [wemdHostDependencies(), wemdPublicAssets()] : []),
  ],
  define: wemdAvailable ? {
    __APP_VERSION__: JSON.stringify(wemdPackage.version),
  } : {},
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@wemd/core': path.resolve(wemdRoot, 'packages/core/src/index.ts'),
      '@creation-master': process.env.VITE_EXCLUDE_CREATION_MASTER === 'true'
        ? path.resolve(__dirname, './src/stubs/creation-master')
        : path.resolve(__dirname, '../backend/app_center/creation_master/react/src'),
      '@newmedia-workbench': path.resolve(__dirname, '../backend/app_center/newmedia_workbench/react/src'),
      'lucide-react': path.resolve(__dirname, './node_modules/lucide-react/dist/esm/lucide-react.js'),
    },
  },
  build: {
    chunkSizeWarningLimit: 550,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
        ...(wemdAvailable ? { wemd: path.resolve(__dirname, 'wemd.html') } : {}),
      },
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
            || packageName === '@babel/runtime'
          ) return 'vendor-antd-runtime';
          if (
            packageName === 'react'
            || packageName === 'react-dom'
            || packageName === 'react-router'
            || packageName === 'react-router-dom'
            || packageName === 'scheduler'
          ) return 'vendor-react';
          // Keep the host application's established shared dependencies cached,
          // while letting Rollup place WeMD-only packages behind wemd.html.
          if (
            packageName === 'axios'
            || packageName === 'react-markdown'
            || packageName === 'zustand'
          ) return 'vendor-common';
          if (wemdDependencyNames.has(packageName)) return 'vendor-wemd';
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
    }
  }
})

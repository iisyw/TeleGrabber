import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';
import fs from 'node:fs';

/** 兼容 DefaultFramework 的 "host:port" 写法，也允许直接写完整 URL。 */
function normalizeBackendUrl(value) {
  const raw = (value || '').trim();
  if (!raw) return '';
  return /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = normalizeBackendUrl(
    process.env.VITE_API_PROXY_URL || env.VITE_API_PROXY_URL,
  );

  const server = {
    host: '0.0.0.0',
    port: Number(process.env.VITE_PORT || env.VITE_PORT) || 5173,
    strictPort: false,
    open: env.VITE_OPEN === 'true',
    hmr: { overlay: true },
  };

  if (proxyTarget) {
    server.proxy = {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/media': { target: proxyTarget, changeOrigin: true },
      '/thumb': { target: proxyTarget, changeOrigin: true },
    };
  }

  if (env.VITE_USE_HTTPS === 'true') {
    const keyPath = env.VITE_SSL_KEY_PATH || './ssl/cert-key.pem';
    const certPath = env.VITE_SSL_CERT_PATH || './ssl/cert.pem';
    const keyFile = fileURLToPath(new URL(keyPath, import.meta.url));
    const certFile = fileURLToPath(new URL(certPath, import.meta.url));
    if (fs.existsSync(keyFile) && fs.existsSync(certFile)) {
      server.https = {
        key: fs.readFileSync(keyFile),
        cert: fs.readFileSync(certFile),
      };
    } else {
      console.warn('VITE_USE_HTTPS=true 但未找到证书文件，回退到 HTTP');
    }
  }

  const drop = [];
  if (env.VITE_DROP_CONSOLE === 'true') drop.push('console');
  if (env.VITE_DROP_DEBUGGER === 'true') drop.push('debugger');

  return {
    plugins: [vue()],
    esbuild: drop.length > 0 ? { drop } : undefined,
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server,
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: mode !== 'production',
      assetsInlineLimit: 8192,
      reportCompressedSize: false,
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'element-plus': ['element-plus'],
            utils: ['axios'],
          },
          chunkFileNames: 'assets/js/[name]-[hash].js',
          entryFileNames: 'assets/js/[name]-[hash].js',
          assetFileNames: 'assets/[ext]/[name]-[hash].[ext]',
        },
      },
    },
  };
});

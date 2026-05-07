import { defineConfig } from 'vite';
import path from 'node:path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { TanStackRouterVite } from '@tanstack/router-plugin/vite';

const API_PROXY_TARGET = process.env.VITE_API_PROXY ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [
		TanStackRouterVite({
			routesDirectory: './src/routes',
			generatedRouteTree: './src/routeTree.gen.ts',
			autoCodeSplitting: true,
		}),
		react(),
		tailwindcss(),
	],
	resolve: {
		alias: {
			'@': path.resolve(__dirname, './src'),
		},
	},
	server: {
		port: 3000,
		strictPort: false,
		proxy: {
			'/api': {
				target: API_PROXY_TARGET,
				changeOrigin: false,
				rewrite: (p) => p.replace(/^\/api/, ''),
			},
			'/mcp': {
				target: API_PROXY_TARGET,
				changeOrigin: false,
			},
			'/login': {
				target: API_PROXY_TARGET,
				changeOrigin: false,
			},
		},
	},
	build: {
		outDir: 'dist',
		sourcemap: true,
		rollupOptions: {
			output: {
				// Split heavy vendor libs out of the main entry chunk so the
				// initial download stays small. Per-route chunking is already
				// handled by TanStack Router's autoCodeSplitting.
				manualChunks: (id) => {
					if (!id.includes('node_modules')) return undefined;
					if (id.includes('@tanstack/react-router')) return 'tanstack-router';
					if (id.includes('@tanstack/react-query')) return 'tanstack-query';
					if (id.includes('@radix-ui')) return 'radix';
					if (id.includes('react-hook-form') || id.includes('@hookform') || id.includes('/zod/')) return 'forms';
					if (id.includes('i18next') || id.includes('react-i18next')) return 'i18n';
					if (id.includes('lucide-react')) return 'icons';
					if (id.includes('/react-dom/') || id.includes('/react/')) return 'react';
					return 'vendor';
				},
			},
		},
	},
});

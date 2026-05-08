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
		// No manualChunks: Vite/Rollup's default chunking already extracts
		// vendor and respects ESM init order. A hand-rolled split previously
		// created a vendor↔react cycle that threw "Cannot access '_' before
		// initialization" at boot. Per-route splitting is handled by
		// TanStack Router's autoCodeSplitting.
	},
});

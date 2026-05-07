import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import { routeTree } from '@/routeTree.gen';
import { queryClient } from '@/lib/query-client';
import { loadRuntimeConfig } from '@/lib/config';
import '@/styles/globals.css';

const router = createRouter({
	routeTree,
	context: { queryClient },
	defaultPreload: 'intent',
	defaultPreloadStaleTime: 0,
});

declare module '@tanstack/react-router' {
	interface Register {
		router: typeof router;
	}
}

async function boot() {
	await loadRuntimeConfig();

	const rootEl = document.getElementById('root');
	if (!rootEl) throw new Error('#root element missing from index.html');

	createRoot(rootEl).render(
		<StrictMode>
			<QueryClientProvider client={queryClient}>
				<RouterProvider router={router} />
			</QueryClientProvider>
		</StrictMode>,
	);
}

void boot();

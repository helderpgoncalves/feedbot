import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createRouter } from '@tanstack/react-router';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/i18n';
import { loadRuntimeConfig } from '@/lib/config';
import { queryClient } from '@/lib/query-client';
import { routeTree } from '@/routeTree.gen';
import '@/styles/globals.css';

const router = createRouter({
	routeTree,
	context: { queryClient },
	defaultPreload: 'intent',
	defaultPreloadStaleTime: 0,
	// Static path-not-found page; the in-route NotFound component still wins
	// for nested misses.
	defaultNotFoundComponent: undefined,
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

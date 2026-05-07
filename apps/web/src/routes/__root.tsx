/**
 * Root layout — shell that every page lives inside.
 *
 * Renders just the routed children plus the global toaster and devtools.
 * Auth-gating happens in the {@link (authed) layout group} so unauthenticated
 * routes (login, magic) never trigger a `/v1/me` fetch.
 */

import type { QueryClient } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { Outlet, createRootRouteWithContext } from '@tanstack/react-router';
import { TanStackRouterDevtools } from '@tanstack/router-devtools';
import { Toaster } from '@/components/ui/sonner';
import { ErrorScreen } from '@/components/layout/error-screen';
import { NotFound } from '@/components/layout/not-found';

export interface RouterContext {
	queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
	component: RootLayout,
	errorComponent: ({ error, reset }) => <ErrorScreen error={error} onReset={reset} />,
	notFoundComponent: NotFound,
});

function RootLayout() {
	return (
		<>
			<Outlet />
			<Toaster />
			{import.meta.env.DEV && (
				<>
					<TanStackRouterDevtools position="bottom-right" />
					<ReactQueryDevtools buttonPosition="bottom-left" />
				</>
			)}
		</>
	);
}

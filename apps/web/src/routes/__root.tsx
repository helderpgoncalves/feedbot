import { Outlet, createRootRouteWithContext } from '@tanstack/react-router';
import { TanStackRouterDevtools } from '@tanstack/router-devtools';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import type { QueryClient } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';

interface RouterContext {
	queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
	component: RootLayout,
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

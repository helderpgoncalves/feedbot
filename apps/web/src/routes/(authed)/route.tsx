/**
 * (authed) — pathless layout that redirects unauthenticated visitors to
 * /login BEFORE the page renders. The /v1/me query is prefetched in
 * `beforeLoad` so child routes can read it from cache synchronously.
 */

import { Outlet, createFileRoute, redirect } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/app-shell';
import { meQueryOptions } from '@/lib/auth';

export const Route = createFileRoute('/(authed)')({
	beforeLoad: async ({ context, location }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) {
			throw redirect({
				to: '/login',
				search: {
					// Preserve where the user was going so we can return them
					// after they sign in.
					redirect: location.href,
				},
			});
		}
	},
	component: AuthedLayout,
});

function AuthedLayout() {
	return (
		<AppShell>
			<Outlet />
		</AppShell>
	);
}

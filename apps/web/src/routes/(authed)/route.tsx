/**
 * (authed) — pathless layout that redirects unauthenticated visitors to
 * /login BEFORE the page renders. The /v1/me query is prefetched in
 * `beforeLoad` so child routes can read it from cache synchronously.
 */

import { Outlet, createFileRoute, redirect } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/app-shell';
import { meQueryOptions, setupStatusQueryOptions } from '@/lib/auth';

export const Route = createFileRoute('/(authed)')({
	beforeLoad: async ({ context, location }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) {
			// If the DB has no users yet, the answer isn't "log in" — the answer
			// is "bootstrap the first owner". Send the visitor to /setup;
			// otherwise to /login (preserving where they were going).
			const status = await context.queryClient.ensureQueryData(
				setupStatusQueryOptions(),
			);
			if (status.required) {
				throw redirect({ to: '/setup' });
			}
			throw redirect({
				to: '/login',
				search: {
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

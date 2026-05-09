/**
 * (authed) — pathless layout that redirects unauthenticated visitors to
 * /login BEFORE the page renders. The /v1/me query is prefetched in
 * `beforeLoad` so child routes can read it from cache synchronously.
 */

import { Outlet, createFileRoute, redirect } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/app-shell';
import { meQueryOptions, setupStatusQueryOptions } from '@/lib/auth';
import { getConfig } from '@/lib/config';

export const Route = createFileRoute('/(authed)')({
	beforeLoad: async ({ context, location }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (me) return;

		// Not signed in. Three legitimate next-steps depending on deployment:
		//
		//   - DB empty + cloud signup on  >>>  /signup (multi-tenant onboarding)
		//   - DB empty + self-host       >>>  /setup   (first-owner wizard)
		//   - DB has users               >>>  /login   (regular sign-in)
		const status = await context.queryClient.ensureQueryData(
			setupStatusQueryOptions(),
		);
		const cfg = getConfig();
		if (status.required) {
			if (cfg.deployment === 'cloud' && cfg.allowSignup) {
				throw redirect({ to: '/signup' });
			}
			throw redirect({ to: '/setup' });
		}
		throw redirect({
			to: '/login',
			search: {
				redirect: location.href,
			},
		});
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

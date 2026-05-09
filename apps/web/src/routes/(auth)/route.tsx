/**
 * (auth) — pathless layout for routes that DON'T require a session
 * (login, magic-link landing, invite preview/accept, first-run setup).
 *
 * Renders a centered shell so login screens look intentional rather than
 * exposing the empty app-frame.
 *
 * If the deployment still needs first-run bootstrap, every public route
 * except ``/setup`` redirects there — that's the only thing the user can
 * usefully do before the first owner exists.
 */

import { Outlet, createFileRoute, redirect } from '@tanstack/react-router';
import { setupStatusQueryOptions } from '@/lib/auth';
import { getConfig } from '@/lib/config';

export const Route = createFileRoute('/(auth)')({
	beforeLoad: async ({ context, location }) => {
		if (location.pathname === '/setup' || location.pathname === '/signup') {
			return;
		}
		const status = await context.queryClient.ensureQueryData(setupStatusQueryOptions());
		if (!status.required) return;

		// Cloud (multi-tenant): "DB has zero users" doesn't mean "bootstrap
		// the first owner" — it means "nobody has signed up yet". Send the
		// visitor to /signup so they can create their own workspace, not to
		// /setup which is the single-tenant first-run wizard.
		const cfg = getConfig();
		if (cfg.deployment === 'cloud' && cfg.allowSignup) {
			throw redirect({ to: '/signup' });
		}
		throw redirect({ to: '/setup' });
	},
	component: AuthLayout,
});

function AuthLayout() {
	return (
		<div className="min-h-screen flex items-center justify-center p-6 bg-background">
			<div className="w-full max-w-md">
				<Outlet />
			</div>
		</div>
	);
}

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

export const Route = createFileRoute('/(auth)')({
	beforeLoad: async ({ context, location }) => {
		if (location.pathname === '/setup') return;
		const status = await context.queryClient.ensureQueryData(setupStatusQueryOptions());
		if (status.required) {
			throw redirect({ to: '/setup' });
		}
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

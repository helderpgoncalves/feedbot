/**
 * (auth) — pathless layout for routes that DON'T require a session
 * (login, magic-link landing, invite preview/accept).
 *
 * Renders a centered shell so login screens look intentional rather than
 * exposing the empty app-frame.
 */

import { Outlet, createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/(auth)')({
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

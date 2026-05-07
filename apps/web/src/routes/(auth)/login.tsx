/**
 * F3.1 placeholder for the login page; F3.2 replaces this with the real form.
 * Kept intentionally minimal so the route tree compiles end-to-end before the
 * full auth UI lands.
 */

import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/(auth)/login')({
	validateSearch: (search): { redirect?: string } => ({
		redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
	}),
	component: LoginPlaceholder,
});

function LoginPlaceholder() {
	return (
		<div className="text-sm text-muted-foreground text-center">
			Login form lands in F3.2.
		</div>
	);
}

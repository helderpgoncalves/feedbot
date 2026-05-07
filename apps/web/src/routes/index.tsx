/**
 * Root index — instantly redirects to either the projects list or the
 * sign-in page depending on auth state. Avoids rendering anything visible
 * so users never see a blank shell at the root URL.
 */

import { createFileRoute, redirect } from '@tanstack/react-router';
import { meQueryOptions } from '@/lib/auth';

export const Route = createFileRoute('/')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (me) {
			throw redirect({ to: '/projects' });
		}
		throw redirect({ to: '/login' });
	},
});

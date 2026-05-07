/**
 * Magic-link landing page. Receives `?email=&token=` from the email and
 * exchanges them for a session cookie via GET /v1/auth/magic. Three states:
 *
 *   verifying  — request in flight (default on mount)
 *   success    — cookie set; navigate to /projects
 *   failed     — token invalid/expired, offer "Request a new link"
 *
 * Cross-device protection: the API also checks the `mlnonce` cookie set
 * during /login. If the user opened the link in a different browser, the
 * API records `login.cross_device` (lax mode → still succeeds, but emails
 * a notice). Either way the user lands here without seeing the difference.
 */

import { useMutation } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import { ApiError } from '@/lib/api';
import { meQueryOptions } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';

export const Route = createFileRoute('/(auth)/magic')({
	validateSearch: (search): { email?: string; token?: string } => ({
		email: typeof search.email === 'string' ? search.email : undefined,
		token: typeof search.token === 'string' ? search.token : undefined,
	}),
	component: MagicPage,
});

function MagicPage() {
	const { t } = useTranslation();
	const { email, token } = Route.useSearch();
	const navigate = useNavigate();

	const verify = useMutation({
		mutationFn: async () => {
			if (!email || !token) {
				throw new ApiError(400, 'invalid or expired link', null);
			}
			// openapi-fetch types `email`/`token` as required query params,
			// so passing them satisfies the type-checker.
			const { response, error } = await api.GET('/v1/auth/magic', {
				params: { query: { email, token } },
			});
			if (!response.ok) {
				const detail =
					(error as { detail?: string } | undefined)?.detail ?? 'invalid';
				throw new ApiError(response.status, detail, error);
			}
		},
		onSuccess: async () => {
			// Cookie is now set; refetch /v1/me before navigating so the
			// authed shell has identity ready and there's no flash.
			await queryClient.invalidateQueries({ queryKey: meQueryOptions().queryKey });
			await queryClient.fetchQuery(meQueryOptions());
			await navigate({ to: '/projects', replace: true });
		},
		// onError swallowed — the form below renders the failed-state card.
		meta: { silent: true },
	});

	useEffect(() => {
		verify.mutate();
		// Trigger once on mount; deps intentionally empty.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	if (verify.isPending || verify.isIdle) {
		return (
			<Card>
				<CardHeader className="text-center">
					<CardTitle className="flex items-center justify-center gap-2">
						<Loader2 className="size-4 animate-spin" />
						{t('auth.magic.verifying')}
					</CardTitle>
				</CardHeader>
			</Card>
		);
	}

	if (verify.isError) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{t('auth.magic.failed_title')}</CardTitle>
					<CardDescription>{t('auth.magic.failed_subtitle')}</CardDescription>
				</CardHeader>
				<CardContent>
					<Button asChild className="w-full">
						<Link to="/login">{t('auth.magic.try_again')}</Link>
					</Button>
				</CardContent>
			</Card>
		);
	}

	// Success — navigation already in flight.
	return null;
}

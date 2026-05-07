/**
 * Public invite-accept page. Reads the token from the URL, calls
 * GET /v1/invites/preview for metadata, and on confirm POSTs to
 * /v1/invites/accept which creates the user + a session cookie.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { meQueryOptions } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { components } from '@/types/api';

type InvitePreviewOut = components['schemas']['InvitePreviewOut'];

export const Route = createFileRoute('/(auth)/invites/$token')({
	component: InvitePage,
});

function InvitePage() {
	const { t } = useTranslation();
	const { token } = Route.useParams();
	const navigate = useNavigate();

	const preview = useQuery({
		queryKey: queryKeys.invites.preview(token),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/invites/preview', { params: { query: { token } } }),
			);
			return data as unknown as InvitePreviewOut;
		},
		retry: false,
		meta: { silent: true },
	});

	const accept = useMutation({
		mutationFn: () =>
			unwrap(api.POST('/v1/invites/accept', { body: { token } })),
		onSuccess: async () => {
			await queryClient.invalidateQueries({ queryKey: meQueryOptions().queryKey });
			await queryClient.fetchQuery(meQueryOptions());
			await navigate({ to: '/projects', replace: true });
		},
	});

	if (preview.isLoading) {
		return <Skeleton className="h-40 w-full" />;
	}
	if (preview.isError || !preview.data) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{t('errors.404')}</CardTitle>
					<CardDescription>{t('auth.magic.failed_subtitle')}</CardDescription>
				</CardHeader>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader className="text-center">
				<CardTitle>You're invited to {preview.data.tenant_name}</CardTitle>
				<CardDescription>
					Email <span className="font-mono">{preview.data.email}</span> · role{' '}
					<span className="font-mono">{preview.data.role}</span>
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Button
					className="w-full"
					onClick={() => accept.mutate()}
					disabled={accept.isPending}
				>
					{accept.isPending ? t('common.saving') : t('common.confirm')}
				</Button>
			</CardContent>
		</Card>
	);
}

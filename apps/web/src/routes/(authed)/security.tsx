/**
 * Security page — lists every active session of the current user, lets them
 * revoke each one or sign out everywhere. Powered by GET /v1/auth/sessions.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';

interface SessionRow {
	id: string;
	created_at: string;
	last_seen_at: string;
	expires_at: string;
	user_agent: string | null;
	ip: string | null;
	is_current: boolean;
}

export const Route = createFileRoute('/(authed)/security')({
	component: SecurityPage,
});

function SecurityPage() {
	const { t } = useTranslation();
	const navigate = useNavigate();
	const [confirmAll, setConfirmAll] = useState(false);

	const sessionsQuery = useQuery({
		queryKey: queryKeys.auth.sessions(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/auth/sessions'));
			return data as unknown as SessionRow[];
		},
	});

	const logoutAll = useMutation({
		mutationFn: () => unwrap(api.POST('/v1/auth/logout-all')),
		onSuccess: async () => {
			queryClient.removeQueries({ queryKey: queryKeys.me() });
			queryClient.removeQueries({ queryKey: queryKeys.auth.sessions() });
			await navigate({ to: '/login', replace: true });
		},
	});

	return (
		<div className="space-y-6">
			<div className="flex items-start justify-between gap-4">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">
						{t('auth.security.title')}
					</h1>
					<p className="text-sm text-muted-foreground mt-1">
						{t('auth.security.subtitle')}
					</p>
				</div>
				<Button
					variant="destructive"
					onClick={() => setConfirmAll(true)}
					disabled={logoutAll.isPending}
				>
					{t('auth.security.sign_out_all')}
				</Button>
			</div>

			{sessionsQuery.isLoading ? (
				<div className="space-y-3">
					<Skeleton className="h-20 w-full" />
					<Skeleton className="h-20 w-full" />
				</div>
			) : (
				<div className="grid gap-3">
					{(sessionsQuery.data ?? []).map((s) => (
						<SessionCard key={s.id} session={s} />
					))}
				</div>
			)}

			<Dialog open={confirmAll} onOpenChange={setConfirmAll}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('auth.security.sign_out_all')}</DialogTitle>
						<DialogDescription>
							{t('auth.security.sign_out_all_confirm')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmAll(false)}>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							onClick={() => logoutAll.mutate()}
							disabled={logoutAll.isPending}
						>
							{logoutAll.isPending
								? t('common.saving')
								: t('auth.security.sign_out_all')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

function SessionCard({ session }: { session: SessionRow }) {
	const { t, i18n } = useTranslation();
	const fmt = (iso: string) =>
		new Date(iso).toLocaleString(i18n.language, {
			year: 'numeric',
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit',
		});

	return (
		<Card>
			<CardHeader className="gap-1">
				<div className="flex items-center justify-between gap-3">
					<CardTitle className="text-base flex items-center gap-2 font-mono break-all">
						{session.user_agent ?? t('auth.security.unknown_device')}
						{session.is_current && (
							<Badge variant="success">{t('auth.security.current')}</Badge>
						)}
					</CardTitle>
				</div>
				<CardDescription className="font-mono text-xs">
					{session.ip ?? '—'}
				</CardDescription>
			</CardHeader>
			<CardContent className="grid grid-cols-3 gap-4 text-sm">
				<MetaCell
					label={t('auth.security.created')}
					value={fmt(session.created_at)}
				/>
				<MetaCell
					label={t('auth.security.last_seen')}
					value={fmt(session.last_seen_at)}
				/>
				<MetaCell
					label={t('auth.security.expires')}
					value={fmt(session.expires_at)}
				/>
			</CardContent>
		</Card>
	);
}

function MetaCell({ label, value }: { label: string; value: string }) {
	return (
		<div>
			<div className="text-xs text-muted-foreground">{label}</div>
			<div className="font-mono">{value}</div>
		</div>
	);
}

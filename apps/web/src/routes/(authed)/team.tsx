/**
 * Team page — members + pending invites. Owner/admin only (the route
 * also redirects in beforeLoad if a non-admin somehow reaches it).
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { createFileRoute, redirect } from '@tanstack/react-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2, UserPlus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from '@/components/ui/table';
import { api, unwrap } from '@/lib/api';
import { isAdmin, meQueryOptions } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { components } from '@/types/api';
import { InviteDialog } from './-components/invite-dialog';

type TenantUserOut = components['schemas']['TenantUserOut'];
type InviteOut = components['schemas']['InviteOut'];

export const Route = createFileRoute('/(authed)/team')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me || !isAdmin(me.user.role)) {
			throw redirect({ to: '/projects' });
		}
	},
	component: TeamPage,
});

function TeamPage() {
	const { t } = useTranslation();
	const [inviteOpen, setInviteOpen] = useState(false);

	const users = useQuery({
		queryKey: queryKeys.tenant.users(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/tenant/users'));
			return data as unknown as TenantUserOut[];
		},
	});

	const invites = useQuery({
		queryKey: queryKeys.invites.all(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/invites'));
			return data as unknown as InviteOut[];
		},
	});

	return (
		<div className="space-y-6">
			<div className="flex items-center justify-between gap-4">
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('team.title')}
				</h1>
				<Button onClick={() => setInviteOpen(true)}>
					<UserPlus className="size-4" />
					{t('team.invite')}
				</Button>
			</div>

			<Card>
				<CardHeader>
					<CardTitle className="text-base">{t('team.members')}</CardTitle>
				</CardHeader>
				<CardContent>
					{users.isLoading ? (
						<Skeleton className="h-32 w-full" />
					) : (
						<MembersTable users={users.data ?? []} />
					)}
				</CardContent>
			</Card>

			<Card>
				<CardHeader>
					<CardTitle className="text-base">{t('team.invites_pending')}</CardTitle>
				</CardHeader>
				<CardContent>
					{invites.isLoading ? (
						<Skeleton className="h-24 w-full" />
					) : (invites.data ?? []).length === 0 ? (
						<p className="text-sm text-muted-foreground">{t('common.empty')}</p>
					) : (
						<InvitesTable invites={invites.data ?? []} />
					)}
				</CardContent>
			</Card>

			<InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} />
		</div>
	);
}

function MembersTable({ users }: { users: TenantUserOut[] }) {
	const remove = useMutation({
		mutationFn: (userId: number) =>
			unwrap(
				api.DELETE('/v1/tenant/users/{user_id}', {
					params: { path: { user_id: userId } },
				}),
			),
		onSuccess: () =>
			queryClient.invalidateQueries({ queryKey: queryKeys.tenant.users() }),
	});

	return (
		<Table>
			<TableHeader>
				<TableRow>
					<TableHead>Email</TableHead>
					<TableHead>Role</TableHead>
					<TableHead className="w-12" />
				</TableRow>
			</TableHeader>
			<TableBody>
				{users.map((u) => (
					<TableRow key={u.id}>
						<TableCell className="font-mono">{u.email}</TableCell>
						<TableCell>
							<Badge variant={u.role === 'owner' ? 'default' : 'secondary'}>
								{u.role}
							</Badge>
						</TableCell>
						<TableCell className="text-right">
							{u.role !== 'owner' && (
								<Button
									size="icon"
									variant="ghost"
									onClick={() => {
										if (window.confirm(`Remove ${u.email}?`)) remove.mutate(u.id);
									}}
									disabled={remove.isPending}
									aria-label={`Remove ${u.email}`}
								>
									<Trash2 className="size-4" />
								</Button>
							)}
						</TableCell>
					</TableRow>
				))}
			</TableBody>
		</Table>
	);
}

function InvitesTable({ invites }: { invites: InviteOut[] }) {
	const revoke = useMutation({
		mutationFn: (id: number) =>
			unwrap(
				api.DELETE('/v1/invites/{invite_id}', {
					params: { path: { invite_id: id } },
				}),
			),
		onSuccess: () =>
			queryClient.invalidateQueries({ queryKey: queryKeys.invites.all() }),
	});

	return (
		<Table>
			<TableHeader>
				<TableRow>
					<TableHead>Email</TableHead>
					<TableHead>Role</TableHead>
					<TableHead>Expires</TableHead>
					<TableHead className="w-12" />
				</TableRow>
			</TableHeader>
			<TableBody>
				{invites.map((inv) => (
					<TableRow key={inv.id}>
						<TableCell className="font-mono">{inv.email}</TableCell>
						<TableCell>
							<Badge variant="secondary">{inv.role}</Badge>
						</TableCell>
						<TableCell className="font-mono text-xs">
							{new Date(inv.expires_at).toLocaleDateString()}
						</TableCell>
						<TableCell className="text-right">
							<Button
								size="icon"
								variant="ghost"
								onClick={() => revoke.mutate(inv.id)}
								disabled={revoke.isPending}
								aria-label="Revoke invite"
							>
								<Trash2 className="size-4" />
							</Button>
						</TableCell>
					</TableRow>
				))}
			</TableBody>
		</Table>
	);
}

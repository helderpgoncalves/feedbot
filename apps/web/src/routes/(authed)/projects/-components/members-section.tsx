/**
 * Project-scoped membership management. Admin-only.
 *
 * Members in this list are tenant users who can see this project; owners and
 * tenant-admins always see every project regardless of membership, so this UI
 * effectively gates *member* visibility — it's how a tenant-admin grants a
 * non-admin user access to a single project.
 *
 * Add flow: pick from the list of tenant users who aren't already members.
 * The /v1/tenant/users endpoint is admin-only, which mirrors the privilege
 * needed to mutate membership here, so we re-use it without a separate
 * "candidates" endpoint.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, Users } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { ProjectSlug } from '@/lib/types';
import type { components } from '@/types/api';

type TenantUserOut = components['schemas']['TenantUserOut'];

interface Props {
	slug: ProjectSlug;
}

export function MembersSection({ slug }: Props) {
	const { t } = useTranslation();
	const [addOpen, setAddOpen] = useState(false);
	const [confirmRemove, setConfirmRemove] = useState<TenantUserOut | null>(null);

	const members = useQuery({
		queryKey: queryKeys.projects.members(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/members', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as TenantUserOut[];
		},
	});

	return (
		<Card>
			<CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
				<div className="space-y-1">
					<CardTitle className="flex items-center gap-2">
						<Users className="size-4" />
						{t('projects.members.title')}
					</CardTitle>
					<CardDescription>{t('projects.members.description')}</CardDescription>
				</div>
				<Button size="sm" onClick={() => setAddOpen(true)}>
					<Plus className="size-4" />
					{t('projects.members.add')}
				</Button>
			</CardHeader>
			<CardContent>
				{members.isLoading ? (
					<MembersSkeleton />
				) : members.data && members.data.length > 0 ? (
					<MembersTable rows={members.data} onRemove={setConfirmRemove} />
				) : (
					<p className="text-sm text-muted-foreground">
						{t('projects.members.empty')}
					</p>
				)}
			</CardContent>

			<AddMemberDialog
				slug={slug}
				open={addOpen}
				onOpenChange={setAddOpen}
				existing={members.data ?? []}
			/>

			<RemoveMemberDialog
				slug={slug}
				row={confirmRemove}
				onOpenChange={(open) => {
					if (!open) setConfirmRemove(null);
				}}
			/>
		</Card>
	);
}

function MembersSkeleton() {
	return (
		<div className="space-y-2">
			<Skeleton className="h-10 w-full" />
			<Skeleton className="h-10 w-full" />
		</div>
	);
}

function MembersTable({
	rows,
	onRemove,
}: {
	rows: TenantUserOut[];
	onRemove: (row: TenantUserOut) => void;
}) {
	const { t } = useTranslation();
	return (
		<div className="overflow-x-auto rounded-md border">
			<table className="w-full text-sm">
				<thead className="bg-muted/50 text-muted-foreground">
					<tr>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.members.col_email')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.members.col_role')}
						</th>
						<th className="px-3 py-2 text-right font-medium" />
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => {
						const isPrivileged = row.role === 'owner' || row.role === 'admin';
						return (
							<tr key={row.id} className="border-t last:border-b-0 hover:bg-muted/30">
								<td className="px-3 py-2">{row.email}</td>
								<td className="px-3 py-2">
									<Badge variant={isPrivileged ? 'secondary' : 'outline'}>
										{row.role}
									</Badge>
								</td>
								<td className="px-3 py-2 text-right">
									{!isPrivileged && (
										<Button
											size="sm"
											variant="ghost"
											onClick={() => onRemove(row)}
											aria-label={t('projects.members.remove')}
										>
											<Trash2 className="size-4" />
										</Button>
									)}
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}

function AddMemberDialog({
	slug,
	open,
	onOpenChange,
	existing,
}: {
	slug: ProjectSlug;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	existing: TenantUserOut[];
}) {
	const { t } = useTranslation();
	const [selected, setSelected] = useState<string>('');

	const tenantUsers = useQuery({
		queryKey: queryKeys.tenant.users(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/tenant/users'));
			return data as unknown as TenantUserOut[];
		},
		enabled: open,
	});

	const candidates = useMemo(() => {
		const memberIds = new Set(existing.map((m) => m.id));
		return (tenantUsers.data ?? []).filter(
			(u) => !memberIds.has(u.id) && u.role === 'member',
		);
	}, [tenantUsers.data, existing]);

	const add = useMutation({
		mutationFn: async () => {
			if (!selected) return;
			await unwrap(
				api.POST('/v1/projects/{slug}/members', {
					params: { path: { slug } },
					body: { user_id: Number(selected) },
				}),
			);
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.members(slug),
			});
			setSelected('');
			onOpenChange(false);
		},
	});

	return (
		<Dialog
			open={open}
			onOpenChange={(o) => {
				if (!add.isPending) onOpenChange(o);
			}}
		>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('projects.members.add_title')}</DialogTitle>
					<DialogDescription>
						{t('projects.members.add_description')}
					</DialogDescription>
				</DialogHeader>

				{tenantUsers.isLoading ? (
					<Skeleton className="h-10" />
				) : candidates.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						{t('projects.members.no_candidates')}
					</p>
				) : (
					<Select value={selected} onValueChange={setSelected}>
						<SelectTrigger>
							<SelectValue placeholder={t('projects.members.pick_user')} />
						</SelectTrigger>
						<SelectContent>
							{candidates.map((u) => (
								<SelectItem key={u.id} value={String(u.id)}>
									{u.email}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
				)}

				<DialogFooter>
					<Button
						variant="outline"
						onClick={() => onOpenChange(false)}
						disabled={add.isPending}
					>
						{t('common.cancel')}
					</Button>
					<Button
						onClick={() => add.mutate()}
						disabled={!selected || add.isPending}
					>
						{add.isPending ? t('common.saving') : t('projects.members.add')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

function RemoveMemberDialog({
	slug,
	row,
	onOpenChange,
}: {
	slug: ProjectSlug;
	row: TenantUserOut | null;
	onOpenChange: (open: boolean) => void;
}) {
	const { t } = useTranslation();

	const remove = useMutation({
		mutationFn: async () => {
			if (!row) return;
			await unwrap(
				api.DELETE('/v1/projects/{slug}/members/{user_id}', {
					params: { path: { slug, user_id: row.id } },
				}),
			);
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.members(slug),
			});
			onOpenChange(false);
		},
	});

	return (
		<Dialog
			open={!!row}
			onOpenChange={(o) => {
				if (!remove.isPending) onOpenChange(o);
			}}
		>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('projects.members.remove_title')}</DialogTitle>
					<DialogDescription>
						{t('projects.members.remove_body', { email: row?.email ?? '' })}
					</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button
						variant="outline"
						onClick={() => onOpenChange(false)}
						disabled={remove.isPending}
					>
						{t('common.cancel')}
					</Button>
					<Button
						variant="destructive"
						onClick={() => remove.mutate()}
						disabled={remove.isPending}
					>
						{remove.isPending ? t('common.saving') : t('projects.members.remove')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

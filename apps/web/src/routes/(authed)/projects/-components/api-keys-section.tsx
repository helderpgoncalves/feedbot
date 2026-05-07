/**
 * Project-scoped API key management. Admin-only.
 *
 * The full secret is returned exactly once by ``POST /v1/projects/{slug}/api-keys``;
 * we surface it inside a one-time reveal banner with a click-to-copy button and
 * stash the just-created key in local state so the sibling
 * {@link ConnectMcpSection} can pre-fill its snippets without forcing the user
 * to paste it back in. After dismissal the key is gone forever — both from
 * memory and from the server's perspective (only the Argon2 hash is stored).
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, KeyRound, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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

type ApiKeyOut = components['schemas']['ApiKeyOut'];
type ApiKeyCreated = components['schemas']['ApiKeyCreated'];

interface Props {
	slug: ProjectSlug;
	/** Reveal handler — emits the just-created secret to the parent so the
	 *  Connect-MCP panel can pre-fill snippets while the alert is still up. */
	onKeyCreated?: (key: ApiKeyCreated) => void;
}

export function ApiKeysSection({ slug, onKeyCreated }: Props) {
	const { t } = useTranslation();
	const [createOpen, setCreateOpen] = useState(false);
	const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null);
	const [confirmRevoke, setConfirmRevoke] = useState<ApiKeyOut | null>(null);

	const keys = useQuery({
		queryKey: queryKeys.projects.apiKeys(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/api-keys', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as ApiKeyOut[];
		},
	});

	return (
		<Card>
			<CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
				<div className="space-y-1">
					<CardTitle className="flex items-center gap-2">
						<KeyRound className="size-4" />
						{t('projects.api_keys.title')}
					</CardTitle>
					<CardDescription>{t('projects.api_keys.description')}</CardDescription>
				</div>
				<Button size="sm" onClick={() => setCreateOpen(true)}>
					<Plus className="size-4" />
					{t('projects.api_keys.new')}
				</Button>
			</CardHeader>
			<CardContent className="space-y-4">
				{revealed && (
					<RevealedKeyAlert
						created={revealed}
						onDismiss={() => setRevealed(null)}
					/>
				)}

				{keys.isLoading ? (
					<KeysSkeleton />
				) : keys.data && keys.data.length > 0 ? (
					<KeysTable rows={keys.data} onRevoke={setConfirmRevoke} />
				) : (
					<p className="text-sm text-muted-foreground">
						{t('projects.api_keys.empty')}
					</p>
				)}
			</CardContent>

			<CreateKeyDialog
				slug={slug}
				open={createOpen}
				onOpenChange={setCreateOpen}
				onCreated={(created) => {
					setRevealed(created);
					onKeyCreated?.(created);
				}}
			/>

			<RevokeKeyDialog
				slug={slug}
				row={confirmRevoke}
				onOpenChange={(open) => {
					if (!open) setConfirmRevoke(null);
				}}
			/>
		</Card>
	);
}

// ─── List ────────────────────────────────────────────────────────────────────

function KeysSkeleton() {
	return (
		<div className="space-y-2">
			<Skeleton className="h-10 w-full" />
			<Skeleton className="h-10 w-full" />
		</div>
	);
}

function KeysTable({
	rows,
	onRevoke,
}: {
	rows: ApiKeyOut[];
	onRevoke: (row: ApiKeyOut) => void;
}) {
	const { t, i18n } = useTranslation();
	const fmt = new Intl.DateTimeFormat(i18n.language, {
		dateStyle: 'medium',
		timeStyle: 'short',
	});
	return (
		<div className="overflow-x-auto rounded-md border">
			<table className="w-full text-sm">
				<thead className="bg-muted/50 text-muted-foreground">
					<tr>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.api_keys.col_label')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.api_keys.col_prefix')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.api_keys.col_scope')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.api_keys.col_last_used')}
						</th>
						<th className="px-3 py-2 text-right font-medium">
							{t('projects.api_keys.col_actions')}
						</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => {
						const revoked = !!row.revoked_at;
						return (
							<tr
								key={row.id}
								className="border-t last:border-b-0 hover:bg-muted/30"
								data-revoked={revoked}
							>
								<td className="px-3 py-2">
									<span className={revoked ? 'line-through text-muted-foreground' : ''}>
										{row.label}
									</span>
									{revoked && (
										<Badge variant="outline" className="ml-2">
											{t('projects.api_keys.revoked')}
										</Badge>
									)}
								</td>
								<td className="px-3 py-2 font-mono text-xs">{row.prefix}…</td>
								<td className="px-3 py-2">
									<Badge variant={row.scope === 'read' ? 'outline' : 'secondary'}>
										{row.scope}
									</Badge>
								</td>
								<td className="px-3 py-2 text-muted-foreground text-xs">
									{row.last_used_at
										? fmt.format(new Date(row.last_used_at))
										: t('projects.api_keys.never_used')}
								</td>
								<td className="px-3 py-2 text-right">
									{!revoked && (
										<Button
											size="sm"
											variant="ghost"
											onClick={() => onRevoke(row)}
											aria-label={t('projects.api_keys.revoke')}
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

// ─── One-time reveal banner ──────────────────────────────────────────────────

function RevealedKeyAlert({
	created,
	onDismiss,
}: {
	created: ApiKeyCreated;
	onDismiss: () => void;
}) {
	const { t } = useTranslation();
	return (
		<Alert>
			<AlertTitle>{t('projects.api_keys.reveal_title')}</AlertTitle>
			<AlertDescription className="space-y-3">
				<p>{t('projects.api_keys.reveal_body')}</p>
				<div className="flex items-center gap-2">
					<Input
						readOnly
						value={created.key}
						className="font-mono text-xs"
						onFocus={(e) => e.currentTarget.select()}
					/>
					<CopyButton value={created.key} />
				</div>
				<div className="flex justify-end">
					<Button size="sm" variant="outline" onClick={onDismiss}>
						{t('projects.api_keys.reveal_dismiss')}
					</Button>
				</div>
			</AlertDescription>
		</Alert>
	);
}

export function CopyButton({
	value,
	label,
	size = 'sm',
}: {
	value: string;
	label?: string;
	size?: 'sm' | 'icon';
}) {
	const { t } = useTranslation();
	return (
		<Button
			type="button"
			size={size === 'icon' ? 'sm' : 'sm'}
			variant="outline"
			onClick={async () => {
				try {
					await navigator.clipboard.writeText(value);
					toast.success(t('common.copied'));
				} catch {
					toast.error(t('common.copy_failed'));
				}
			}}
		>
			<Copy className="size-4" />
			{label ?? t('common.copy')}
		</Button>
	);
}

// ─── Create dialog ───────────────────────────────────────────────────────────

function CreateKeyDialog({
	slug,
	open,
	onOpenChange,
	onCreated,
}: {
	slug: ProjectSlug;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreated: (created: ApiKeyCreated) => void;
}) {
	const { t } = useTranslation();
	const [label, setLabel] = useState('');
	const [scope, setScope] = useState<'read' | 'write' | 'admin'>('write');

	const create = useMutation({
		mutationFn: async () => {
			const data = await unwrap(
				api.POST('/v1/projects/{slug}/api-keys', {
					params: { path: { slug } },
					body: { label: label.trim(), scope },
				}),
			);
			return data as unknown as ApiKeyCreated;
		},
		onSuccess: async (created) => {
			await queryClient.invalidateQueries({ queryKey: queryKeys.projects.apiKeys(slug) });
			onCreated(created);
			setLabel('');
			setScope('write');
			onOpenChange(false);
		},
	});

	return (
		<Dialog
			open={open}
			onOpenChange={(o) => {
				if (!create.isPending) onOpenChange(o);
			}}
		>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('projects.api_keys.create_title')}</DialogTitle>
					<DialogDescription>
						{t('projects.api_keys.create_description')}
					</DialogDescription>
				</DialogHeader>
				<form
					onSubmit={(e) => {
						e.preventDefault();
						if (label.trim().length === 0) return;
						create.mutate();
					}}
					className="space-y-4"
					noValidate
				>
					<div className="space-y-2">
						<Label htmlFor="api-key-label">
							{t('projects.api_keys.label_label')}
						</Label>
						<Input
							id="api-key-label"
							placeholder={t('projects.api_keys.label_placeholder')}
							autoFocus
							value={label}
							onChange={(e) => setLabel(e.target.value)}
							maxLength={120}
							required
						/>
					</div>
					<div className="space-y-2">
						<Label htmlFor="api-key-scope">
							{t('projects.api_keys.scope_label')}
						</Label>
						<Select
							value={scope}
							onValueChange={(v) => setScope(v as 'read' | 'write' | 'admin')}
						>
							<SelectTrigger id="api-key-scope">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="read">
									{t('projects.api_keys.scope_read')}
								</SelectItem>
								<SelectItem value="write">
									{t('projects.api_keys.scope_write')}
								</SelectItem>
								<SelectItem value="admin">
									{t('projects.api_keys.scope_admin')}
								</SelectItem>
							</SelectContent>
						</Select>
					</div>
					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={create.isPending}
						>
							{t('common.cancel')}
						</Button>
						<Button
							type="submit"
							disabled={create.isPending || label.trim().length === 0}
						>
							{create.isPending ? t('common.saving') : t('common.create')}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

// ─── Revoke confirmation ─────────────────────────────────────────────────────

function RevokeKeyDialog({
	slug,
	row,
	onOpenChange,
}: {
	slug: ProjectSlug;
	row: ApiKeyOut | null;
	onOpenChange: (open: boolean) => void;
}) {
	const { t } = useTranslation();

	const revoke = useMutation({
		mutationFn: async () => {
			if (!row) return;
			await unwrap(
				api.DELETE('/v1/projects/{slug}/api-keys/{key_id}', {
					params: { path: { slug, key_id: row.id } },
				}),
			);
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({ queryKey: queryKeys.projects.apiKeys(slug) });
			onOpenChange(false);
		},
	});

	return (
		<Dialog
			open={!!row}
			onOpenChange={(o) => {
				if (!revoke.isPending) onOpenChange(o);
			}}
		>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('projects.api_keys.revoke_title')}</DialogTitle>
					<DialogDescription>
						{t('projects.api_keys.revoke_body', { label: row?.label ?? '' })}
					</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button
						variant="outline"
						onClick={() => onOpenChange(false)}
						disabled={revoke.isPending}
					>
						{t('common.cancel')}
					</Button>
					<Button
						variant="destructive"
						onClick={() => revoke.mutate()}
						disabled={revoke.isPending}
					>
						{revoke.isPending ? t('common.saving') : t('projects.api_keys.revoke')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

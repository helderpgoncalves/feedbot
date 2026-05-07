/**
 * Telegram chat-link onboarding for a project. Admin-only.
 *
 * Two-step flow:
 *   1. Admin clicks "Generate invite" → POST /v1/projects/{slug}/chat-link-tokens
 *      returns a 15-min single-use token + a deep link
 *      ``https://t.me/<bot>?startgroup=link_<token>``.
 *   2. Admin clicks the deep link (or copies the token) → adds the bot to a
 *      group → the bot DMs ``/start link_<token>`` server-side, server
 *      consumes the token + creates a chat_link row → group is now bound.
 *
 * If ``FEEDBOT_TELEGRAM_BOT_USERNAME`` is unset on the deployment, the API
 * returns ``deep_link=""`` and we render the raw token + manual instructions
 * instead — which still works, just clunkier.
 *
 * The ``chat_links`` query is invalidated on token issuance so freshly bound
 * chats appear without a manual refresh once the bot replies.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink, MessageSquare, Plus, Trash2 } from 'lucide-react';
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
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { ProjectSlug } from '@/lib/types';
import type { components } from '@/types/api';
import { CopyButton } from './api-keys-section';

type ChatLinkOut = components['schemas']['ChatLinkOut'];
type ChatLinkTokenOut = components['schemas']['ChatLinkTokenOut'];

interface Props {
	slug: ProjectSlug;
}

export function ChatLinksSection({ slug }: Props) {
	const { t } = useTranslation();
	const [token, setToken] = useState<ChatLinkTokenOut | null>(null);
	const [confirmRemove, setConfirmRemove] = useState<ChatLinkOut | null>(null);

	const links = useQuery({
		queryKey: queryKeys.projects.chatLinks(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/chat-links', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as ChatLinkOut[];
		},
		// Lightly poll — when the user clicks the deep link and adds the bot
		// to a group, the chat_link row appears server-side asynchronously.
		// 5 s strikes the balance between "feels alive" and "noisy".
		refetchInterval: token ? 5_000 : false,
	});

	const createToken = useMutation({
		mutationFn: async () => {
			const data = await unwrap(
				api.POST('/v1/projects/{slug}/chat-link-tokens', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as ChatLinkTokenOut;
		},
		onSuccess: async (data) => {
			setToken(data);
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.chatLinks(slug),
			});
		},
	});

	return (
		<Card>
			<CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
				<div className="space-y-1">
					<CardTitle className="flex items-center gap-2">
						<MessageSquare className="size-4" />
						{t('projects.chat_links.title')}
					</CardTitle>
					<CardDescription>{t('projects.chat_links.description')}</CardDescription>
				</div>
				<Button
					size="sm"
					onClick={() => createToken.mutate()}
					disabled={createToken.isPending}
				>
					<Plus className="size-4" />
					{createToken.isPending
						? t('common.saving')
						: t('projects.chat_links.generate')}
				</Button>
			</CardHeader>
			<CardContent className="space-y-4">
				{token && (
					<TokenAlert token={token} onDismiss={() => setToken(null)} />
				)}

				{links.isLoading ? (
					<Skeleton className="h-20 w-full" />
				) : links.data && links.data.length > 0 ? (
					<LinksTable rows={links.data} onRemove={setConfirmRemove} />
				) : (
					<p className="text-sm text-muted-foreground">
						{t('projects.chat_links.empty')}
					</p>
				)}
			</CardContent>

			<RemoveLinkDialog
				slug={slug}
				row={confirmRemove}
				onOpenChange={(open) => {
					if (!open) setConfirmRemove(null);
				}}
			/>
		</Card>
	);
}

function TokenAlert({
	token,
	onDismiss,
}: {
	token: ChatLinkTokenOut;
	onDismiss: () => void;
}) {
	const { t, i18n } = useTranslation();
	const fmt = new Intl.DateTimeFormat(i18n.language, { timeStyle: 'short' });
	const expires = fmt.format(new Date(token.expires_at));
	const hasDeepLink = !!token.deep_link;

	return (
		<Alert>
			<AlertTitle>
				{hasDeepLink
					? t('projects.chat_links.token_title')
					: t('projects.chat_links.token_title_no_bot')}
			</AlertTitle>
			<AlertDescription className="space-y-3">
				<p>
					{t('projects.chat_links.token_body', { expires })}
				</p>

				{hasDeepLink ? (
					<Button asChild className="w-full sm:w-auto">
						<a href={token.deep_link} target="_blank" rel="noreferrer">
							<ExternalLink className="size-4" />
							{t('projects.chat_links.open_telegram')}
						</a>
					</Button>
				) : (
					<>
						<div className="flex items-center gap-2">
							<Input
								readOnly
								value={token.token}
								className="font-mono text-xs"
								onFocus={(e) => e.currentTarget.select()}
							/>
							<CopyButton value={token.token} />
						</div>
						<p className="text-xs text-muted-foreground">
							{t('projects.chat_links.no_bot_hint')}
						</p>
					</>
				)}

				<div className="flex justify-end">
					<Button size="sm" variant="outline" onClick={onDismiss}>
						{t('common.close')}
					</Button>
				</div>
			</AlertDescription>
		</Alert>
	);
}

function LinksTable({
	rows,
	onRemove,
}: {
	rows: ChatLinkOut[];
	onRemove: (row: ChatLinkOut) => void;
}) {
	const { t, i18n } = useTranslation();
	const fmt = new Intl.DateTimeFormat(i18n.language, {
		dateStyle: 'medium',
	});
	return (
		<div className="overflow-x-auto rounded-md border">
			<table className="w-full text-sm">
				<thead className="bg-muted/50 text-muted-foreground">
					<tr>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.chat_links.col_chat')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.chat_links.col_platform')}
						</th>
						<th className="px-3 py-2 text-left font-medium">
							{t('projects.chat_links.col_added')}
						</th>
						<th className="px-3 py-2 text-right font-medium" />
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => (
						<tr key={row.id} className="border-t last:border-b-0 hover:bg-muted/30">
							<td className="px-3 py-2">
								<div className="font-medium">
									{row.title ?? t('projects.chat_links.untitled_chat')}
								</div>
								<div className="font-mono text-xs text-muted-foreground">
									{row.chat_id}
								</div>
							</td>
							<td className="px-3 py-2">
								<Badge variant="secondary">{row.platform}</Badge>
							</td>
							<td className="px-3 py-2 text-muted-foreground text-xs">
								{fmt.format(new Date(row.created_at))}
							</td>
							<td className="px-3 py-2 text-right">
								<Button
									size="sm"
									variant="ghost"
									onClick={() => onRemove(row)}
									aria-label={t('projects.chat_links.disconnect')}
								>
									<Trash2 className="size-4" />
								</Button>
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

function RemoveLinkDialog({
	slug,
	row,
	onOpenChange,
}: {
	slug: ProjectSlug;
	row: ChatLinkOut | null;
	onOpenChange: (open: boolean) => void;
}) {
	const { t } = useTranslation();

	const remove = useMutation({
		mutationFn: async () => {
			if (!row) return;
			await unwrap(
				api.DELETE('/v1/projects/{slug}/chat-links/{link_id}', {
					params: { path: { slug, link_id: row.id } },
				}),
			);
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.chatLinks(slug),
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
					<DialogTitle>{t('projects.chat_links.disconnect_title')}</DialogTitle>
					<DialogDescription>
						{t('projects.chat_links.disconnect_body', {
							chat: row?.title ?? row?.chat_id ?? '',
						})}
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
						{remove.isPending
							? t('common.saving')
							: t('projects.chat_links.disconnect')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

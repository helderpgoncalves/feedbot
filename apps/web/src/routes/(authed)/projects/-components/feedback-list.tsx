/**
 * Feedback list inside a project. Cookie-authed via
 * GET /v1/projects/{slug}/feedbacks (defined in feedbot-api/v1_feedbacks.py).
 *
 * Filter chips drive the `status` query param. Optimistic-UI status mutations
 * via PATCH /v1/projects/{slug}/feedbacks/{public_id}.
 *
 * Click a row to expand: shows the full body + the conversational state
 * (queued reply / user reply / internal note) and lets an admin queue
 * replies and notes via the same PATCH endpoint. The "request more info"
 * button is the canonical way to combine ``reply_to_user`` + status flip
 * back to ``triaged`` — same semantics the MCP tool exposes.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { ChevronDown, ChevronUp, MessageCircle, MessageSquare } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { ProjectSlug } from '@/lib/types';
import type { components } from '@/types/api';

type FeedbackOut = components['schemas']['FeedbackOut'];
type FeedbackStatus = components['schemas']['FeedbackStatus'];

const STATUSES = ['new', 'triaged', 'in_progress', 'done', 'wont_fix'] as const;
type FilterStatus = (typeof STATUSES)[number] | 'all';

export function FeedbackList({ slug }: { slug: ProjectSlug }) {
	const { t } = useTranslation();
	const [filter, setFilter] = useState<FilterStatus>('all');

	const feedbacks = useQuery({
		queryKey: [...queryKeys.projects.feedbacks(slug), filter],
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/feedbacks', {
					params: {
						path: { slug },
						query: filter === 'all' ? {} : { status: filter as FeedbackStatus },
					},
				}),
			);
			return data as unknown as FeedbackOut[];
		},
	});

	return (
		<div className="space-y-4">
			<div className="flex flex-wrap gap-2">
				<FilterChip
					label={t('feedbacks.filter.all')}
					active={filter === 'all'}
					onClick={() => setFilter('all')}
				/>
				{STATUSES.map((s) => (
					<FilterChip
						key={s}
						label={t(`feedbacks.filter.${s.replace('_', '_')}` as 'feedbacks.filter.new')}
						active={filter === s}
						onClick={() => setFilter(s)}
					/>
				))}
			</div>

			{feedbacks.isLoading ? (
				<div className="space-y-3">
					<Skeleton className="h-24 w-full" />
					<Skeleton className="h-24 w-full" />
				</div>
			) : (feedbacks.data ?? []).length === 0 ? (
				<Card>
					<CardContent className="py-10 text-center text-sm text-muted-foreground">
						{t('feedbacks.empty')}
					</CardContent>
				</Card>
			) : (
				<div className="space-y-3">
					{(feedbacks.data ?? []).map((fb) => (
						<FeedbackRow key={fb.id} fb={fb} slug={slug} />
					))}
				</div>
			)}
		</div>
	);
}

function FilterChip({
	label,
	active,
	onClick,
}: {
	label: string;
	active: boolean;
	onClick: () => void;
}) {
	return (
		<Button
			variant={active ? 'default' : 'outline'}
			size="sm"
			onClick={onClick}
			className="rounded-full"
		>
			{label}
		</Button>
	);
}

function FeedbackRow({ fb, slug }: { fb: FeedbackOut; slug: ProjectSlug }) {
	const [expanded, setExpanded] = useState(false);

	const update = useMutation({
		mutationFn: (newStatus: FeedbackStatus) =>
			unwrap(
				api.PATCH('/v1/projects/{slug}/feedbacks/{public_id}', {
					params: { path: { slug, public_id: fb.id } },
					body: { status: newStatus },
				}),
			),
		// Optimistic update — flip the status in cache immediately.
		onMutate: async (newStatus) => {
			const cachedKeys: ReadonlyArray<readonly unknown[]> = [
				[...queryKeys.projects.feedbacks(slug), 'all'],
				[...queryKeys.projects.feedbacks(slug), fb.status],
				[...queryKeys.projects.feedbacks(slug), newStatus],
			];
			await Promise.all(
				cachedKeys.map((key) => queryClient.cancelQueries({ queryKey: key })),
			);
			const snapshot = cachedKeys.map(
				(key) => [key, queryClient.getQueryData(key)] as const,
			);
			queryClient.setQueriesData<FeedbackOut[]>(
				{ queryKey: queryKeys.projects.feedbacks(slug) },
				(rows) =>
					rows?.map((r) => (r.id === fb.id ? { ...r, status: newStatus } : r)),
			);
			return { snapshot };
		},
		onError: (_err, _vars, ctx) => {
			ctx?.snapshot.forEach(([key, data]) => queryClient.setQueryData(key, data));
		},
		onSettled: () => {
			queryClient.invalidateQueries({
				queryKey: queryKeys.projects.feedbacks(slug),
			});
			queryClient.invalidateQueries({
				queryKey: queryKeys.projects.detail(slug),
			});
		},
	});

	return (
		<Card>
			<CardHeader
				className="gap-1 cursor-pointer select-none"
				onClick={() => setExpanded((v) => !v)}
				role="button"
				aria-expanded={expanded}
			>
				<div className="flex items-start justify-between gap-3">
					<div className="space-y-1 min-w-0">
						<CardTitle className="text-sm font-mono text-muted-foreground">
							{fb.id}
						</CardTitle>
						<div className="text-base font-medium leading-snug truncate">
							{fb.title}
						</div>
					</div>
					<div
						className="flex items-center gap-2 shrink-0"
						onClick={(e) => e.stopPropagation()}
					>
						<StatusBadge status={fb.status} />
						<DropdownMenu>
							<DropdownMenuTrigger asChild>
								<Button size="sm" variant="outline" disabled={update.isPending}>
									{update.isPending ? '…' : 'Status'}
								</Button>
							</DropdownMenuTrigger>
							<DropdownMenuContent align="end">
								{STATUSES.map((s) => (
									<DropdownMenuItem
										key={s}
										disabled={s === fb.status}
										onClick={() => update.mutate(s)}
									>
										{s.replace('_', ' ')}
									</DropdownMenuItem>
								))}
							</DropdownMenuContent>
						</DropdownMenu>
						{expanded ? (
							<ChevronUp className="size-4 text-muted-foreground" />
						) : (
							<ChevronDown className="size-4 text-muted-foreground" />
						)}
					</div>
				</div>
			</CardHeader>
			<CardContent
				className={
					expanded
						? 'space-y-4 text-sm'
						: 'text-sm text-muted-foreground line-clamp-3'
				}
			>
				{expanded ? (
					<FeedbackDetail fb={fb} slug={slug} />
				) : (
					fb.body
				)}
			</CardContent>
		</Card>
	);
}

function FeedbackDetail({ fb, slug }: { fb: FeedbackOut; slug: ProjectSlug }) {
	const { t, i18n } = useTranslation();
	const [reply, setReply] = useState(fb.reply_to_user ?? '');
	const [note, setNote] = useState('');

	const fmt = new Intl.DateTimeFormat(i18n.language, {
		dateStyle: 'medium',
		timeStyle: 'short',
	});

	const patch = useMutation({
		mutationFn: async (
			body: components['schemas']['FeedbackPatch'],
		): Promise<FeedbackOut> => {
			const data = await unwrap(
				api.PATCH('/v1/projects/{slug}/feedbacks/{public_id}', {
					params: { path: { slug, public_id: fb.id } },
					body,
				}),
			);
			return data as unknown as FeedbackOut;
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.feedbacks(slug),
			});
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.detail(slug),
			});
		},
	});

	const queueReply = () => {
		const trimmed = reply.trim();
		if (!trimmed) return;
		patch.mutate({ reply_to_user: trimmed });
	};

	const requestMoreInfo = () => {
		const trimmed = reply.trim();
		if (!trimmed) return;
		// Same semantics as the MCP `request_more_info` tool: reply + flip
		// status back to triaged so the loop is visibly open.
		patch.mutate({ reply_to_user: trimmed, status: 'triaged' });
	};

	const queueNote = () => {
		const trimmed = note.trim();
		if (!trimmed) return;
		patch.mutate({ note: trimmed });
		setNote('');
	};

	const replyDirty = (reply.trim() || '') !== (fb.reply_to_user ?? '').trim();

	return (
		<div className="space-y-5">
			{/* Body */}
			<div className="whitespace-pre-wrap break-words text-foreground">
				{fb.body}
			</div>

			{/* Existing user reply */}
			{fb.user_reply && (
				<div className="rounded-md border border-primary/30 bg-primary/5 p-3 space-y-1">
					<div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
						<MessageCircle className="size-3" />
						{t('feedbacks.detail.user_reply_label')}
					</div>
					<div className="whitespace-pre-wrap break-words text-foreground">
						{fb.user_reply}
					</div>
				</div>
			)}

			{/* Reply queue */}
			<div className="space-y-2">
				<div className="flex items-center justify-between">
					<label
						htmlFor={`reply-${fb.id}`}
						className="text-xs uppercase tracking-wider text-muted-foreground font-medium"
					>
						{t('feedbacks.detail.reply_label')}
					</label>
					{fb.reply_to_user && !replyDirty && (
						<span className="text-xs text-muted-foreground">
							{t('feedbacks.detail.reply_queued')}
						</span>
					)}
				</div>
				<Textarea
					id={`reply-${fb.id}`}
					value={reply}
					onChange={(e) => setReply(e.target.value)}
					placeholder={t('feedbacks.detail.reply_placeholder')}
					rows={3}
				/>
				<div className="flex flex-wrap gap-2">
					<Button
						size="sm"
						onClick={queueReply}
						disabled={!reply.trim() || !replyDirty || patch.isPending}
					>
						<MessageSquare className="size-4" />
						{t('feedbacks.detail.queue_reply')}
					</Button>
					<Button
						size="sm"
						variant="outline"
						onClick={requestMoreInfo}
						disabled={!reply.trim() || patch.isPending}
						title={t('feedbacks.detail.request_more_info_help')}
					>
						{t('feedbacks.detail.request_more_info')}
					</Button>
				</div>
			</div>

			{/* Internal note */}
			<div className="space-y-2">
				<label
					htmlFor={`note-${fb.id}`}
					className="text-xs uppercase tracking-wider text-muted-foreground font-medium"
				>
					{t('feedbacks.detail.note_label')}
				</label>
				<Textarea
					id={`note-${fb.id}`}
					value={note}
					onChange={(e) => setNote(e.target.value)}
					placeholder={t('feedbacks.detail.note_placeholder')}
					rows={2}
				/>
				<Button
					size="sm"
					variant="outline"
					onClick={queueNote}
					disabled={!note.trim() || patch.isPending}
				>
					{t('feedbacks.detail.append_note')}
				</Button>
				{fb.note && (
					<details className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
						<summary className="cursor-pointer">
							{t('feedbacks.detail.existing_notes')}
						</summary>
						<div className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">
							{fb.note}
						</div>
					</details>
				)}
			</div>

			{/* Footer metadata */}
			<div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
				<span>
					{t('feedbacks.detail.created_at', {
						date: fmt.format(new Date(fb.created_at)),
					})}
				</span>
				{fb.author_name && <span>· {fb.author_name}</span>}
				<span>· {fb.author_platform}</span>
				<span>· {fb.type}</span>
				<span>· {fb.severity}</span>
			</div>
		</div>
	);
}

function StatusBadge({ status }: { status: FeedbackStatus }) {
	const variant = (() => {
		switch (status) {
			case 'done':
				return 'success' as const;
			case 'in_progress':
				return 'warning' as const;
			case 'wont_fix':
				return 'secondary' as const;
			case 'triaged':
				return 'outline' as const;
			default:
				return 'default' as const;
		}
	})();
	return <Badge variant={variant}>{status.replace('_', ' ')}</Badge>;
}

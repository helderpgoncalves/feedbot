/**
 * Feedback list inside a project. Cookie-authed via
 * GET /v1/projects/{slug}/feedbacks (defined in feedbot-api/v1_feedbacks.py).
 *
 * Filter chips drive the `status` query param. Optimistic-UI status mutations
 * via PATCH /v1/projects/{slug}/feedbacks/{public_id}.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
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
			<CardHeader className="gap-1">
				<div className="flex items-start justify-between gap-3">
					<div className="space-y-1 min-w-0">
						<CardTitle className="text-sm font-mono text-muted-foreground">
							{fb.id}
						</CardTitle>
						<div className="text-base font-medium leading-snug truncate">
							{fb.title}
						</div>
					</div>
					<div className="flex items-center gap-2 shrink-0">
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
					</div>
				</div>
			</CardHeader>
			<CardContent className="text-sm text-muted-foreground line-clamp-3">
				{fb.body}
			</CardContent>
		</Card>
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

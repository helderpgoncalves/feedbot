/**
 * Single project detail. Loads the project + counts via /v1/projects/:slug
 * and renders the navigation tabs (feedback / members / api keys / chat
 * links / LLM). The list of feedbacks itself lands in F3.4.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { isAdmin, useMe } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import { projectSlug } from '@/lib/types';
import type { components } from '@/types/api';
import { ApiKeysSection } from './-components/api-keys-section';
import { ConnectMcpSection } from './-components/connect-mcp-section';
import { FeedbackList } from './-components/feedback-list';

type ApiKeyCreated = components['schemas']['ApiKeyCreated'];

type ProjectOut = components['schemas']['ProjectOut'];

export const Route = createFileRoute('/(authed)/projects/$slug')({
	loader: ({ context, params }) =>
		context.queryClient.ensureQueryData({
			queryKey: queryKeys.projects.detail(projectSlug(params.slug)),
			queryFn: async () => {
				const data = await unwrap(
					api.GET('/v1/projects/{slug}', {
						params: { path: { slug: params.slug } },
					}),
				);
				return data as unknown as ProjectOut;
			},
		}),
	component: ProjectDetailPage,
});

function ProjectDetailPage() {
	const { t } = useTranslation();
	const params = Route.useParams();
	const slug = projectSlug(params.slug);
	const { data: me } = useMe();
	const navigate = useNavigate();
	const [confirmDelete, setConfirmDelete] = useState(false);
	const [revealedKey, setRevealedKey] = useState<ApiKeyCreated | null>(null);

	const project = useQuery({
		queryKey: queryKeys.projects.detail(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as ProjectOut;
		},
	});

	const remove = useMutation({
		mutationFn: () =>
			unwrap(
				api.DELETE('/v1/projects/{slug}', {
					params: { path: { slug } },
				}),
			),
		onSuccess: async () => {
			await queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() });
			await queryClient.invalidateQueries({ queryKey: queryKeys.me() });
			await navigate({ to: '/projects', replace: true });
		},
	});

	if (project.isLoading) {
		return <ProjectDetailSkeleton />;
	}
	if (!project.data) return null;

	const canDelete = me ? isAdmin(me.user.role) : false;

	return (
		<div className="space-y-6">
			<div className="flex items-start justify-between gap-4">
				<div>
					<Button asChild variant="ghost" size="sm" className="-ml-3 mb-2">
						<Link to="/projects">
							<ChevronLeft className="size-4" />
							{t('common.back')}
						</Link>
					</Button>
					<h1 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
						{project.data.name}
						<span className="font-mono text-sm text-muted-foreground">
							{project.data.slug}
						</span>
					</h1>
				</div>
				<div className="flex gap-2">
					{canDelete && (
						<Button asChild variant="outline" size="sm">
							<Link to="/projects/$slug/llm" params={{ slug: project.data.slug }}>
								{t('projects.detail.llm')}
							</Link>
						</Button>
					)}
					{canDelete && (
						<Button
							variant="outline"
							size="sm"
							onClick={() => setConfirmDelete(true)}
						>
							<Trash2 className="size-4" />
							{t('common.delete')}
						</Button>
					)}
				</div>
			</div>

			<StatusGrid counts={project.data.feedback_count_by_status ?? {}} />

			<section className="space-y-3">
				<h2 className="text-lg font-semibold tracking-tight">
					{t('projects.detail.feedback')}
				</h2>
				<FeedbackList slug={slug} />
			</section>

			{canDelete && (
				<>
					<section className="space-y-3">
						<ApiKeysSection slug={slug} onKeyCreated={setRevealedKey} />
					</section>
					<section className="space-y-3">
						<ConnectMcpSection
							slug={slug}
							revealedSecret={revealedKey?.key ?? null}
						/>
					</section>
				</>
			)}

			<Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>
							{t('projects.delete_dialog.title', { name: project.data.name })}
						</DialogTitle>
						<DialogDescription>
							{t('projects.delete_dialog.body')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmDelete(false)}>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							onClick={() => remove.mutate()}
							disabled={remove.isPending}
						>
							{remove.isPending
								? t('common.saving')
								: t('projects.delete_dialog.confirm')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

function StatusGrid({ counts }: { counts: Record<string, number> }) {
	const entries = ['new', 'triaged', 'in_progress', 'done', 'wont_fix'] as const;
	return (
		<div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
			{entries.map((status) => (
				<Card key={status}>
					<CardHeader className="pb-2">
						<CardTitle className="text-xs uppercase tracking-wider text-muted-foreground font-medium">
							{status.replace('_', ' ')}
						</CardTitle>
					</CardHeader>
					<CardContent className="pt-0">
						<div className="text-2xl font-semibold">
							{counts[status] ?? 0}
						</div>
					</CardContent>
				</Card>
			))}
		</div>
	);
}

function ProjectDetailSkeleton() {
	return (
		<div className="space-y-6">
			<Skeleton className="h-10 w-2/3" />
			<div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
				{[0, 1, 2, 3, 4].map((k) => (
					<Skeleton key={k} className="h-24" />
				))}
			</div>
			<Skeleton className="h-40" />
		</div>
	);
}

export type { ProjectOut };

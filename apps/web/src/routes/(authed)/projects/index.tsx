/**
 * Projects list — entrypoint to every workspace area. Owner/admins see every
 * project in the tenant; members see only the ones they were added to.
 */

import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { UsageBanner } from '@/components/billing/usage-banner';
import { api, unwrap } from '@/lib/api';
import { isAdmin, useMe } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import type { components } from '@/types/api';
import { ProjectCreateDialog } from './-components/project-create-dialog';

type ProjectSummary = components['schemas']['ProjectSummary'];

export const Route = createFileRoute('/(authed)/projects/')({
	loader: ({ context }) =>
		context.queryClient.ensureQueryData({
			queryKey: queryKeys.projects.all(),
			queryFn: async () => {
				const data = await unwrap(api.GET('/v1/projects'));
				return data as unknown as ProjectSummary[];
			},
		}),
	component: ProjectsPage,
});

function ProjectsPage() {
	const { t } = useTranslation();
	const { data: me } = useMe();
	const [createOpen, setCreateOpen] = useState(false);

	const projects = useQuery({
		queryKey: queryKeys.projects.all(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/projects'));
			return data as unknown as ProjectSummary[];
		},
	});

	const canCreate = me ? isAdmin(me.user.role) : false;

	return (
		<div className="space-y-6">
			<UsageBanner />
			<div className="flex items-center justify-between gap-4">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">
						{t('projects.title')}
					</h1>
				</div>
				{canCreate && (
					<Button onClick={() => setCreateOpen(true)}>
						<Plus className="size-4" />
						{t('projects.new')}
					</Button>
				)}
			</div>

			{projects.isLoading ? (
				<ProjectListSkeleton />
			) : (projects.data ?? []).length === 0 ? (
				<EmptyState canCreate={canCreate} onCreate={() => setCreateOpen(true)} />
			) : (
				<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{(projects.data ?? []).map((p) => (
						<ProjectCard key={p.slug} project={p} />
					))}
				</div>
			)}

			<ProjectCreateDialog
				open={createOpen}
				onOpenChange={setCreateOpen}
				onCreated={async () => {
					await queryClient.invalidateQueries({
						queryKey: queryKeys.projects.all(),
					});
				}}
			/>
		</div>
	);
}

function ProjectCard({ project }: { project: ProjectSummary }) {
	return (
		<Link
			to="/projects/$slug"
			params={{ slug: project.slug }}
			className="block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl"
		>
			<Card className="h-full transition-colors hover:bg-accent/30">
				<CardHeader>
					<CardTitle className="text-base font-semibold">{project.name}</CardTitle>
					<CardDescription className="font-mono text-xs">
						{project.slug}
					</CardDescription>
				</CardHeader>
			</Card>
		</Link>
	);
}

function EmptyState({
	canCreate,
	onCreate,
}: {
	canCreate: boolean;
	onCreate: () => void;
}) {
	const { t } = useTranslation();
	return (
		<Card>
			<CardHeader className="text-center">
				<CardTitle>{t('projects.empty_title')}</CardTitle>
				<CardDescription>{t('projects.empty_subtitle')}</CardDescription>
			</CardHeader>
			{canCreate && (
				<CardContent className="flex justify-center">
					<Button onClick={onCreate}>
						<Plus className="size-4" />
						{t('projects.new')}
					</Button>
				</CardContent>
			)}
		</Card>
	);
}

function ProjectListSkeleton() {
	return (
		<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
			{[0, 1, 2].map((k) => (
				<Skeleton key={k} className="h-24 w-full" />
			))}
		</div>
	);
}

export type { ProjectSummary };

/**
 * F3.1 placeholder for the projects list. F3.3 replaces this with the real
 * list, create dialog, and delete confirmation flow.
 */

import { createFileRoute } from '@tanstack/react-router';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useMe } from '@/lib/auth';

export const Route = createFileRoute('/(authed)/projects')({
	component: ProjectsPlaceholder,
});

function ProjectsPlaceholder() {
	const { data: me } = useMe();
	if (!me) return null;
	return (
		<Card>
			<CardHeader>
				<CardTitle>Projects</CardTitle>
				<CardDescription>
					You're signed in as {me.user.email} ({me.user.role}). The real
					projects list lands in F3.3.
				</CardDescription>
			</CardHeader>
			<CardContent className="text-sm text-muted-foreground">
				{me.projects.length === 0
					? 'No projects yet.'
					: `${me.projects.length} project(s) loaded from /v1/me.`}
			</CardContent>
		</Card>
	);
}

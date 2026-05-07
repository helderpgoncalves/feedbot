import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/(authed)/team')({
	component: () => (
		<div className="text-sm text-muted-foreground">
			Team management lands in F3.5.
		</div>
	),
});

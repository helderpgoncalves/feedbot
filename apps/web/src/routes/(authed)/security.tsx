import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/(authed)/security')({
	component: () => (
		<div className="text-sm text-muted-foreground">
			Active sessions list lands in F3.2.
		</div>
	),
});

import { createFileRoute } from '@tanstack/react-router';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getConfig } from '@/lib/config';

export const Route = createFileRoute('/')({
	component: IndexPage,
});

function IndexPage() {
	const config = getConfig();

	return (
		<div className="min-h-screen flex items-center justify-center p-6">
			<Card className="max-w-2xl w-full">
				<CardHeader>
					<CardTitle className="text-2xl">{config.productName}</CardTitle>
					<CardDescription>
						Web app scaffolded. Real pages land in F3 onwards — this is the
						F1 deploy verification target.
					</CardDescription>
				</CardHeader>
				<CardContent className="space-y-4">
					<dl className="grid grid-cols-2 gap-3 text-sm">
						<dt className="text-muted-foreground">Deployment</dt>
						<dd className="font-mono">{config.deployment}</dd>
						<dt className="text-muted-foreground">Public URL</dt>
						<dd className="font-mono break-all">{config.publicUrl}</dd>
						<dt className="text-muted-foreground">Public sign-up</dt>
						<dd className="font-mono">{config.allowSignup ? 'enabled' : 'disabled'}</dd>
						<dt className="text-muted-foreground">Build</dt>
						<dd className="font-mono">{config.buildSha ?? 'dev'}</dd>
					</dl>
					<div className="flex gap-2 pt-2">
						<Button asChild>
							<a href="/login">Sign in</a>
						</Button>
						<Button variant="outline" asChild>
							<a
								href="https://github.com/helderpgoncalves/feedbot"
								target="_blank"
								rel="noreferrer"
							>
								GitHub
							</a>
						</Button>
					</div>
				</CardContent>
			</Card>
		</div>
	);
}

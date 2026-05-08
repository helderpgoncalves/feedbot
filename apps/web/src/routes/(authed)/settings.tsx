/**
 * Settings — top-level page for orchestrator-managed config
 * (owner-only, self-host only).
 *
 * For now the only section is "Email delivery" (I5). Subsequent
 * phases (I6: Telegram bot, I7: Domain & HTTPS, I8: System) wire
 * additional cards into this same grid. The page is a thin shell
 * that lists each section's status and links into the dedicated
 * subroute for editing — keeps each section self-contained and
 * mirrors the IA from the installer spec.
 *
 * Access control:
 *   - Anyone non-owner is redirected to /projects.
 *   - Cloud builds (deployment === 'cloud') are also redirected;
 *     the orchestrator endpoints 404 there and the page would be
 *     useless.
 */

import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { Mail, Send } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { getConfig } from '@/lib/config';
import { meQueryOptions } from '@/lib/auth';
import type { components } from '@/types/api';

type EmailConfigOut = components['schemas']['EmailConfigOut'];
type BotConfigOut = components['schemas']['BotConfigOut'];

export const Route = createFileRoute('/(authed)/settings')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		// ``beforeLoad`` of the parent (authed) layout already guarantees
		// ``me`` is non-null; the assertion here is for the type narrowing.
		if (!me) throw redirect({ to: '/login' });
		if (me.user.role !== 'owner') {
			throw redirect({ to: '/projects' });
		}
		if (getConfig().deployment === 'cloud') {
			throw redirect({ to: '/projects' });
		}
	},
	component: SettingsIndex,
});

function SettingsIndex() {
	const { t } = useTranslation();

	const email = useQuery({
		queryKey: ['admin', 'email', 'config'] as const,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/email/config'));
			return data as unknown as EmailConfigOut;
		},
	});

	const bot = useQuery({
		queryKey: ['admin', 'bot', 'config'] as const,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/bot/config'));
			return data as unknown as BotConfigOut;
		},
	});

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('settings.title')}
				</h1>
				<p className="text-sm text-muted-foreground mt-1">
					{t('settings.subtitle')}
				</p>
			</div>

			<div className="grid gap-4">
				<SectionCard
					icon={<Mail className="size-5" />}
					title={t('settings.email.title')}
					description={t('settings.email.subtitle')}
					status={
						email.isLoading ? (
							<Skeleton className="h-5 w-16" />
						) : email.data?.configured ? (
							<Badge variant="success">{t('settings.status.configured')}</Badge>
						) : (
							<Badge variant="secondary">
								{t('settings.status.not_configured')}
							</Badge>
						)
					}
					href="/settings/email"
					linkLabel={t('settings.email.manage')}
				/>
				<SectionCard
					icon={<Send className="size-5" />}
					title={t('settings.bot.title')}
					description={t('settings.bot.subtitle')}
					status={
						bot.isLoading ? (
							<Skeleton className="h-5 w-16" />
						) : bot.data?.configured ? (
							<Badge variant="success">{t('settings.status.configured')}</Badge>
						) : (
							<Badge variant="secondary">
								{t('settings.status.not_configured')}
							</Badge>
						)
					}
					href="/settings/bot"
					linkLabel={t('settings.bot.manage')}
				/>
			</div>
		</div>
	);
}

function SectionCard({
	icon,
	title,
	description,
	status,
	href,
	linkLabel,
}: {
	icon: React.ReactNode;
	title: string;
	description: string;
	status: React.ReactNode;
	href: string;
	linkLabel: string;
}) {
	return (
		<Card>
			<CardHeader className="gap-2">
				<div className="flex items-start justify-between gap-3">
					<div className="flex items-start gap-3">
						<div className="rounded-md border bg-muted/40 p-2 text-muted-foreground">
							{icon}
						</div>
						<div>
							<CardTitle className="text-base">{title}</CardTitle>
							<CardDescription>{description}</CardDescription>
						</div>
					</div>
					{status}
				</div>
			</CardHeader>
			<CardContent>
				<Button asChild variant="outline" size="sm">
					<Link to={href}>{linkLabel}</Link>
				</Button>
			</CardContent>
		</Card>
	);
}

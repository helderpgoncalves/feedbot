/**
 * /billing — owner-only billing dashboard.
 *
 * Surfaces the current plan + status, usage progress bars, and one-click
 * upgrade / portal redirects. Hidden entirely on self-host (the route
 * guard 404s when ``cfg.billingEnabled`` is false) so the SPA bundle for
 * a self-host install never even renders the section.
 *
 * Stripe owns the actual UI for managing the card, viewing invoices,
 * and cancelling — we just open the Customer Portal in a new tab.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { CreditCard, BadgeCheck, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import { meQueryOptions } from '@/lib/auth';
import {
	billingSubscriptionQueryOptions,
	createCheckoutSession,
	createPortalSession,
	type SubscriptionData,
} from '@/lib/billing';
import { getConfig } from '@/lib/config';

export const Route = createFileRoute('/(authed)/billing')({
	beforeLoad: async ({ context }) => {
		// Hidden entirely when billing is off (self-host, cloud free-beta).
		// The backend also 404s the data endpoint in those modes; this guard
		// just avoids a flash of the page chrome before that 404 lands.
		if (!getConfig().billingEnabled) {
			throw redirect({ to: '/projects' });
		}
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me || me.user.role !== 'owner') {
			throw redirect({ to: '/projects' });
		}
	},
	loader: async ({ context }) =>
		context.queryClient.ensureQueryData(billingSubscriptionQueryOptions()),
	component: BillingPage,
});

function BillingPage() {
	const { t } = useTranslation();
	const { data: sub } = useQuery(billingSubscriptionQueryOptions());

	const portal = useMutation({
		mutationFn: createPortalSession,
		onSuccess: ({ url }) => {
			// Stripe portal sessions are single-use and short-lived; opening in
			// the same tab is fine because the user expects to land on Stripe.
			window.location.assign(url);
		},
	});

	const checkout = useMutation({
		mutationFn: (plan: string) => createCheckoutSession(plan),
		onSuccess: ({ url }) => {
			window.location.assign(url);
		},
	});

	if (!sub) {
		return null;
	}

	const status = sub.status;
	const isPastDue = status === 'past_due' || status === 'unpaid';
	const isCanceled = status === 'canceled';

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('billing.title')}
				</h1>
				<p className="text-sm text-muted-foreground mt-1">
					{t('billing.subtitle')}
				</p>
			</div>

			{isPastDue && (
				<Alert variant="destructive">
					<TriangleAlert className="size-4" />
					<AlertTitle>{t('billing.past_due_title')}</AlertTitle>
					<AlertDescription>
						{t('billing.past_due_body')}
					</AlertDescription>
				</Alert>
			)}

			<Card>
				<CardHeader>
					<CardTitle className="flex items-center gap-2">
						<BadgeCheck className="size-5 text-emerald-600" />
						{sub.plan_display_name}
					</CardTitle>
					<CardDescription>
						{t(`billing.status.${status}`, {
							defaultValue: status,
						})}
						{sub.current_period_end &&
							` · ${t('billing.renews_on', {
								date: new Date(sub.current_period_end).toLocaleDateString(),
							})}`}
					</CardDescription>
				</CardHeader>
				<CardContent className="space-y-4">
					{sub.usage && sub.limits && (
						<div className="space-y-3">
							<UsageRow
								label={t('billing.usage.projects')}
								current={sub.usage.projects}
								limit={sub.limits.project_limit}
							/>
							<UsageRow
								label={t('billing.usage.feedback')}
								current={sub.usage.monthly_feedback}
								limit={sub.limits.monthly_feedback_limit}
							/>
							<UsageRow
								label={t('billing.usage.members')}
								current={sub.usage.members}
								limit={sub.limits.member_limit}
							/>
						</div>
					)}
					<div className="flex flex-wrap gap-2 pt-2">
						<Button
							variant="outline"
							onClick={() => portal.mutate()}
							disabled={portal.isPending}
						>
							<CreditCard className="mr-2 size-4" />
							{portal.isPending
								? t('common.loading')
								: t('billing.manage')}
						</Button>
						{!isCanceled && sub.plan !== 'team' && (
							<Button
								onClick={() =>
									checkout.mutate(sub.plan === 'free' ? 'pro' : 'team')
								}
								disabled={checkout.isPending}
							>
								{checkout.isPending
									? t('common.loading')
									: sub.plan === 'free'
										? t('billing.upgrade_to_pro')
										: t('billing.upgrade_to_team')}
							</Button>
						)}
					</div>
				</CardContent>
			</Card>

			<p className="text-xs text-muted-foreground">
				{t('billing.questions_prefix')}{' '}
				<Link to="/projects" className="underline-offset-4 hover:underline">
					{t('billing.questions_link')}
				</Link>
			</p>
		</div>
	);
}

interface UsageRowProps {
	label: string;
	current: number;
	limit: number | null;
}

function UsageRow({ label, current, limit }: UsageRowProps) {
	const isUnlimited = limit === null;
	const ratio = isUnlimited ? 0 : Math.min(1, current / Math.max(1, limit));
	const overLimit = !isUnlimited && current >= (limit ?? 0);
	const nearLimit = !overLimit && ratio >= 0.8;
	const barColor = overLimit
		? 'bg-destructive'
		: nearLimit
			? 'bg-amber-500'
			: 'bg-emerald-500';

	return (
		<div>
			<div className="flex items-baseline justify-between text-sm">
				<span className="text-muted-foreground">{label}</span>
				<span className="font-mono tabular-nums">
					{current.toLocaleString()}
					{!isUnlimited && (
						<span className="text-muted-foreground"> / {limit?.toLocaleString()}</span>
					)}
				</span>
			</div>
			<div className="mt-1 h-1.5 rounded-full bg-muted overflow-hidden">
				<div
					className={`h-full transition-all ${barColor}`}
					style={{ width: `${Math.max(2, ratio * 100)}%` }}
				/>
			</div>
		</div>
	);
}

export type { SubscriptionData };

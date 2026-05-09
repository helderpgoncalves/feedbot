/**
 * UsageBanner — surfaces near-limit / over-limit conditions on top of
 * the projects pages. Renders ``null`` whenever billingEnabled is off,
 * so importing this component is safe in self-host code paths too.
 *
 * Logic:
 *   - any single quota at >=100% of its limit  >>>  red over-limit banner
 *     (with upgrade CTA pointing at /billing).
 *   - any single quota at >=80%  >>>  yellow heads-up banner.
 *   - everything else  >>>  null.
 *
 * The data source is the same /v1/billing/subscription endpoint the
 * /billing page uses, so we share TanStack Query cache (one round trip
 * per app session, refreshed every 30s).
 */

import { Link } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TriangleAlert, Sparkles } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
	billingSubscriptionQueryOptions,
	type SubscriptionData,
} from '@/lib/billing';
import { getConfig } from '@/lib/config';

interface QuotaState {
	kind: 'project' | 'feedback' | 'member';
	current: number;
	limit: number;
	ratio: number;
}

function _highestRatio(sub: SubscriptionData): QuotaState | null {
	if (!sub.limits || !sub.usage) return null;
	const candidates: QuotaState[] = [];
	if (sub.limits.project_limit !== null) {
		candidates.push({
			kind: 'project',
			current: sub.usage.projects,
			limit: sub.limits.project_limit,
			ratio: sub.usage.projects / Math.max(1, sub.limits.project_limit),
		});
	}
	if (sub.limits.monthly_feedback_limit !== null) {
		candidates.push({
			kind: 'feedback',
			current: sub.usage.monthly_feedback,
			limit: sub.limits.monthly_feedback_limit,
			ratio:
				sub.usage.monthly_feedback /
				Math.max(1, sub.limits.monthly_feedback_limit),
		});
	}
	if (sub.limits.member_limit !== null) {
		candidates.push({
			kind: 'member',
			current: sub.usage.members,
			limit: sub.limits.member_limit,
			ratio: sub.usage.members / Math.max(1, sub.limits.member_limit),
		});
	}
	if (candidates.length === 0) return null;
	return candidates.reduce((best, q) => (q.ratio > best.ratio ? q : best));
}

export function UsageBanner() {
	const { t } = useTranslation();
	const cfg = getConfig();
	// We must always call hooks unconditionally; the query is cheap
	// (cached, no network on cache hit), but we tell it to skip the
	// fetch entirely when billing is off.
	const { data: sub } = useQuery({
		...billingSubscriptionQueryOptions(),
		enabled: cfg.billingEnabled,
	});
	if (!cfg.billingEnabled || !sub) return null;

	const worst = _highestRatio(sub);
	if (!worst) return null;

	if (worst.ratio >= 1) {
		return (
			<Alert variant="destructive">
				<TriangleAlert className="size-4" />
				<AlertTitle>
					{t(`billing.banner.over_${worst.kind}_title`, {
						current: worst.current,
						limit: worst.limit,
					})}
				</AlertTitle>
				<AlertDescription className="flex items-center justify-between gap-4">
					<span>{t(`billing.banner.over_${worst.kind}_body`)}</span>
					<Button asChild size="sm" variant="outline">
						<Link to="/billing">{t('billing.banner.upgrade_cta')}</Link>
					</Button>
				</AlertDescription>
			</Alert>
		);
	}

	if (worst.ratio >= 0.8) {
		return (
			<Alert>
				<Sparkles className="size-4" />
				<AlertTitle>
					{t(`billing.banner.near_${worst.kind}_title`, {
						current: worst.current,
						limit: worst.limit,
					})}
				</AlertTitle>
				<AlertDescription className="flex items-center justify-between gap-4">
					<span>{t(`billing.banner.near_${worst.kind}_body`)}</span>
					<Button asChild size="sm" variant="outline">
						<Link to="/billing">{t('billing.banner.upgrade_cta')}</Link>
					</Button>
				</AlertDescription>
			</Alert>
		);
	}

	return null;
}

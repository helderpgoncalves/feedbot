/**
 * Billing query + mutations.
 *
 * Mirrors what feedbot_api/routers/v1_billing.py exposes:
 *   GET  /v1/billing/subscription  — plan + usage snapshot
 *   POST /v1/billing/portal        — Stripe Customer Portal redirect
 *   POST /v1/billing/checkout      — Stripe Checkout session redirect
 *
 * The openapi-typescript generator is run against a live API
 * (`pnpm gen:api`) and lags the source for new routes. Until that's
 * regenerated against the C2 schema we type the responses by hand —
 * the shapes are tiny and pinned by the backend Pydantic models.
 */

import { queryOptions } from '@tanstack/react-query';
import { ApiError } from './api';

export interface SubscriptionLimits {
	project_limit: number | null;
	monthly_feedback_limit: number | null;
	member_limit: number | null;
}

export interface SubscriptionUsage {
	projects: number;
	monthly_feedback: number;
	members: number;
}

export interface SubscriptionData {
	plan: string;
	plan_display_name: string;
	status: string;
	current_period_end: string | null;
	trial_end: string | null;
	limits: SubscriptionLimits | null;
	usage: SubscriptionUsage | null;
	cancel_at_period_end: boolean;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
	const res = await fetch(url, {
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json' },
		...init,
	});
	if (!res.ok) {
		let body: unknown = null;
		try {
			body = await res.json();
		} catch {
			// Non-JSON body — fall through to status text.
		}
		const detail =
			(body as { detail?: string } | null)?.detail ?? res.statusText;
		throw new ApiError(res.status, detail, body);
	}
	return (await res.json()) as T;
}

export const billingSubscriptionQueryOptions = () =>
	queryOptions({
		queryKey: ['billing', 'subscription'] as const,
		queryFn: () => fetchJson<SubscriptionData>('/api/v1/billing/subscription'),
		staleTime: 30_000,
	});

export async function createPortalSession(): Promise<{ url: string }> {
	return fetchJson<{ url: string }>('/api/v1/billing/portal', {
		method: 'POST',
	});
}

export async function createCheckoutSession(
	plan: string,
): Promise<{ url: string }> {
	return fetchJson<{ url: string }>('/api/v1/billing/checkout', {
		method: 'POST',
		body: JSON.stringify({ plan }),
	});
}

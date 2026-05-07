/**
 * Single TanStack QueryClient instance shared by the whole app.
 *
 * Defaults are tuned for a dashboard:
 *  - 30-second staleTime: data feels fresh without thrashing the network.
 *  - 5-minute gcTime: components re-mounting (e.g. via TanStack Router
 *    navigation) don't pay a refetch.
 *  - No retries on 401/403/404 — those are not transient.
 *  - One automatic retry on everything else (network blips, 5xx).
 *  - Mutations never retry; the user is in the loop and gets a toast.
 *
 * A global mutation `onError` lifts the boring toast plumbing out of every
 * page. Components that want custom UX still override it locally.
 */

import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError } from './api';
import { normalizeError } from './errors';

const isAuthMissing = (error: unknown) =>
	error instanceof ApiError && error.status === 401;

export const queryClient = new QueryClient({
	queryCache: new QueryCache({
		onError: (error, query) => {
			// Auth errors are handled by the route loader / guard; don't yell.
			if (isAuthMissing(error)) return;
			// If the query asked to suppress global toasts, respect it.
			if (query.meta && (query.meta as { silent?: boolean }).silent) return;
			toast.error(normalizeError(error).message);
		},
	}),
	mutationCache: new MutationCache({
		onError: (error, _vars, _ctx, mutation) => {
			if (mutation.meta && (mutation.meta as { silent?: boolean }).silent) return;
			toast.error(normalizeError(error).message);
		},
	}),
	defaultOptions: {
		queries: {
			staleTime: 30_000,
			gcTime: 5 * 60_000,
			retry: (failureCount, error) => {
				const status = (error as { status?: number } | null)?.status;
				if (status === 401 || status === 403 || status === 404) return false;
				return failureCount < 2;
			},
			refetchOnWindowFocus: true,
		},
		mutations: {
			retry: false,
		},
	},
});

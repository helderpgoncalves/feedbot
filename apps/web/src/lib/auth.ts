/**
 * Auth queries + helpers.
 *
 * Identity comes from `GET /v1/me`. Components consume it through
 * {@link useMe}; route loaders prefetch via {@link meQueryOptions}.
 */

import { queryOptions, useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './query-keys';

export interface MeData {
	user: {
		id: number;
		email: string;
		role: 'owner' | 'admin' | 'member';
		tenant_id: number;
	};
	tenant: {
		id: number;
		name: string;
	};
	projects: ReadonlyArray<{
		slug: string;
		name: string;
		created_at: string;
	}>;
	is_setup_complete: boolean;
}

/** Shared queryOptions so both `useMe` and route loaders use the same key + fn. */
export const meQueryOptions = () =>
	queryOptions({
		queryKey: queryKeys.me(),
		queryFn: async (): Promise<MeData | null> => {
			const { data, error, response } = await api.GET('/v1/me');
			if (response.status === 401) return null; // not signed in — graceful nil
			if (!response.ok) {
				const detail =
					(error as { detail?: string } | undefined)?.detail ?? response.statusText;
				throw new Error(`/v1/me failed: ${detail}`);
			}
			return data as unknown as MeData;
		},
		// `me` is the most stable thing we fetch; let it stay cache-warm longer.
		staleTime: 60_000,
		// 401 on /me is "not signed in" not "broken"; tell the global toast handler
		// not to bother.
		meta: { silent: true },
	});

/** React hook for components that need to know who's signed in. */
export function useMe() {
	return useQuery(meQueryOptions());
}

export function isAdmin(role: MeData['user']['role']): boolean {
	return role === 'owner' || role === 'admin';
}

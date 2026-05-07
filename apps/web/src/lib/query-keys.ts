/**
 * Hierarchical TanStack Query keys.
 *
 * Each helper returns an array literal so TanStack Query can compare keys by
 * structural equality, and so callers get autocomplete on related operations:
 *
 *   queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() })
 *   queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(slug) })
 *
 * The `all()` form is the parent of every more specific key under it, so a
 * single invalidate will refetch list AND detail. Use the more specific form
 * when you only need to refetch one.
 */

import type { ProjectSlug } from './types';

export const queryKeys = {
	me: () => ['me'] as const,

	auth: {
		sessions: () => ['auth', 'sessions'] as const,
	},

	llmProviders: () => ['llm', 'providers'] as const,

	tenant: {
		users: () => ['tenant', 'users'] as const,
	},

	invites: {
		all: () => ['invites'] as const,
		preview: (token: string) => ['invites', 'preview', token] as const,
	},

	projects: {
		all: () => ['projects'] as const,
		detail: (slug: ProjectSlug) => ['projects', slug] as const,

		members: (slug: ProjectSlug) => ['projects', slug, 'members'] as const,
		apiKeys: (slug: ProjectSlug) => ['projects', slug, 'api-keys'] as const,
		chatLinks: (slug: ProjectSlug) => ['projects', slug, 'chat-links'] as const,

		llmSettings: (slug: ProjectSlug) => ['projects', slug, 'llm', 'settings'] as const,
		llmCalls: (slug: ProjectSlug) => ['projects', slug, 'llm', 'calls'] as const,

		feedbacks: (slug: ProjectSlug) => ['projects', slug, 'feedbacks'] as const,
	},
} as const;

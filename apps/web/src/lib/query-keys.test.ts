/**
 * Tests pin the shape of query keys. Changing a key without realising it
 * silently breaks every cache invalidation, so we lock the contract.
 */

import { describe, expect, it } from 'vitest';
import { queryKeys } from './query-keys';
import { projectSlug } from './types';

describe('queryKeys', () => {
	it('me() is a flat array', () => {
		expect(queryKeys.me()).toEqual(['me']);
	});

	it('projects.detail(slug) extends projects.all()', () => {
		const all = queryKeys.projects.all();
		const detail = queryKeys.projects.detail(projectSlug('demo'));
		expect(detail.slice(0, all.length)).toEqual(all);
	});

	it('every project sub-key is prefixed with the slug', () => {
		const slug = projectSlug('demo');
		expect(queryKeys.projects.feedbacks(slug)).toEqual(['projects', slug, 'feedbacks']);
		expect(queryKeys.projects.apiKeys(slug)).toEqual(['projects', slug, 'api-keys']);
		expect(queryKeys.projects.llmSettings(slug)).toEqual([
			'projects',
			slug,
			'llm',
			'settings',
		]);
	});

	it('invites.preview(token) carries the token', () => {
		expect(queryKeys.invites.preview('abc')).toEqual(['invites', 'preview', 'abc']);
	});
});

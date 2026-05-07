/**
 * Tests for branded primitive helpers. They're tiny but worth pinning so a
 * future refactor doesn't accidentally remove the runtime values.
 */

import { describe, expect, it } from 'vitest';
import {
	apiKeyId,
	feedbackId,
	inviteId,
	projectId,
	projectSlug,
	sessionId,
	tenantId,
	userId,
} from './types';

describe('branded type helpers', () => {
	it('pass through numeric ids without transformation', () => {
		expect(userId(7)).toBe(7);
		expect(projectId(1)).toBe(1);
		expect(apiKeyId(99)).toBe(99);
		expect(inviteId(3)).toBe(3);
		expect(tenantId(42)).toBe(42);
	});

	it('pass through string ids without transformation', () => {
		expect(projectSlug('demo')).toBe('demo');
		expect(feedbackId('FB-A3F2')).toBe('FB-A3F2');
		expect(sessionId('opaquetoken')).toBe('opaquetoken');
	});
});

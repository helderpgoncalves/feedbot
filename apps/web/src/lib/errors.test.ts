/**
 * Tests for the error normalization layer. Critical because every error UI
 * (toasts, inline form messages) flows through `normalizeError`.
 */

import { describe, expect, it } from 'vitest';
import { ApiError } from './api';
import { normalizeError } from './errors';

describe('normalizeError', () => {
	it('translates known status codes via i18next', () => {
		const result = normalizeError(new ApiError(401, 'login required', null));
		expect(result.message).toBe('You need to sign in.');
		expect(result.status).toBe(401);
	});

	it('falls back to ApiError.message for unknown codes', () => {
		const result = normalizeError(new ApiError(418, "I'm a teapot", null));
		expect(result.message).toBe("I'm a teapot");
		expect(result.status).toBe(418);
	});

	it('extracts FastAPI 422 field errors into a flat path map', () => {
		const body = {
			detail: [
				{ loc: ['body', 'email'], msg: 'value is not a valid email address' },
				{ loc: ['body', 'role'], msg: 'String should match pattern' },
			],
		};
		const result = normalizeError(new ApiError(422, 'unprocessable', body));
		expect(result.fieldErrors).toEqual({
			email: ['value is not a valid email address'],
			role: ['String should match pattern'],
		});
	});

	it('handles network failures', () => {
		const err = new TypeError('Failed to fetch');
		const result = normalizeError(err);
		expect(result.message).toBe('Network error — check your connection.');
	});

	it('falls back to a generic message for unknown values', () => {
		const result = normalizeError({ wat: true });
		expect(result.message).toBe('Something went wrong. Try again in a moment.');
	});
});

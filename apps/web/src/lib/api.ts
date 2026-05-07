/**
 * Single typed API client used everywhere.
 *
 * Cookies are httpOnly + SameSite=Strict and the request flows through the
 * same-origin Caddy proxy at /api/* in production (or Vite's dev proxy
 * locally) — no CORS, no manual `credentials: 'include'`.
 */

import createClient from 'openapi-fetch';
import type { paths } from '@/types/api';

export const api = createClient<paths>({
	baseUrl: '/api',
	credentials: 'same-origin',
});

/**
 * Narrow openapi-fetch failures into something we can match on with
 * `instanceof` and pattern-match by status code.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly body: unknown;
	constructor(status: number, message: string, body: unknown) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.body = body;
	}
}

/**
 * Convert an openapi-fetch result into either the data or a thrown
 * {@link ApiError}. Use this in TanStack Query queryFn / mutationFn so the
 * error handlers (toasts, retries) get a single, structured exception type.
 */
export async function unwrap<T>(
	promise: Promise<{
		data?: T;
		error?: unknown;
		response: Response;
	}>,
): Promise<T> {
	const { data, error, response } = await promise;
	if (!response.ok) {
		const message =
			(error as { detail?: string } | undefined)?.detail ??
			`Request failed: ${response.status} ${response.statusText}`;
		throw new ApiError(response.status, message, error);
	}
	if (data === undefined) {
		// 204 No Content — return whatever the caller's generic widened to.
		return undefined as T;
	}
	return data;
}

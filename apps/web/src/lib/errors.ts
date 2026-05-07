/**
 * Centralised error → human message translation.
 *
 * Every user-visible error in the app should pass through `messageForError`
 * so the copy stays consistent and i18n-ready. Component-level handlers
 * pick the message and render it in a toast or inline.
 */

import i18next from '@/i18n';
import { ApiError } from './api';

export interface FieldErrors {
	/** Map of field path -> array of messages, suitable to feed react-hook-form. */
	[fieldPath: string]: string[];
}

export interface NormalizedError {
	/** Top-level message safe to show as a toast. */
	message: string;
	/** Field-level errors, only populated for 422 responses. */
	fieldErrors?: FieldErrors;
	/** Original status, useful for callers that want to branch on it. */
	status?: number;
}

/**
 * Convert any thrown value into a normalised, displayable error.
 *
 * Special-cases:
 *   - {@link ApiError} 401 → translated "you need to sign in"
 *   - {@link ApiError} 422 → field-by-field errors derived from FastAPI's body
 *   - generic `TypeError: Failed to fetch` → translated "network error"
 */
export function normalizeError(err: unknown): NormalizedError {
	if (err instanceof ApiError) {
		const errorByStatus = i18next.t(`errors.${err.status}`, {
			defaultValue: err.message,
		});

		// FastAPI 422 body shape: { detail: [{ loc: [...], msg: ... }, ...] }
		if (err.status === 422 && err.body && typeof err.body === 'object') {
			const detail = (err.body as { detail?: unknown }).detail;
			if (Array.isArray(detail)) {
				const fieldErrors: FieldErrors = {};
				for (const item of detail) {
					if (
						item &&
						typeof item === 'object' &&
						Array.isArray((item as { loc?: unknown[] }).loc)
					) {
						const loc = (item as { loc: unknown[] }).loc;
						const msg =
							typeof (item as { msg?: unknown }).msg === 'string'
								? ((item as { msg: string }).msg)
								: i18next.t('common.unknown_error');
						// Drop the `body` prefix that FastAPI adds; we only care about
						// the field path inside the request body.
						const path = loc.filter((p) => p !== 'body').join('.');
						(fieldErrors[path] ??= []).push(msg);
					}
				}
				if (Object.keys(fieldErrors).length > 0) {
					return { message: errorByStatus, fieldErrors, status: err.status };
				}
			}
		}

		return { message: errorByStatus, status: err.status };
	}

	if (err instanceof TypeError && /fetch|network/i.test(err.message)) {
		return { message: i18next.t('common.network_error') };
	}

	if (err instanceof Error) {
		return { message: err.message || i18next.t('common.unknown_error') };
	}

	return { message: i18next.t('common.unknown_error') };
}

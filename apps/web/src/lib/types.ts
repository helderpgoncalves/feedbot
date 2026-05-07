/**
 * Branded primitive types — small TS trick that prevents accidentally mixing
 * IDs from different domains.
 *
 *   const u: UserId = userId(42)
 *   const s: ProjectSlug = projectSlug('demo')
 *   takesUser(s)  // ❌ compile error — ProjectSlug is not assignable to UserId
 *
 * Branded values are still primitives at runtime; the brand exists only in
 * the type system. Wrap with the casting helpers below at the API boundary.
 */

declare const __brand: unique symbol;

export type Brand<T, B extends string> = T & { readonly [__brand]: B };

export type UserId = Brand<number, 'UserId'>;
export type ProjectId = Brand<number, 'ProjectId'>;
export type ProjectSlug = Brand<string, 'ProjectSlug'>;
export type FeedbackId = Brand<string, 'FeedbackId'>;
export type ApiKeyId = Brand<number, 'ApiKeyId'>;
export type SessionId = Brand<string, 'SessionId'>;
export type InviteId = Brand<number, 'InviteId'>;
export type TenantId = Brand<number, 'TenantId'>;

export const userId = (n: number): UserId => n as UserId;
export const projectId = (n: number): ProjectId => n as ProjectId;
export const projectSlug = (s: string): ProjectSlug => s as ProjectSlug;
export const feedbackId = (s: string): FeedbackId => s as FeedbackId;
export const apiKeyId = (n: number): ApiKeyId => n as ApiKeyId;
export const sessionId = (s: string): SessionId => s as SessionId;
export const inviteId = (n: number): InviteId => n as InviteId;
export const tenantId = (n: number): TenantId => n as TenantId;

/**
 * Roles, mirrored from the API. The string values match `feedbot_core.models.Role`
 * verbatim so we can pass them straight through.
 */
export type Role = 'owner' | 'admin' | 'member';

/**
 * Feedback statuses, ditto.
 */
export type FeedbackStatus = 'new' | 'triaged' | 'in_progress' | 'done' | 'wontfix';

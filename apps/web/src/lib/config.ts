/**
 * Runtime configuration loaded from /config.json before the app boots.
 *
 * Self-hosters edit the JSON via the Caddy entrypoint env vars in
 * docker-compose.yml; the same Docker image works for everyone.
 */

export interface RuntimeConfig {
	/** Human-friendly product name shown in the UI. */
	productName: string;
	/** Base URL of this web app — used in emails / share links. Defaults to current origin. */
	publicUrl: string;
	/**
	 * Public URL of the MCP endpoint, suitable for pasting into any MCP-compatible
	 * client (Claude Code, Claude Desktop, Cursor, Windsurf, …).
	 *
	 * Source order at container start (Caddyfile templating):
	 *   1. ``FEEDBOT_MCP_PUBLIC_URL`` if set — for split-domain deploys where
	 *      the API and SPA live on different hosts.
	 *   2. ``${FEEDBOT_PUBLIC_URL}/mcp/`` if FEEDBOT_PUBLIC_URL is set — the
	 *      same-origin Caddy proxy reaches /mcp/ on the API container.
	 *   3. Empty string — the SPA falls back to ``${window.location.origin}/mcp/``
	 *      at render time so a fresh self-host with zero env vars Just Works.
	 */
	mcpPublicUrl: string;
	/** Optional: Telegram bot username (without @). Powers the "connect Telegram" deep link. */
	telegramBotUsername: string | null;
	/** Whether public sign-up is allowed. Cloud = true. Self-host = false (default). */
	allowSignup: boolean;
	/** Cloud-only: shows the upgrade banner / plan name in the UI. */
	deployment: 'self-host' | 'cloud';
	/** Optional commit SHA shown in footer for traceability. */
	buildSha: string | null;
}

const FALLBACK_CONFIG: RuntimeConfig = {
	productName: 'Feedbot',
	publicUrl: typeof window !== 'undefined' ? window.location.origin : '',
	mcpPublicUrl: '',
	telegramBotUsername: null,
	allowSignup: false,
	deployment: 'self-host',
	buildSha: null,
};

/**
 * Resolve the MCP server URL the user should paste into their MCP client,
 * applying the fallback chain documented on ``RuntimeConfig.mcpPublicUrl``.
 *
 * Always returns a value with a trailing slash so concatenations never produce
 * ``//``. Returns an empty string only if there's no window (SSR/test) and
 * no config has been loaded.
 */
export function resolveMcpUrl(cfg: RuntimeConfig): string {
	if (cfg.mcpPublicUrl) return _withTrailingSlash(cfg.mcpPublicUrl);
	if (cfg.publicUrl) return _withTrailingSlash(`${_stripTrailingSlash(cfg.publicUrl)}/mcp/`);
	if (typeof window !== 'undefined') return `${window.location.origin}/mcp/`;
	return '';
}

function _stripTrailingSlash(s: string): string {
	return s.endsWith('/') ? s.slice(0, -1) : s;
}

function _withTrailingSlash(s: string): string {
	return s.endsWith('/') ? s : `${s}/`;
}

let cached: RuntimeConfig | null = null;

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
	if (cached) return cached;
	try {
		const res = await fetch('/config.json', { cache: 'no-store' });
		if (!res.ok) throw new Error(`config.json HTTP ${res.status}`);
		const raw = (await res.json()) as Partial<RuntimeConfig>;
		cached = { ...FALLBACK_CONFIG, ...raw };
	} catch (err) {
		// Failing to load /config.json is not fatal — we boot with defaults
		// and log so self-hosters notice during initial setup.
		console.warn('[config] /config.json not available, using defaults', err);
		cached = FALLBACK_CONFIG;
	}
	return cached;
}

export function getConfig(): RuntimeConfig {
	if (!cached) {
		throw new Error(
			'getConfig() called before loadRuntimeConfig() resolved — wait for the boot promise.',
		);
	}
	return cached;
}

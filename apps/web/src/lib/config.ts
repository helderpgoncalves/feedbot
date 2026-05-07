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
	telegramBotUsername: null,
	allowSignup: false,
	deployment: 'self-host',
	buildSha: null,
};

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

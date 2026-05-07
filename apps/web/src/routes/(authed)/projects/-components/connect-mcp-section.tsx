/**
 * "Connect via MCP" panel.
 *
 * Generates ready-to-paste configuration for any MCP-compatible client
 * (Claude Code, Claude Desktop, Cursor, Windsurf, Zed, Continue, …) using
 * the deployment's *own* domain (read from runtime ``/config.json``) and an
 * API key the admin selects from the project's keys (or has just created).
 *
 * Why three tabs:
 *   - **CLI**: ``claude mcp add --transport http …`` for users wiring up
 *     Claude Code from the terminal. Mirrors Anthropic's "Option 1: Add a
 *     remote HTTP server" example verbatim.
 *   - **JSON**: ``.mcp.json`` (Claude Code / Cursor / Windsurf) and
 *     ``claude_desktop_config.json`` (Claude Desktop) share the same
 *     ``mcpServers`` shape — one snippet covers all four.
 *   - **Generic**: prose for any other MCP client — server URL + Bearer
 *     header described independently of any vendor's config file.
 *
 * The actual key (``fbk_live_…``) is shown verbatim only in the period
 * immediately after creation (the parent passes ``revealedSecret``). For
 * pre-existing keys we render a ``<YOUR_API_KEY>`` placeholder so the secret
 * stays one-time-only.
 */

import { useQuery } from '@tanstack/react-query';
import { ExternalLink, Server, Terminal, FileJson, Code2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api, unwrap } from '@/lib/api';
import { getConfig, resolveMcpUrl } from '@/lib/config';
import { queryKeys } from '@/lib/query-keys';
import type { ProjectSlug } from '@/lib/types';
import type { components } from '@/types/api';
import { CopyButton } from './api-keys-section';

type ApiKeyOut = components['schemas']['ApiKeyOut'];

const SECRET_PLACEHOLDER = '<YOUR_API_KEY>';

interface Props {
	slug: ProjectSlug;
	/** Server name to use inside ``mcpServers`` and as the CLI argument.
	 *  Defaults to ``feedbot``; per-project we use the slug to disambiguate
	 *  when one user wires multiple Feedbot projects to one Claude Code. */
	serverName?: string;
	/** Optional: the freshly-created secret, only available immediately after
	 *  ``POST /api-keys``. When present, pre-fills the snippet so the user
	 *  doesn't have to copy-paste twice. Falls back to ``<YOUR_API_KEY>``. */
	revealedSecret?: string | null;
}

export function ConnectMcpSection({ slug, serverName, revealedSecret }: Props) {
	const { t } = useTranslation();
	const cfg = getConfig();
	const mcpUrl = resolveMcpUrl(cfg);
	const name = serverName ?? `feedbot-${slug}`;

	const keys = useQuery({
		queryKey: queryKeys.projects.apiKeys(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/api-keys', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as ApiKeyOut[];
		},
	});

	const activeKeys = useMemo(
		() => (keys.data ?? []).filter((k) => !k.revoked_at),
		[keys.data],
	);

	const [selectedPrefix, setSelectedPrefix] = useState<string>('');

	// If we have a revealed secret OR exactly one active key, the secret /
	// prefix to show is implicit. Otherwise the user picks one.
	const effectiveSecret = revealedSecret ?? SECRET_PLACEHOLDER;
	const effectiveLabel = useMemo(() => {
		if (revealedSecret) {
			const prefix = revealedSecret.slice(0, 16);
			return activeKeys.find((k) => prefix.startsWith(k.prefix))?.label ?? '';
		}
		if (selectedPrefix) {
			return activeKeys.find((k) => k.prefix === selectedPrefix)?.label ?? '';
		}
		return activeKeys.length === 1 ? activeKeys[0].label : '';
	}, [revealedSecret, selectedPrefix, activeKeys]);

	const cliSnippet = buildCliSnippet({ name, url: mcpUrl, secret: effectiveSecret });
	const jsonSnippet = buildJsonSnippet({ name, url: mcpUrl, secret: effectiveSecret });
	const curlSnippet = buildCurlSnippet({ url: mcpUrl, secret: effectiveSecret });

	return (
		<Card>
			<CardHeader>
				<CardTitle className="flex items-center gap-2">
					<Server className="size-4" />
					{t('projects.mcp.title')}
				</CardTitle>
				<CardDescription>{t('projects.mcp.description')}</CardDescription>
			</CardHeader>
			<CardContent className="space-y-4">
				<ConnectionDetails url={mcpUrl} />

				{!revealedSecret && activeKeys.length === 0 && (
					<Alert>
						<AlertTitle>{t('projects.mcp.no_keys_title')}</AlertTitle>
						<AlertDescription>{t('projects.mcp.no_keys_body')}</AlertDescription>
					</Alert>
				)}

				{!revealedSecret && activeKeys.length > 1 && (
					<KeyPicker
						keys={activeKeys}
						selected={selectedPrefix}
						onChange={setSelectedPrefix}
					/>
				)}

				{revealedSecret && (
					<p className="text-sm text-muted-foreground">
						{t('projects.mcp.using_revealed', { label: effectiveLabel })}
					</p>
				)}

				{!revealedSecret && (
					<p className="text-xs text-muted-foreground">
						{t('projects.mcp.placeholder_help')}
					</p>
				)}

				<Tabs defaultValue="cli">
					<TabsList>
						<TabsTrigger value="cli">
							<Terminal className="size-4" />
							{t('projects.mcp.tab_cli')}
						</TabsTrigger>
						<TabsTrigger value="json">
							<FileJson className="size-4" />
							{t('projects.mcp.tab_json')}
						</TabsTrigger>
						<TabsTrigger value="generic">
							<Code2 className="size-4" />
							{t('projects.mcp.tab_generic')}
						</TabsTrigger>
					</TabsList>

					<TabsContent value="cli">
						<SnippetBlock
							label={t('projects.mcp.cli_help')}
							value={cliSnippet}
						/>
					</TabsContent>

					<TabsContent value="json">
						<SnippetBlock
							label={t('projects.mcp.json_help')}
							value={jsonSnippet}
							language="json"
						/>
					</TabsContent>

					<TabsContent value="generic">
						<GenericInstructions url={mcpUrl} secret={effectiveSecret} />
					</TabsContent>
				</Tabs>

				<details className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
					<summary className="cursor-pointer font-medium">
						{t('projects.mcp.curl_summary')}
					</summary>
					<div className="mt-3">
						<SnippetBlock value={curlSnippet} />
					</div>
				</details>

				<p className="text-xs text-muted-foreground">
					{t('projects.mcp.docs_hint')}{' '}
					<a
						href="https://code.claude.com/docs/en/mcp#authenticate-with-remote-mcp-servers"
						target="_blank"
						rel="noreferrer"
						className="inline-flex items-center gap-1 underline underline-offset-2"
					>
						{t('projects.mcp.docs_link')}
						<ExternalLink className="size-3" />
					</a>
				</p>
			</CardContent>
		</Card>
	);
}

// ─── Connection details ──────────────────────────────────────────────────────

function ConnectionDetails({ url }: { url: string }) {
	const { t } = useTranslation();
	return (
		<div className="grid gap-3 sm:grid-cols-2">
			<div className="space-y-1">
				<Label className="text-xs uppercase tracking-wider text-muted-foreground">
					{t('projects.mcp.field_url')}
				</Label>
				<div className="flex items-center gap-2">
					<Input readOnly value={url} className="font-mono text-xs" />
					<CopyButton value={url} />
				</div>
			</div>
			<div className="space-y-1">
				<Label className="text-xs uppercase tracking-wider text-muted-foreground">
					{t('projects.mcp.field_transport')}
				</Label>
				<Input readOnly value="Streamable HTTP" className="text-xs" />
			</div>
		</div>
	);
}

// ─── Key picker (>1 active keys) ────────────────────────────────────────────

function KeyPicker({
	keys,
	selected,
	onChange,
}: {
	keys: ApiKeyOut[];
	selected: string;
	onChange: (prefix: string) => void;
}) {
	const { t } = useTranslation();
	return (
		<div className="space-y-2">
			<Label>{t('projects.mcp.key_picker_label')}</Label>
			<Select value={selected} onValueChange={onChange}>
				<SelectTrigger>
					<SelectValue placeholder={t('projects.mcp.key_picker_placeholder')} />
				</SelectTrigger>
				<SelectContent>
					{keys.map((k) => (
						<SelectItem key={k.id} value={k.prefix}>
							<span className="font-mono text-xs">{k.prefix}…</span>{' '}
							<span className="text-muted-foreground">{k.label}</span>
						</SelectItem>
					))}
				</SelectContent>
			</Select>
		</div>
	);
}

// ─── Snippet block ───────────────────────────────────────────────────────────

function SnippetBlock({
	value,
	label,
	language,
}: {
	value: string;
	label?: string;
	language?: 'shell' | 'json';
}) {
	return (
		<div className="space-y-2">
			{label && <p className="text-xs text-muted-foreground">{label}</p>}
			<div className="relative">
				<pre
					className="overflow-x-auto rounded-md border bg-muted/40 p-3 pr-14 text-xs font-mono leading-relaxed"
					data-lang={language ?? 'shell'}
				>
					<code>{value}</code>
				</pre>
				<div className="absolute right-2 top-2">
					<CopyButton value={value} />
				</div>
			</div>
		</div>
	);
}

function GenericInstructions({ url, secret }: { url: string; secret: string }) {
	const { t } = useTranslation();
	return (
		<div className="space-y-3 text-sm">
			<p>{t('projects.mcp.generic_intro')}</p>
			<ul className="list-disc space-y-2 pl-5">
				<li>
					<span className="text-muted-foreground">{t('projects.mcp.field_url')}:</span>{' '}
					<code className="font-mono text-xs">{url}</code>
				</li>
				<li>
					<span className="text-muted-foreground">
						{t('projects.mcp.field_transport')}:
					</span>{' '}
					<code className="font-mono text-xs">Streamable HTTP</code>
				</li>
				<li>
					<span className="text-muted-foreground">
						{t('projects.mcp.field_header')}:
					</span>{' '}
					<code className="font-mono text-xs">Authorization: Bearer {secret}</code>
				</li>
			</ul>
		</div>
	);
}

// ─── Snippet builders ────────────────────────────────────────────────────────

function buildCliSnippet({
	name,
	url,
	secret,
}: {
	name: string;
	url: string;
	secret: string;
}): string {
	return [
		`claude mcp add --transport http ${name} ${url} \\`,
		`  --header "Authorization: Bearer ${secret}"`,
	].join('\n');
}

function buildJsonSnippet({
	name,
	url,
	secret,
}: {
	name: string;
	url: string;
	secret: string;
}): string {
	const obj = {
		mcpServers: {
			[name]: {
				type: 'http',
				url,
				headers: {
					Authorization: `Bearer ${secret}`,
				},
			},
		},
	};
	return JSON.stringify(obj, null, 2);
}

function buildCurlSnippet({ url, secret }: { url: string; secret: string }): string {
	return [
		`curl -s -X POST ${JSON.stringify(url)} \\`,
		`  -H ${JSON.stringify(`Authorization: Bearer ${secret}`)} \\`,
		`  -H "Content-Type: application/json" \\`,
		`  -H "Accept: application/json, text/event-stream" \\`,
		`  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'`,
	].join('\n');
}

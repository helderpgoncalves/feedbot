/**
 * Settings → System.
 *
 * Three tabs:
 *
 *   - Status: live ``docker compose ps`` snapshot + version,
 *     refreshes every 30s. Per-service Restart button calls
 *     POST /restart with that service name; "Restart all" omits
 *     the field.
 *   - Auto-start: toggles systemd / launchd unit registration.
 *     Falls back to copy-paste manual instructions on
 *     unsupported platforms.
 *   - Telemetry: opt-in flag persisted on instance_config.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { ChevronLeft, Download, RefreshCw, RotateCw } from 'lucide-react';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
	Tabs,
	TabsContent,
	TabsList,
	TabsTrigger,
} from '@/components/ui/tabs';
import { api, unwrap } from '@/lib/api';
import { getConfig } from '@/lib/config';
import { meQueryOptions } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import type { components } from '@/types/api';

type SystemStatusOut = components['schemas']['SystemStatusOut'];
type AutostartStatusOut = components['schemas']['AutostartStatusOut'];
type TelemetryConfigOut = components['schemas']['TelemetryConfigOut'];
type UpdatesOut = components['schemas']['UpdatesOut'];
type BackupOut = components['schemas']['BackupOut'];

const STATUS_KEY = ['admin', 'system', 'status'] as const;
const AUTOSTART_KEY = ['admin', 'system', 'autostart'] as const;
const TELEMETRY_KEY = ['admin', 'system', 'telemetry'] as const;
const UPDATES_KEY = ['admin', 'system', 'updates'] as const;
const BACKUPS_KEY = ['admin', 'system', 'backups'] as const;

export const Route = createFileRoute('/(authed)/settings/system')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) throw redirect({ to: '/login' });
		if (me.user.role !== 'owner') throw redirect({ to: '/projects' });
		if (getConfig().deployment === 'cloud') {
			throw redirect({ to: '/projects' });
		}
	},
	component: SystemSettingsPage,
});

function SystemSettingsPage() {
	const { t } = useTranslation();

	return (
		<div className="space-y-6">
			<div>
				<Button asChild variant="ghost" size="sm" className="mb-2">
					<Link to="/settings">
						<ChevronLeft className="mr-1 size-4" />
						{t('settings.back')}
					</Link>
				</Button>
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('settings.system.title')}
				</h1>
				<p className="text-sm text-muted-foreground mt-1">
					{t('settings.system.subtitle')}
				</p>
			</div>

			<Tabs defaultValue="status">
				<TabsList>
					<TabsTrigger value="status">
						{t('settings.system.tabs.status')}
					</TabsTrigger>
					<TabsTrigger value="updates">
						{t('settings.system.tabs.updates')}
					</TabsTrigger>
					<TabsTrigger value="backups">
						{t('settings.system.tabs.backups')}
					</TabsTrigger>
					<TabsTrigger value="autostart">
						{t('settings.system.tabs.autostart')}
					</TabsTrigger>
					<TabsTrigger value="telemetry">
						{t('settings.system.tabs.telemetry')}
					</TabsTrigger>
				</TabsList>
				<TabsContent value="status" className="mt-4">
					<StatusTab />
				</TabsContent>
				<TabsContent value="updates" className="mt-4">
					<UpdatesTab />
				</TabsContent>
				<TabsContent value="backups" className="mt-4">
					<BackupsTab />
				</TabsContent>
				<TabsContent value="autostart" className="mt-4">
					<AutostartTab />
				</TabsContent>
				<TabsContent value="telemetry" className="mt-4">
					<TelemetryTab />
				</TabsContent>
			</Tabs>
		</div>
	);
}

// ── Status ──────────────────────────────────────────────────────────

function StatusTab() {
	const { t } = useTranslation();

	const status = useQuery({
		queryKey: STATUS_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/system/status'));
			return data as unknown as SystemStatusOut;
		},
		refetchInterval: 30_000,
	});

	const restart = useMutation({
		mutationFn: async (service: string | null) => {
			await unwrap(
				api.POST('/v1/admin/system/restart', {
					body: { service },
				}),
			);
		},
		onSuccess: (_, service) => {
			toast.success(
				t('settings.system.restart_toast', { target: service ?? 'all' }),
			);
			queryClient.invalidateQueries({ queryKey: STATUS_KEY });
		},
		onError: (err) => {
			toast.error(
				t('settings.system.restart_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	if (status.isLoading || !status.data) {
		return <Skeleton className="h-40 w-full" />;
	}

	return (
		<div className="space-y-4">
			<Card>
				<CardHeader className="flex flex-row items-start justify-between gap-3">
					<div>
						<CardTitle>{t('settings.system.status.title')}</CardTitle>
						<CardDescription>
							{t('settings.system.status.subtitle', {
								version: status.data.version,
							})}
						</CardDescription>
					</div>
					<div className="flex items-center gap-2">
						{status.data.ok ? (
							<Badge variant="success">
								{t('settings.system.status.ok')}
							</Badge>
						) : (
							<Badge variant="destructive">
								{t('settings.system.status.degraded')}
							</Badge>
						)}
						<Button
							variant="outline"
							size="sm"
							onClick={() =>
								queryClient.invalidateQueries({ queryKey: STATUS_KEY })
							}
						>
							<RefreshCw className="size-4" />
						</Button>
						<Button
							variant="outline"
							size="sm"
							onClick={() => restart.mutate(null)}
							disabled={restart.isPending}
						>
							<RotateCw className="mr-1 size-4" />
							{t('settings.system.restart_all')}
						</Button>
					</div>
				</CardHeader>
				<CardContent>
					{status.data.error && (
						<Alert variant="destructive" className="mb-4">
							<AlertTitle>{t('settings.system.status.error_title')}</AlertTitle>
							<AlertDescription className="font-mono text-xs break-all">
								{status.data.error}
							</AlertDescription>
						</Alert>
					)}
					{status.data.services.length === 0 ? (
						<p className="text-sm text-muted-foreground">
							{t('settings.system.status.empty')}
						</p>
					) : (
						<ul className="divide-y">
							{status.data.services.map((s) => (
								<li
									key={s.name}
									className="py-2 flex items-center justify-between gap-3"
								>
									<div className="min-w-0">
										<div className="font-medium">{s.name}</div>
										<div className="text-xs text-muted-foreground font-mono truncate">
											{s.image ?? '—'} · {s.status ?? s.state}
										</div>
									</div>
									<div className="flex items-center gap-2">
										<Badge
											variant={s.state === 'running' ? 'success' : 'secondary'}
										>
											{s.state}
										</Badge>
										<Button
											variant="ghost"
											size="sm"
											onClick={() => restart.mutate(s.name)}
											disabled={restart.isPending}
										>
											<RotateCw className="size-4" />
										</Button>
									</div>
								</li>
							))}
						</ul>
					)}
				</CardContent>
			</Card>
		</div>
	);
}

// ── Auto-start ─────────────────────────────────────────────────────

function AutostartTab() {
	const { t } = useTranslation();

	const cfg = useQuery({
		queryKey: AUTOSTART_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/system/autostart'));
			return data as unknown as AutostartStatusOut;
		},
	});

	const toggle = useMutation({
		mutationFn: async (enabled: boolean) => {
			const data = await unwrap(
				api.POST('/v1/admin/system/autostart', {
					body: { enabled },
				}),
			);
			return data as unknown as AutostartStatusOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(AUTOSTART_KEY, data);
			toast.success(
				data.enabled
					? t('settings.system.autostart.enabled_toast')
					: t('settings.system.autostart.disabled_toast'),
			);
		},
		onError: (err) => {
			toast.error(
				t('settings.system.autostart.failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	if (cfg.isLoading || !cfg.data) return <Skeleton className="h-40 w-full" />;

	const supported =
		cfg.data.platform === 'linux-systemd' ||
		cfg.data.platform === 'macos-launchd';

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t('settings.system.autostart.title')}</CardTitle>
				<CardDescription>
					{t('settings.system.autostart.subtitle', {
						platform: cfg.data.platform,
					})}
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-4">
				{supported ? (
					<div className="flex items-center justify-between gap-3 rounded-md border p-3">
						<div>
							<div className="font-medium">
								{t('settings.system.autostart.enable_label')}
							</div>
							<div className="text-xs text-muted-foreground font-mono break-all">
								{cfg.data.unit_path ?? '—'}
							</div>
						</div>
						<Switch
							checked={cfg.data.enabled}
							onCheckedChange={(v) => toggle.mutate(v)}
							disabled={toggle.isPending}
						/>
					</div>
				) : (
					<Alert>
						<AlertTitle>
							{t('settings.system.autostart.unsupported_title')}
						</AlertTitle>
						<AlertDescription>
							<p>{t('settings.system.autostart.unsupported_body')}</p>
							{cfg.data.manual_instructions && (
								<pre className="mt-3 rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
									{cfg.data.manual_instructions}
								</pre>
							)}
						</AlertDescription>
					</Alert>
				)}
			</CardContent>
		</Card>
	);
}

// ── Telemetry ──────────────────────────────────────────────────────

function TelemetryTab() {
	const { t } = useTranslation();

	const cfg = useQuery({
		queryKey: TELEMETRY_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/system/telemetry'));
			return data as unknown as TelemetryConfigOut;
		},
	});

	const toggle = useMutation({
		mutationFn: async (enabled: boolean) => {
			const data = await unwrap(
				api.POST('/v1/admin/system/telemetry', { body: { enabled } }),
			);
			return data as unknown as TelemetryConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(TELEMETRY_KEY, data);
			toast.success(
				data.enabled
					? t('settings.system.telemetry.enabled_toast')
					: t('settings.system.telemetry.disabled_toast'),
			);
		},
	});

	if (cfg.isLoading || !cfg.data) return <Skeleton className="h-32 w-full" />;

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t('settings.system.telemetry.title')}</CardTitle>
				<CardDescription>
					{t('settings.system.telemetry.subtitle')}
				</CardDescription>
			</CardHeader>
			<CardContent>
				<div className="flex items-center justify-between gap-3 rounded-md border p-3">
					<div className="text-sm">
						{t('settings.system.telemetry.label')}
					</div>
					<Switch
						checked={cfg.data.enabled}
						onCheckedChange={(v) => toggle.mutate(v)}
						disabled={toggle.isPending}
					/>
				</div>
				<p className="text-xs text-muted-foreground mt-3">
					{t('settings.system.telemetry.privacy_note')}
				</p>
			</CardContent>
		</Card>
	);
}

// ── Updates ────────────────────────────────────────────────────────

function UpdatesTab() {
	const { t } = useTranslation();
	const [confirmApply, setConfirmApply] = useState(false);

	const info = useQuery({
		queryKey: UPDATES_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/system/updates'));
			return data as unknown as UpdatesOut;
		},
		// GHCR is rate-limited; refresh every 5 min rather than every poll.
		staleTime: 5 * 60_000,
	});

	const apply = useMutation({
		mutationFn: async () => {
			await unwrap(api.POST('/v1/admin/system/updates/apply'));
		},
		onSuccess: () => {
			setConfirmApply(false);
			toast.success(t('settings.system.updates.applied_toast'));
			queryClient.invalidateQueries({ queryKey: UPDATES_KEY });
			queryClient.invalidateQueries({ queryKey: STATUS_KEY });
		},
		onError: (err) => {
			toast.error(
				t('settings.system.updates.apply_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	if (info.isLoading || !info.data) {
		return <Skeleton className="h-32 w-full" />;
	}

	return (
		<Card>
			<CardHeader className="flex flex-row items-start justify-between gap-3">
				<div>
					<CardTitle>{t('settings.system.updates.title')}</CardTitle>
					<CardDescription>
						{t('settings.system.updates.subtitle')}
					</CardDescription>
				</div>
				{info.data.available ? (
					<Badge variant="success">
						{t('settings.system.updates.available')}
					</Badge>
				) : info.data.error ? (
					<Badge variant="secondary">
						{t('settings.system.updates.unavailable')}
					</Badge>
				) : (
					<Badge variant="secondary">
						{t('settings.system.updates.up_to_date')}
					</Badge>
				)}
			</CardHeader>
			<CardContent className="space-y-4">
				<div className="grid grid-cols-2 gap-2 text-sm rounded-md border p-3">
					<div className="text-muted-foreground">
						{t('settings.system.updates.current')}
					</div>
					<div className="font-mono">{info.data.current}</div>
					<div className="text-muted-foreground">
						{t('settings.system.updates.latest')}
					</div>
					<div className="font-mono">{info.data.latest ?? '—'}</div>
				</div>

				{info.data.error && (
					<Alert>
						<AlertTitle>{t('settings.system.updates.check_failed')}</AlertTitle>
						<AlertDescription className="font-mono text-xs break-all">
							{info.data.error}
						</AlertDescription>
					</Alert>
				)}

				<div className="flex flex-wrap items-center gap-3">
					<Button
						variant="outline"
						size="sm"
						onClick={() =>
							queryClient.invalidateQueries({ queryKey: UPDATES_KEY })
						}
					>
						<RefreshCw className="mr-1 size-4" />
						{t('settings.system.updates.recheck')}
					</Button>
					<Button
						onClick={() => setConfirmApply(true)}
						disabled={!info.data.available || apply.isPending}
					>
						{apply.isPending
							? t('settings.system.updates.applying')
							: t('settings.system.updates.apply')}
					</Button>
				</div>
			</CardContent>

			<Dialog open={confirmApply} onOpenChange={setConfirmApply}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('settings.system.updates.confirm_title')}</DialogTitle>
						<DialogDescription>
							{t('settings.system.updates.confirm_body')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmApply(false)}>
							{t('common.cancel')}
						</Button>
						<Button
							onClick={() => apply.mutate()}
							disabled={apply.isPending}
						>
							{apply.isPending
								? t('settings.system.updates.applying')
								: t('settings.system.updates.confirm_action')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</Card>
	);
}

// ── Backups ────────────────────────────────────────────────────────

function BackupsTab() {
	const { t, i18n } = useTranslation();

	const list = useQuery({
		queryKey: BACKUPS_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/system/backups'));
			return data as unknown as BackupOut[];
		},
	});

	const create = useMutation({
		mutationFn: async () => {
			const data = await unwrap(api.POST('/v1/admin/system/backups'));
			return data as unknown as BackupOut;
		},
		onSuccess: (data) => {
			toast.success(
				t('settings.system.backups.created_toast', { filename: data.filename }),
			);
			queryClient.invalidateQueries({ queryKey: BACKUPS_KEY });
		},
		onError: (err) => {
			toast.error(
				t('settings.system.backups.create_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	const fmt = (iso: string) =>
		new Date(iso).toLocaleString(i18n.language, {
			year: 'numeric',
			month: 'short',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit',
		});

	const human = (bytes: number) => {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
		return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
	};

	if (list.isLoading) return <Skeleton className="h-40 w-full" />;

	return (
		<Card>
			<CardHeader className="flex flex-row items-start justify-between gap-3">
				<div>
					<CardTitle>{t('settings.system.backups.title')}</CardTitle>
					<CardDescription>
						{t('settings.system.backups.subtitle')}
					</CardDescription>
				</div>
				<Button
					onClick={() => create.mutate()}
					disabled={create.isPending}
				>
					{create.isPending
						? t('settings.system.backups.creating')
						: t('settings.system.backups.create')}
				</Button>
			</CardHeader>
			<CardContent>
				{(list.data ?? []).length === 0 ? (
					<p className="text-sm text-muted-foreground">
						{t('settings.system.backups.empty')}
					</p>
				) : (
					<ul className="divide-y">
						{(list.data ?? []).map((b) => (
							<li
								key={b.filename}
								className="py-2 flex items-center justify-between gap-3"
							>
								<div className="min-w-0">
									<div className="font-mono text-sm truncate">
										{b.filename}
									</div>
									<div className="text-xs text-muted-foreground">
										{fmt(b.created_at)} · {human(b.size_bytes)}
									</div>
								</div>
								<Button asChild variant="outline" size="sm">
									<a
										href={`/api/v1/admin/system/backups/${encodeURIComponent(
											b.filename,
										)}/download`}
									>
										<Download className="mr-1 size-4" />
										{t('settings.system.backups.download')}
									</a>
								</Button>
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}

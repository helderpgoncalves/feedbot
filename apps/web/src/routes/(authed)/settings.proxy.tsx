/**
 * Settings → Domain & HTTPS.
 *
 * Two-phase UX matching the backend:
 *
 *   1. Pre-flight DNS check (button) → POST /dns-check returns
 *      whether ``domain`` resolves to this server's outbound IP.
 *      A failed match is a *warning*, not a block — DNS
 *      propagation lag is common; the user can proceed.
 *
 *   2. Save → POST /config writes to the DB and asks Caddy to
 *      load a TLS-enabled config. Caddy starts the ACME flow
 *      asynchronously; we then poll GET /status every 3s until
 *      ``configured`` flips to true (cert provisioned) or an
 *      error string appears.
 *
 * Remove → DELETE /config reverts to the IP-only config and
 * clears the persisted domain.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';
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
import {
	Form,
	FormControl,
	FormDescription,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { getConfig } from '@/lib/config';
import { meQueryOptions } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import type { components } from '@/types/api';

type ProxyConfigOut = components['schemas']['ProxyConfigOut'];
type ProxyStatusOut = components['schemas']['ProxyStatusOut'];
type ProxyDnsCheckOut = components['schemas']['ProxyDnsCheckOut'];

const schema = z.object({
	domain: z.string().min(3).max(253),
	letsencrypt_email: z.email(),
});
type FormValues = z.infer<typeof schema>;

const CFG_KEY = ['admin', 'proxy', 'config'] as const;
const STATUS_KEY = ['admin', 'proxy', 'status'] as const;

export const Route = createFileRoute('/(authed)/settings/proxy')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) throw redirect({ to: '/login' });
		if (me.user.role !== 'owner') throw redirect({ to: '/projects' });
		if (getConfig().deployment === 'cloud') {
			throw redirect({ to: '/projects' });
		}
	},
	component: ProxySettingsPage,
});

function ProxySettingsPage() {
	const { t } = useTranslation();
	const [confirmRemove, setConfirmRemove] = useState(false);
	const [dnsCheck, setDnsCheck] = useState<ProxyDnsCheckOut | null>(null);
	// Polling activates after a successful save and stops once the
	// Caddy ``configured`` flag flips to true or an error appears.
	const [polling, setPolling] = useState(false);

	const cfg = useQuery({
		queryKey: CFG_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/proxy/config'));
			return data as unknown as ProxyConfigOut;
		},
	});

	const status = useQuery({
		queryKey: STATUS_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/proxy/status'));
			return data as unknown as ProxyStatusOut;
		},
		// Only poll while we know a save is propagating; otherwise the
		// query just returns a cheap snapshot once on mount.
		refetchInterval: polling ? 3000 : false,
		enabled: !!cfg.data?.configured || polling,
	});

	// Stop polling once Caddy reports the policy is loaded or hands
	// us back an error string the user needs to read.
	useEffect(() => {
		if (!polling) return;
		if (status.data?.configured || status.data?.error) {
			setPolling(false);
		}
	}, [polling, status.data]);

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		defaultValues: { domain: '', letsencrypt_email: '' },
	});

	useEffect(() => {
		if (!cfg.data) return;
		form.reset({
			domain: cfg.data.domain ?? '',
			letsencrypt_email: cfg.data.letsencrypt_email ?? '',
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [cfg.data]);

	const checkDns = useMutation({
		mutationFn: async (domain: string) => {
			const data = await unwrap(
				api.POST('/v1/admin/proxy/dns-check', { body: { domain } }),
			);
			return data as unknown as ProxyDnsCheckOut;
		},
		onSuccess: (data) => setDnsCheck(data),
	});

	const save = useMutation({
		mutationFn: async (values: FormValues) => {
			const data = await unwrap(
				api.POST('/v1/admin/proxy/config', {
					body: {
						domain: values.domain.trim().toLowerCase(),
						letsencrypt_email: values.letsencrypt_email.trim(),
					},
				}),
			);
			return data as unknown as ProxyConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(CFG_KEY, data);
			setPolling(true);
			toast.success(t('settings.proxy.saved_toast'));
		},
		onError: (err) => {
			toast.error(
				t('settings.proxy.save_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	const remove = useMutation({
		mutationFn: async () => {
			const data = await unwrap(api.DELETE('/v1/admin/proxy/config'));
			return data as unknown as ProxyConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(CFG_KEY, data);
			setConfirmRemove(false);
			setPolling(false);
			setDnsCheck(null);
			toast.success(t('settings.proxy.removed_toast'));
		},
	});

	if (cfg.isLoading || !cfg.data) {
		return (
			<div className="space-y-6">
				<Skeleton className="h-8 w-48" />
				<Skeleton className="h-72 w-full" />
			</div>
		);
	}

	const provisioning =
		polling && !status.data?.error && !status.data?.configured;
	const provisioned = !!status.data?.configured;

	return (
		<div className="space-y-6">
			<div>
				<Button asChild variant="ghost" size="sm" className="mb-2">
					<Link to="/settings">
						<ChevronLeft className="mr-1 size-4" />
						{t('settings.back')}
					</Link>
				</Button>
				<div className="flex items-start justify-between gap-3">
					<div>
						<h1 className="text-2xl font-semibold tracking-tight">
							{t('settings.proxy.title')}
						</h1>
						<p className="text-sm text-muted-foreground mt-1">
							{t('settings.proxy.subtitle')}
						</p>
					</div>
					{provisioning ? (
						<Badge variant="secondary">
							{t('settings.proxy.status.applying')}
						</Badge>
					) : status.data?.error ? (
						<Badge variant="destructive">
							{t('settings.proxy.status.error')}
						</Badge>
					) : provisioned ? (
						<Badge variant="success">
							{t('settings.proxy.status.ok')}
						</Badge>
					) : (
						<Badge variant="secondary">
							{t('settings.status.not_configured')}
						</Badge>
					)}
				</div>
			</div>

			{!cfg.data.configured && (
				<Alert>
					<AlertTitle>{t('settings.proxy.empty_title')}</AlertTitle>
					<AlertDescription>
						{t('settings.proxy.empty_body')}
					</AlertDescription>
				</Alert>
			)}

			{provisioned && cfg.data.domain && (
				<Alert>
					<AlertTitle>
						{t('settings.proxy.live_title', { domain: cfg.data.domain })}
					</AlertTitle>
					<AlertDescription>
						<p>{t('settings.proxy.live_body')}</p>
						<Button
							asChild
							variant="link"
							size="sm"
							className="mt-2 px-0"
						>
							<a
								href={`https://${cfg.data.domain}`}
								target="_blank"
								rel="noreferrer"
							>
								{`https://${cfg.data.domain}`}
								<ExternalLink className="ml-1 size-3" />
							</a>
						</Button>
					</AlertDescription>
				</Alert>
			)}

			{status.data?.error && (
				<Alert variant="destructive">
					<AlertTitle>{t('settings.proxy.error_title')}</AlertTitle>
					<AlertDescription>
						<p className="font-mono text-xs break-all">
							{status.data.error}
						</p>
					</AlertDescription>
				</Alert>
			)}

			<Card>
				<CardHeader>
					<CardTitle>{t('settings.proxy.form_title')}</CardTitle>
					<CardDescription>
						{t('settings.proxy.form_subtitle')}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<Form {...form}>
						<form
							onSubmit={form.handleSubmit((v) => save.mutate(v))}
							className="grid gap-4 max-w-xl"
						>
							<FormField
								control={form.control}
								name="domain"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.proxy.domain')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												placeholder="feedbot.example.com"
												autoComplete="off"
											/>
										</FormControl>
										<FormDescription>
											{t('settings.proxy.domain_help')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="letsencrypt_email"
								render={({ field }) => (
									<FormItem>
										<FormLabel>
											{t('settings.proxy.letsencrypt_email')}
										</FormLabel>
										<FormControl>
											<Input
												{...field}
												type="email"
												placeholder="ops@example.com"
												autoComplete="off"
											/>
										</FormControl>
										<FormDescription>
											{t('settings.proxy.letsencrypt_email_help')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<div className="flex flex-wrap items-center gap-3 pt-2">
								<Button
									type="button"
									variant="outline"
									onClick={() =>
										checkDns.mutate(form.getValues('domain'))
									}
									disabled={
										checkDns.isPending || !form.watch('domain')
									}
								>
									{checkDns.isPending
										? t('settings.proxy.checking_dns')
										: t('settings.proxy.check_dns')}
								</Button>
								<Button type="submit" disabled={save.isPending || polling}>
									{save.isPending
										? t('settings.proxy.saving')
										: t('common.save')}
								</Button>
								{cfg.data.configured && (
									<Button
										type="button"
										variant="ghost"
										onClick={() => setConfirmRemove(true)}
									>
										{t('settings.proxy.remove')}
									</Button>
								)}
							</div>
						</form>
					</Form>

					{dnsCheck && (
						<div className="mt-6 rounded-md border p-3 text-sm space-y-2">
							<div className="font-medium">
								{t('settings.proxy.dns_result_title', {
									domain: dnsCheck.domain,
								})}
							</div>
							<div className="grid grid-cols-2 gap-2 font-mono text-xs">
								<div className="text-muted-foreground">
									{t('settings.proxy.dns_resolved')}
								</div>
								<div>
									{dnsCheck.resolved_ips.length > 0
										? dnsCheck.resolved_ips.join(', ')
										: '—'}
								</div>
								<div className="text-muted-foreground">
									{t('settings.proxy.dns_server_ip')}
								</div>
								<div>{dnsCheck.server_ip ?? '—'}</div>
							</div>
							{dnsCheck.error ? (
								<p className="text-destructive">{dnsCheck.error}</p>
							) : dnsCheck.matches ? (
								<p className="text-emerald-600">
									{t('settings.proxy.dns_match')}
								</p>
							) : (
								<p className="text-amber-600">
									{t('settings.proxy.dns_mismatch')}
								</p>
							)}
						</div>
					)}
				</CardContent>
			</Card>

			<Dialog open={confirmRemove} onOpenChange={setConfirmRemove}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('settings.proxy.remove_title')}</DialogTitle>
						<DialogDescription>
							{t('settings.proxy.remove_body')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							onClick={() => setConfirmRemove(false)}
						>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							onClick={() => remove.mutate()}
							disabled={remove.isPending}
						>
							{t('settings.proxy.remove_confirm')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

/**
 * Settings → Telegram bot.
 *
 * Wire contract mirrors the SMTP page: token never leaves the
 * server, has_token boolean drives the UI, password tri-state on
 * write. The bot service is opt-in (compose profile "bot"); the
 * orchestrator starts it on save and stops it on disconnect.
 *
 * "Test connection" hits ``POST /test`` with the value currently
 * typed into the form (or, if the input is empty, the stored
 * token). The response carries the bot profile so the UI can
 * show "Connected as @feedbot_acme_bot" before the user even
 * saves — useful when validating a fresh BotFather token.
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

type BotConfigOut = components['schemas']['BotConfigOut'];
type BotChatOut = components['schemas']['BotChatOut'];
type BotProfileOut = components['schemas']['BotProfileOut'];
type BotTestOut = components['schemas']['BotTestOut'];

const schema = z.object({
	token: z.string().max(512).optional(),
	username: z.string().max(64).optional(),
	clear_token: z.boolean().optional(),
});
type FormValues = z.infer<typeof schema>;

const CFG_KEY = ['admin', 'bot', 'config'] as const;
const CHATS_KEY = ['admin', 'bot', 'chats'] as const;

export const Route = createFileRoute('/(authed)/settings/bot')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) throw redirect({ to: '/login' });
		if (me.user.role !== 'owner') throw redirect({ to: '/projects' });
		if (getConfig().deployment === 'cloud') {
			throw redirect({ to: '/projects' });
		}
	},
	component: BotSettingsPage,
});

function BotSettingsPage() {
	const { t } = useTranslation();
	const [confirmDisconnect, setConfirmDisconnect] = useState(false);
	const [testProfile, setTestProfile] = useState<BotProfileOut | null>(null);

	const cfg = useQuery({
		queryKey: CFG_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/bot/config'));
			return data as unknown as BotConfigOut;
		},
	});

	const chats = useQuery({
		queryKey: CHATS_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/bot/chats'));
			return data as unknown as BotChatOut[];
		},
	});

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		defaultValues: { token: '', username: '', clear_token: false },
	});

	useEffect(() => {
		if (!cfg.data) return;
		form.reset({
			token: '',
			username: cfg.data.username ?? '',
			clear_token: false,
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [cfg.data]);

	const save = useMutation({
		mutationFn: async (values: FormValues) => {
			let token: string | undefined | null = undefined;
			if (values.clear_token) token = '';
			else if (values.token && values.token.length > 0) token = values.token;

			const data = await unwrap(
				api.POST('/v1/admin/bot/config', {
					body: {
						username: values.username || null,
						...(token !== undefined ? { token } : {}),
					},
				}),
			);
			return data as unknown as BotConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(CFG_KEY, data);
			form.setValue('token', '');
			form.setValue('clear_token', false);
			toast.success(t('settings.bot.saved_toast'));
		},
		onError: (err) => {
			toast.error(
				t('settings.bot.save_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	const disconnect = useMutation({
		mutationFn: async () => {
			const data = await unwrap(api.DELETE('/v1/admin/bot/config'));
			return data as unknown as BotConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(CFG_KEY, data);
			setConfirmDisconnect(false);
			toast.success(t('settings.bot.disconnected_toast'));
		},
	});

	const testConnection = useMutation({
		mutationFn: async () => {
			const typed = form.getValues('token');
			const data = await unwrap(
				api.POST('/v1/admin/bot/test', {
					body: typed ? { token: typed } : {},
				}),
			);
			return data as unknown as BotTestOut;
		},
		onSuccess: (data) => {
			if (data.ok && data.profile) {
				setTestProfile(data.profile);
				toast.success(
					t('settings.bot.test_ok_toast', {
						username: data.profile.username ?? '?',
					}),
				);
			} else {
				setTestProfile(null);
				toast.error(
					t('settings.bot.test_failed_toast', {
						message: data.error ?? '',
					}),
				);
			}
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
							{t('settings.bot.title')}
						</h1>
						<p className="text-sm text-muted-foreground mt-1">
							{t('settings.bot.subtitle')}
						</p>
					</div>
					{cfg.data.configured ? (
						<Badge variant="success">{t('settings.status.configured')}</Badge>
					) : (
						<Badge variant="secondary">
							{t('settings.status.not_configured')}
						</Badge>
					)}
				</div>
			</div>

			{!cfg.data.configured && (
				<Alert>
					<AlertTitle>{t('settings.bot.empty_title')}</AlertTitle>
					<AlertDescription>
						<p>{t('settings.bot.empty_body')}</p>
						<ol className="mt-2 list-decimal pl-5 space-y-1 text-sm">
							<li>{t('settings.bot.empty_step1')}</li>
							<li>{t('settings.bot.empty_step2')}</li>
							<li>{t('settings.bot.empty_step3')}</li>
						</ol>
						<Button
							asChild
							variant="link"
							size="sm"
							className="mt-2 px-0"
						>
							<a
								href="https://t.me/BotFather"
								target="_blank"
								rel="noreferrer"
							>
								{t('settings.bot.empty_link')}
								<ExternalLink className="ml-1 size-3" />
							</a>
						</Button>
					</AlertDescription>
				</Alert>
			)}

			<Card>
				<CardHeader>
					<CardTitle>{t('settings.bot.form_title')}</CardTitle>
					<CardDescription>
						{t('settings.bot.form_subtitle')}
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
								name="token"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.bot.token')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												type="password"
												placeholder={
													cfg.data?.has_token ? '••••••••' : '123456:ABC-DEF...'
												}
												autoComplete="off"
												disabled={form.watch('clear_token')}
											/>
										</FormControl>
										<FormDescription>
											{cfg.data?.has_token
												? t('settings.bot.token_help_keep')
												: t('settings.bot.token_help_set')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="username"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.bot.username')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												placeholder="feedbot_acme_bot"
												autoComplete="off"
											/>
										</FormControl>
										<FormDescription>
											{t('settings.bot.username_help')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<div className="flex flex-wrap items-center gap-3 pt-2">
								<Button type="submit" disabled={save.isPending}>
									{save.isPending
										? t('settings.bot.saving')
										: t('common.save')}
								</Button>
								<Button
									type="button"
									variant="outline"
									onClick={() => testConnection.mutate()}
									disabled={
										testConnection.isPending ||
										(!cfg.data?.has_token && !form.watch('token'))
									}
								>
									{testConnection.isPending
										? t('settings.bot.testing')
										: t('settings.bot.test')}
								</Button>
								{cfg.data?.has_token && (
									<Button
										type="button"
										variant="ghost"
										onClick={() => setConfirmDisconnect(true)}
									>
										{t('settings.bot.disconnect')}
									</Button>
								)}
							</div>
						</form>
					</Form>
				</CardContent>
			</Card>

			{testProfile && (
				<Alert>
					<AlertTitle>
						{t('settings.bot.connected_as', {
							username: testProfile.username ?? '?',
						})}
					</AlertTitle>
					<AlertDescription>
						{t('settings.bot.connected_body', {
							first_name: testProfile.first_name ?? '?',
							id: testProfile.id,
						})}
					</AlertDescription>
				</Alert>
			)}

			<Card>
				<CardHeader>
					<CardTitle>{t('settings.bot.chats_title')}</CardTitle>
					<CardDescription>
						{t('settings.bot.chats_subtitle')}
					</CardDescription>
				</CardHeader>
				<CardContent>
					{chats.isLoading ? (
						<Skeleton className="h-10 w-full" />
					) : (chats.data ?? []).length === 0 ? (
						<p className="text-sm text-muted-foreground">
							{t('settings.bot.chats_empty')}
						</p>
					) : (
						<ul className="divide-y">
							{(chats.data ?? []).map((c) => (
								<li
									key={c.id}
									className="py-2 flex items-center justify-between gap-3"
								>
									<div className="min-w-0">
										<div className="font-medium truncate">
											{c.title ?? c.chat_id}
										</div>
										<div className="text-xs text-muted-foreground font-mono">
											{c.platform} · {c.chat_id} · {c.project_slug}
										</div>
									</div>
									<Button asChild variant="ghost" size="sm">
										<Link
											to="/projects/$slug"
											params={{ slug: c.project_slug }}
										>
											{t('settings.bot.chats_open_project')}
										</Link>
									</Button>
								</li>
							))}
						</ul>
					)}
				</CardContent>
			</Card>

			<Dialog open={confirmDisconnect} onOpenChange={setConfirmDisconnect}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('settings.bot.disconnect_title')}</DialogTitle>
						<DialogDescription>
							{t('settings.bot.disconnect_body')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							onClick={() => setConfirmDisconnect(false)}
						>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							onClick={() => disconnect.mutate()}
							disabled={disconnect.isPending}
						>
							{t('settings.bot.disconnect_confirm')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

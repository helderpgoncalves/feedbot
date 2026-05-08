/**
 * Settings → Email delivery (SMTP).
 *
 * The encrypted password never reaches the client; the API
 * exposes only ``has_password: boolean``. We mirror that with the
 * same tri-state pattern as the LLM-key form:
 *
 *   - has_password=true & user types nothing       → omit from POST (keep)
 *   - has_password=true & user clicks "clear"      → POST password=""  (clear)
 *   - user types into the password input           → POST password=…   (set)
 *
 * Every save round-trips through the orchestrator: DB write → ``.env``
 * rewrite → ``api`` container restart. The mutation can therefore take
 * ~5–15s in the worst case; the mutation's pending state drives the
 * "applying" chip on the button.
 *
 * "Send test email" hits the dedicated ``/test`` endpoint which uses
 * the *currently stored* credentials — i.e. a successful test verifies
 * the live config rather than what's in the form. Save first, then
 * test.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { ChevronLeft } from 'lucide-react';
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

type EmailConfigOut = components['schemas']['EmailConfigOut'];
type EmailTestOut = components['schemas']['EmailTestOut'];

const schema = z.object({
	host: z.string().max(255).optional(),
	port: z.string().optional(), // string so the input renders cleanly; parsed on submit
	user: z.string().max(255).optional(),
	password: z.string().max(512).optional(),
	clear_password: z.boolean().optional(),
	sender: z.string().max(255).optional(),
});
type FormValues = z.infer<typeof schema>;

const QUERY_KEY = ['admin', 'email', 'config'] as const;

export const Route = createFileRoute('/(authed)/settings/email')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me) throw redirect({ to: '/login' });
		if (me.user.role !== 'owner') throw redirect({ to: '/projects' });
		if (getConfig().deployment === 'cloud') {
			throw redirect({ to: '/projects' });
		}
	},
	component: EmailSettingsPage,
});

function EmailSettingsPage() {
	const { t } = useTranslation();
	const [confirmDisable, setConfirmDisable] = useState(false);
	const [testEmailOpen, setTestEmailOpen] = useState(false);

	const cfg = useQuery({
		queryKey: QUERY_KEY,
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/admin/email/config'));
			return data as unknown as EmailConfigOut;
		},
	});

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		defaultValues: {
			host: '',
			port: '587',
			user: '',
			password: '',
			clear_password: false,
			sender: '',
		},
	});

	// Hydrate the form once the config arrives. We deliberately leave
	// ``password`` empty — it's never returned by the server.
	useEffect(() => {
		if (!cfg.data) return;
		form.reset({
			host: cfg.data.host ?? '',
			port: cfg.data.port ? String(cfg.data.port) : '587',
			user: cfg.data.user ?? '',
			password: '',
			clear_password: false,
			sender: cfg.data.sender ?? '',
		});
		// We intentionally only re-hydrate when the loaded payload changes,
		// not on every form mutation.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [cfg.data]);

	const save = useMutation({
		mutationFn: async (values: FormValues) => {
			const portNum = values.port ? Number(values.port) : null;
			// Tri-state mapping:
			//   typed something  → set
			//   clear_password   → clear (empty string)
			//   nothing typed    → keep (omit field)
			let password: string | undefined | null = undefined;
			if (values.clear_password) password = '';
			else if (values.password && values.password.length > 0)
				password = values.password;

			const data = await unwrap(
				api.POST('/v1/admin/email/config', {
					body: {
						host: values.host || null,
						port: portNum,
						user: values.user || null,
						sender: values.sender || null,
						...(password !== undefined ? { password } : {}),
					},
				}),
			);
			return data as unknown as EmailConfigOut;
		},
		onSuccess: (data) => {
			queryClient.setQueryData(QUERY_KEY, data);
			form.setValue('password', '');
			form.setValue('clear_password', false);
			toast.success(t('settings.email.saved_toast'));
		},
		onError: (err) => {
			toast.error(
				t('settings.email.save_failed_toast', {
					message: err instanceof Error ? err.message : String(err),
				}),
			);
		},
	});

	const sendTest = useMutation({
		mutationFn: async (to: string) => {
			const data = await unwrap(
				api.POST('/v1/admin/email/test', { body: { to } }),
			);
			return data as unknown as EmailTestOut;
		},
		onSuccess: (data) => {
			if (data.ok) {
				toast.success(t('settings.email.test_ok_toast'));
			} else {
				toast.error(
					t('settings.email.test_failed_toast', {
						message: data.error ?? '',
					}),
				);
			}
			setTestEmailOpen(false);
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
							{t('settings.email.title')}
						</h1>
						<p className="text-sm text-muted-foreground mt-1">
							{t('settings.email.subtitle')}
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
					<AlertTitle>{t('settings.email.empty_title')}</AlertTitle>
					<AlertDescription>
						{t('settings.email.empty_body')}
					</AlertDescription>
				</Alert>
			)}

			<Card>
				<CardHeader>
					<CardTitle>{t('settings.email.form_title')}</CardTitle>
					<CardDescription>
						{t('settings.email.form_subtitle')}
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
								name="host"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.email.host')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												placeholder="smtp.resend.com"
												autoComplete="off"
											/>
										</FormControl>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="port"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.email.port')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												type="number"
												inputMode="numeric"
												placeholder="587"
												autoComplete="off"
											/>
										</FormControl>
										<FormDescription>
											{t('settings.email.port_help')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="user"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.email.user')}</FormLabel>
										<FormControl>
											<Input {...field} autoComplete="off" />
										</FormControl>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="password"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.email.password')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												type="password"
												placeholder={
													cfg.data?.has_password
														? '••••••••'
														: ''
												}
												autoComplete="new-password"
												disabled={form.watch('clear_password')}
											/>
										</FormControl>
										<FormDescription>
											{cfg.data?.has_password
												? t('settings.email.password_help_keep')
												: t('settings.email.password_help_set')}
										</FormDescription>
										<FormMessage />
									</FormItem>
								)}
							/>

							<FormField
								control={form.control}
								name="sender"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('settings.email.sender')}</FormLabel>
										<FormControl>
											<Input
												{...field}
												placeholder="feedbot@example.com"
												autoComplete="off"
											/>
										</FormControl>
										<FormMessage />
									</FormItem>
								)}
							/>

							<div className="flex flex-wrap items-center gap-3 pt-2">
								<Button type="submit" disabled={save.isPending}>
									{save.isPending
										? t('settings.email.saving')
										: t('common.save')}
								</Button>
								<Button
									type="button"
									variant="outline"
									onClick={() => setTestEmailOpen(true)}
									disabled={!cfg.data?.configured}
								>
									{t('settings.email.send_test')}
								</Button>
								{cfg.data?.has_password && (
									<Button
										type="button"
										variant="ghost"
										onClick={() => setConfirmDisable(true)}
									>
										{t('settings.email.disable')}
									</Button>
								)}
							</div>
						</form>
					</Form>
				</CardContent>
			</Card>

			<TestEmailDialog
				open={testEmailOpen}
				onOpenChange={setTestEmailOpen}
				onSubmit={(to) => sendTest.mutate(to)}
				pending={sendTest.isPending}
			/>

			<Dialog open={confirmDisable} onOpenChange={setConfirmDisable}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('settings.email.disable_title')}</DialogTitle>
						<DialogDescription>
							{t('settings.email.disable_body')}
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button
							variant="outline"
							onClick={() => setConfirmDisable(false)}
						>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							onClick={() => {
								setConfirmDisable(false);
								save.mutate({
									host: form.getValues('host'),
									port: form.getValues('port'),
									user: form.getValues('user'),
									password: '',
									clear_password: true,
									sender: form.getValues('sender'),
								});
							}}
						>
							{t('settings.email.disable_confirm')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

function TestEmailDialog({
	open,
	onOpenChange,
	onSubmit,
	pending,
}: {
	open: boolean;
	onOpenChange: (v: boolean) => void;
	onSubmit: (to: string) => void;
	pending: boolean;
}) {
	const { t } = useTranslation();
	const [to, setTo] = useState('');

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('settings.email.test_title')}</DialogTitle>
					<DialogDescription>
						{t('settings.email.test_body')}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-2">
					<label className="text-sm font-medium">
						{t('settings.email.test_to')}
					</label>
					<Input
						type="email"
						value={to}
						onChange={(e) => setTo(e.target.value)}
						placeholder="ops@example.com"
					/>
				</div>
				<DialogFooter>
					<Button variant="outline" onClick={() => onOpenChange(false)}>
						{t('common.cancel')}
					</Button>
					<Button
						onClick={() => onSubmit(to)}
						disabled={pending || !to}
					>
						{pending ? t('common.saving') : t('settings.email.send_test')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

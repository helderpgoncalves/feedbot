/**
 * LLM settings page for a project. Encrypted API keys never leave the
 * server (the backend exposes only `has_api_key: boolean`); the UI mirrors
 * that contract with a tri-state input:
 *
 *   - has_api_key=true & user types nothing  → omit api_key from PUT (keep)
 *   - has_api_key=true & user clicks "clear" → send api_key=""        (clear)
 *   - user types into the input              → send api_key="..."     (set)
 *
 * The server also rejects clearing while enabled=true; we mirror the rule
 * client-side so users get the validation message inline.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, createFileRoute } from '@tanstack/react-router';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { ChevronLeft } from 'lucide-react';
import { z } from 'zod';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from '@/components/ui/table';
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';
import { projectSlug } from '@/lib/types';
import type { components } from '@/types/api';

type LLMSettingsOut = components['schemas']['LLMSettingsOut'];
type LLMCallOut = components['schemas']['LLMCallOut'];
type ProvidersOut = components['schemas']['ProvidersOut'];

const schema = z.object({
	provider: z.string().min(1),
	model: z.string().max(120).optional(),
	api_key: z.string().max(512).optional(),
	clear_key: z.boolean().optional(),
	enabled: z.boolean(),
	// Stored as a string so the input can render an empty value cleanly; the
	// submit handler parses it. A union of number/empty here breaks the
	// Control<> generic chain react-hook-form needs.
	monthly_budget_usd: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export const Route = createFileRoute('/(authed)/projects/$slug/llm')({
	component: LLMPage,
});

function LLMPage() {
	const { t } = useTranslation();
	const params = Route.useParams();
	const slug = projectSlug(params.slug);

	const settings = useQuery({
		queryKey: queryKeys.projects.llmSettings(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/llm-settings', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as LLMSettingsOut;
		},
	});

	const providers = useQuery({
		queryKey: queryKeys.llmProviders(),
		queryFn: async () => {
			const data = await unwrap(api.GET('/v1/llm/providers'));
			return data as unknown as ProvidersOut;
		},
		staleTime: 5 * 60_000,
	});

	const calls = useQuery({
		queryKey: queryKeys.projects.llmCalls(slug),
		queryFn: async () => {
			const data = await unwrap(
				api.GET('/v1/projects/{slug}/llm-calls', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as LLMCallOut[];
		},
	});

	if (settings.isLoading || !settings.data) {
		return (
			<div className="space-y-6">
				<Skeleton className="h-10 w-1/3" />
				<Skeleton className="h-60 w-full" />
			</div>
		);
	}

	return (
		<div className="space-y-6">
			<div>
				<Button asChild variant="ghost" size="sm" className="-ml-3 mb-2">
					<Link to="/projects/$slug" params={{ slug }}>
						<ChevronLeft className="size-4" />
						{t('common.back')}
					</Link>
				</Button>
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('llm.title')}
				</h1>
				<p className="text-sm text-muted-foreground mt-1">
					Spend this month: <span className="font-mono">${settings.data.month_to_date_usd.toFixed(4)}</span>
				</p>
			</div>

			<SettingsCard
				settings={settings.data}
				providers={providers.data?.providers ?? {}}
				slug={slug}
			/>
			<TestCard slug={slug} disabled={!settings.data.enabled} />
			<CallsCard rows={calls.data ?? []} loading={calls.isLoading} />
		</div>
	);
}

function SettingsCard({
	settings,
	providers,
	slug,
}: {
	settings: LLMSettingsOut;
	providers: Record<string, Record<string, unknown>>;
	slug: ReturnType<typeof projectSlug>;
}) {
	const { t } = useTranslation();

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: {
			provider: settings.provider,
			model: settings.model ?? '',
			api_key: '',
			clear_key: false,
			enabled: settings.enabled,
			monthly_budget_usd:
				settings.monthly_budget_usd != null ? String(settings.monthly_budget_usd) : '',
		},
	});

	useEffect(() => {
		form.reset({
			provider: settings.provider,
			model: settings.model ?? '',
			api_key: '',
			clear_key: false,
			enabled: settings.enabled,
			monthly_budget_usd:
				settings.monthly_budget_usd != null ? String(settings.monthly_budget_usd) : '',
		});
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [settings.provider, settings.model, settings.enabled, settings.monthly_budget_usd]);

	const save = useMutation({
		mutationFn: async (values: FormValues) => {
			// Mirror the server rule client-side so the user gets it inline.
			if (values.clear_key && values.enabled) {
				form.setError('clear_key', {
					message: 'Disable classification before clearing the key.',
				});
				throw new Error('clear-while-enabled');
			}
			// Tri-state api_key: undefined=keep, ""=clear, "..."=set.
			let apiKey: string | undefined;
			if (values.clear_key) apiKey = '';
			else if (values.api_key && values.api_key.length > 0) apiKey = values.api_key;
			else apiKey = undefined;

			const budgetStr = (values.monthly_budget_usd ?? '').trim();
			const budget = budgetStr === '' ? null : Number(budgetStr);
			if (budget !== null && !Number.isFinite(budget)) {
				form.setError('monthly_budget_usd', { message: 'Must be a number.' });
				throw new Error('invalid-budget');
			}
			const body = {
				provider: values.provider,
				model: values.model || null,
				api_key: apiKey,
				enabled: values.enabled,
				monthly_budget_usd: budget,
			};
			return unwrap(
				api.PUT('/v1/projects/{slug}/llm-settings', {
					params: { path: { slug } },
					body,
				}),
			);
		},
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.projects.llmSettings(slug),
			});
		},
	});

	const availableModels =
		(providers[form.watch('provider')]?.available_models as string[] | undefined) ?? [];

	return (
		<Card>
			<CardHeader>
				<CardTitle className="text-base">Configuration</CardTitle>
				<CardDescription>
					{settings.has_api_key
						? t('llm.api_key_set')
						: 'No API key configured.'}
				</CardDescription>
			</CardHeader>
			<CardContent>
				<Form {...form}>
					<form
						onSubmit={form.handleSubmit((v) => save.mutate(v))}
						className="space-y-4"
						noValidate
					>
						<div className="grid gap-4 sm:grid-cols-2">
							<FormField
								control={form.control}
								name="provider"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('llm.provider')}</FormLabel>
										<Select onValueChange={field.onChange} value={field.value}>
											<FormControl>
												<SelectTrigger>
													<SelectValue />
												</SelectTrigger>
											</FormControl>
											<SelectContent>
												<SelectItem value="none">none</SelectItem>
												{Object.keys(providers).map((p) => (
													<SelectItem key={p} value={p}>
														{p}
													</SelectItem>
												))}
											</SelectContent>
										</Select>
										<FormMessage />
									</FormItem>
								)}
							/>
							<FormField
								control={form.control}
								name="model"
								render={({ field }) => (
									<FormItem>
										<FormLabel>{t('llm.model')}</FormLabel>
										<FormControl>
											<Input
												list="model-options"
												placeholder={availableModels[0] ?? 'gpt-4o-mini'}
												className="font-mono"
												{...field}
											/>
										</FormControl>
										<datalist id="model-options">
											{availableModels.map((m) => (
												<option key={m} value={m} />
											))}
										</datalist>
										<FormMessage />
									</FormItem>
								)}
							/>
						</div>

						<FormField
							control={form.control}
							name="api_key"
							render={({ field }) => (
								<FormItem>
									<FormLabel>
										{settings.has_api_key
											? t('llm.api_key_change')
											: t('llm.api_key')}
									</FormLabel>
									<FormControl>
										<Input
											type="password"
											autoComplete="off"
											placeholder={
												settings.has_api_key
													? '•••••••••••••••• (leave empty to keep)'
													: 'sk-...'
											}
											{...field}
										/>
									</FormControl>
									<FormDescription>
										Stored Fernet-encrypted; the server never returns it.
									</FormDescription>
									<FormMessage />
								</FormItem>
							)}
						/>

						{settings.has_api_key && (
							<FormField
								control={form.control}
								name="clear_key"
								render={({ field }) => (
									<FormItem className="flex items-center gap-3 space-y-0">
										<FormControl>
											<Switch checked={!!field.value} onCheckedChange={field.onChange} />
										</FormControl>
										<FormLabel className="!mt-0 cursor-pointer">
											{t('llm.api_key_clear')}
										</FormLabel>
										<FormMessage />
									</FormItem>
								)}
							/>
						)}

						<FormField
							control={form.control}
							name="enabled"
							render={({ field }) => (
								<FormItem className="flex items-center gap-3 space-y-0">
									<FormControl>
										<Switch checked={field.value} onCheckedChange={field.onChange} />
									</FormControl>
									<FormLabel className="!mt-0 cursor-pointer">
										{t('llm.enabled')}
									</FormLabel>
								</FormItem>
							)}
						/>

						<FormField
							control={form.control}
							name="monthly_budget_usd"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('llm.monthly_budget')}</FormLabel>
									<FormControl>
										<Input
											type="number"
											step="0.01"
											min="0"
											placeholder="No cap"
											{...field}
											value={field.value ?? ''}
										/>
									</FormControl>
									<FormDescription>
										{t('llm.monthly_budget_help')}
									</FormDescription>
								</FormItem>
							)}
						/>

						<div className="flex justify-end">
							<Button type="submit" disabled={save.isPending}>
								{save.isPending ? t('common.saving') : t('common.confirm')}
							</Button>
						</div>
					</form>
				</Form>
			</CardContent>
		</Card>
	);
}

function TestCard({ slug, disabled }: { slug: ReturnType<typeof projectSlug>; disabled: boolean }) {
	const { t } = useTranslation();
	const test = useMutation({
		mutationFn: async () => {
			const data = await unwrap(
				api.POST('/v1/projects/{slug}/llm-test', {
					params: { path: { slug } },
				}),
			);
			return data as unknown as { ok: boolean; status: string; error_text: string | null };
		},
		onSettled: () =>
			queryClient.invalidateQueries({ queryKey: queryKeys.projects.llmCalls(slug) }),
	});

	return (
		<Card>
			<CardHeader>
				<CardTitle className="text-base">Test connection</CardTitle>
				<CardDescription>
					Round-trips a sample classification. Recorded in the audit log.
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-3">
				<Button onClick={() => test.mutate()} disabled={disabled || test.isPending}>
					{test.isPending ? t('llm.test_running') : t('llm.test_button')}
				</Button>
				{test.data?.ok && (
					<Alert>
						<AlertTitle>OK</AlertTitle>
						<AlertDescription>{t('llm.test_ok')}</AlertDescription>
					</Alert>
				)}
				{test.data && !test.data.ok && (
					<Alert variant="destructive">
						<AlertTitle>{test.data.status}</AlertTitle>
						<AlertDescription className="font-mono text-xs break-all">
							{test.data.error_text ?? '—'}
						</AlertDescription>
					</Alert>
				)}
			</CardContent>
		</Card>
	);
}

function CallsCard({ rows, loading }: { rows: LLMCallOut[]; loading: boolean }) {
	const { t } = useTranslation();
	if (loading) return <Skeleton className="h-40 w-full" />;

	return (
		<Card>
			<CardHeader>
				<CardTitle className="text-base">{t('llm.calls_table.title')}</CardTitle>
			</CardHeader>
			<CardContent>
				{rows.length === 0 ? (
					<p className="text-sm text-muted-foreground">{t('llm.calls_table.empty')}</p>
				) : (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>When</TableHead>
								<TableHead>Provider</TableHead>
								<TableHead>Model</TableHead>
								<TableHead>Status</TableHead>
								<TableHead className="text-right">Tokens</TableHead>
								<TableHead className="text-right">Cost</TableHead>
								<TableHead className="text-right">Latency</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((c) => (
								<TableRow key={c.id}>
									<TableCell className="font-mono text-xs">
										{new Date(c.created_at).toLocaleString()}
									</TableCell>
									<TableCell className="font-mono">{c.provider}</TableCell>
									<TableCell className="font-mono">{c.model}</TableCell>
									<TableCell>
										<Badge variant={c.status === 'ok' ? 'success' : 'destructive'}>
											{c.status}
										</Badge>
									</TableCell>
									<TableCell className="text-right font-mono">
										{c.total_tokens}
									</TableCell>
									<TableCell className="text-right font-mono">
										${c.usd_cost.toFixed(6)}
									</TableCell>
									<TableCell className="text-right font-mono">
										{c.latency_ms}ms
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				)}
			</CardContent>
		</Card>
	);
}

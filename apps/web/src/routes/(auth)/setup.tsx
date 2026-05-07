/**
 * First-run bootstrap page. Active only while ``GET /v1/setup-status`` reports
 * ``required: true`` — i.e. the users table is empty. Posts to ``/v1/setup``,
 * which atomically creates the first tenant + owner and emails a magic link.
 *
 * Two outcome cards:
 *   1. Email delivered → "check your inbox" prompt with a "back to login" link.
 *   2. Email NOT delivered (no SMTP on the deployment) → render the
 *      ``fallback_link`` returned by the API as a one-click button so the
 *      bootstrapping admin can sign in immediately without digging through
 *      container logs. This branch only fires on production-HTTPS deploys
 *      that booted with ``EMAIL_BACKEND=console`` — a misconfiguration but
 *      not one that should lock the new owner out of their own instance.
 *
 * If a user reaches /setup *after* bootstrap (URL bookmarked, refresh after
 * setup) the loader redirects to /login — the API will 410 anyway, so we
 * skip the round-trip.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { api, unwrap } from '@/lib/api';
import type { components } from '@/types/api';

type SetupOut = components['schemas']['SetupOut'];

const schema = z.object({
	email: z.string().min(3).max(255).email(),
	tenant_name: z.string().max(120).optional(),
});
type FormValues = z.infer<typeof schema>;

export const Route = createFileRoute('/(auth)/setup')({
	beforeLoad: async () => {
		// Skip the round-trip if bootstrap is already done — the API would
		// return 410 anyway, and the user belongs on /login.
		const { data } = await api.GET('/v1/setup-status');
		if (data && data.required === false) {
			throw redirect({ to: '/login' });
		}
	},
	component: SetupPage,
});

function SetupPage() {
	const { t } = useTranslation();
	const [result, setResult] = useState<SetupOut | null>(null);

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: { email: '', tenant_name: '' },
	});

	const submit = useMutation({
		mutationFn: async (values: FormValues) => {
			const data = await unwrap(
				api.POST('/v1/setup', {
					body: {
						email: values.email,
						tenant_name: values.tenant_name ?? '',
					},
				}),
			);
			return data as unknown as SetupOut;
		},
		onSuccess: (data) => setResult(data),
	});

	if (result) {
		return <SetupSuccessCard result={result} />;
	}

	return (
		<Card>
			<CardHeader className="text-center">
				<CardTitle>{t('auth.setup.title')}</CardTitle>
				<CardDescription>{t('auth.setup.subtitle')}</CardDescription>
			</CardHeader>
			<CardContent>
				<Form {...form}>
					<form
						onSubmit={form.handleSubmit((v) => submit.mutate(v))}
						className="space-y-4"
						noValidate
					>
						<FormField
							control={form.control}
							name="email"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('auth.setup.email_label')}</FormLabel>
									<FormControl>
										<Input
											type="email"
											autoComplete="email"
											autoFocus
											placeholder="you@example.com"
											{...field}
										/>
									</FormControl>
									<FormDescription>
										{t('auth.setup.email_help')}
									</FormDescription>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={form.control}
							name="tenant_name"
							render={({ field }) => (
								<FormItem>
									<FormLabel>
										{t('auth.setup.tenant_label')}{' '}
										<span className="text-muted-foreground text-xs">
											({t('common.optional')})
										</span>
									</FormLabel>
									<FormControl>
										<Input placeholder="Acme Inc." {...field} />
									</FormControl>
									<FormDescription>
										{t('auth.setup.tenant_help')}
									</FormDescription>
									<FormMessage />
								</FormItem>
							)}
						/>
						<Button type="submit" className="w-full" disabled={submit.isPending}>
							{submit.isPending
								? t('auth.setup.submitting')
								: t('auth.setup.submit')}
						</Button>
					</form>
				</Form>
			</CardContent>
		</Card>
	);
}

function SetupSuccessCard({ result }: { result: SetupOut }) {
	const { t } = useTranslation();

	if (result.delivered) {
		return (
			<Card>
				<CardHeader className="text-center">
					<CardTitle>{t('auth.setup.sent_title')}</CardTitle>
					<CardDescription>
						{t('auth.setup.sent_subtitle', { email: result.email })}
					</CardDescription>
				</CardHeader>
				<CardContent>
					<Button asChild variant="outline" className="w-full">
						<Link to="/login">{t('auth.setup.back_to_login')}</Link>
					</Button>
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle>{t('auth.setup.fallback_title')}</CardTitle>
				<CardDescription>
					{t('auth.setup.fallback_subtitle', { email: result.email })}
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-4">
				<Alert>
					<AlertTitle>{t('auth.setup.fallback_alert_title')}</AlertTitle>
					<AlertDescription>
						{t('auth.setup.fallback_alert_body')}
					</AlertDescription>
				</Alert>
				{result.fallback_link && (
					<Button asChild className="w-full">
						<a href={result.fallback_link}>{t('auth.setup.fallback_signin')}</a>
					</Button>
				)}
			</CardContent>
		</Card>
	);
}

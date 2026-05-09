/**
 * Cloud sign-up page. POSTs to /v1/signup which (a) creates a fresh tenant
 * + owner if the email is new, (b) emails a magic-link, and (c) sets the
 * `mlnonce` httpOnly cookie for PKCE binding.
 *
 * The route is hidden behind `cfg.allowSignup` — both via `beforeLoad`
 * (defence-in-depth against stale bookmarks on self-host) and at the link
 * level on the login page. The backend itself returns 404 when the flag is
 * off, so even a hand-crafted POST is rejected.
 *
 * Response shape mirrors /v1/auth/login: { sent: true } regardless of
 * whether the email was new, already registered, or rate-limited (we map
 * 429 to a friendly retry message). This is anti-enumeration by design.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
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
import { ApiError } from '@/lib/api';
import { getConfig } from '@/lib/config';

const schema = z.object({
	email: z.string().min(3).max(255).email(),
	tenant_name: z.string().max(120),
});
type FormValues = z.infer<typeof schema>;

export const Route = createFileRoute('/(auth)/signup')({
	beforeLoad: () => {
		// Defence-in-depth: a self-host instance might still hold a stale
		// bookmark to /signup. If allowSignup is false, send the visitor to
		// /login instead of rendering an empty form that the backend will
		// 404 anyway. The backend remains the source of truth.
		const cfg = getConfig();
		if (!cfg.allowSignup) {
			throw redirect({ to: '/login' });
		}
	},
	component: SignupPage,
});

interface SignupResponse {
	sent: boolean;
}

async function postSignup(values: FormValues): Promise<SignupResponse> {
	const res = await fetch('/api/v1/signup', {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			email: values.email,
			tenant_name: values.tenant_name,
		}),
	});
	if (res.status === 200) {
		return (await res.json()) as SignupResponse;
	}
	let body: unknown = null;
	try {
		body = await res.json();
	} catch {
		// Body might be empty / non-JSON on rate-limit responses.
	}
	const detail =
		(body as { detail?: string } | null)?.detail ?? res.statusText;
	throw new ApiError(res.status, detail, body);
}

function SignupPage() {
	const { t } = useTranslation();
	const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: { email: '', tenant_name: '' },
	});

	const submit = useMutation({
		mutationFn: postSignup,
		onSuccess: (_data, vars) => setSubmittedEmail(vars.email),
		onError: (err) => {
			// Rate-limit gets its own friendly message; everything else falls
			// through to the global error toast.
			if (err instanceof ApiError && err.status === 429) {
				form.setError('root', { message: t('common.rate_limited') });
				return;
			}
			form.setError('root', { message: t('common.unknown_error') });
		},
		// 429 should not fire the global toast — we surface it inline.
		meta: { silent: true },
	});

	if (submittedEmail) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{t('auth.signup.sent_title')}</CardTitle>
					<CardDescription>
						{t('auth.signup.sent_subtitle', { email: submittedEmail })}
					</CardDescription>
				</CardHeader>
				<CardContent className="space-y-2">
					<Button
						variant="outline"
						className="w-full"
						onClick={() => {
							setSubmittedEmail(null);
							form.reset();
						}}
					>
						{t('auth.login.resend')}
					</Button>
					<Button asChild variant="ghost" className="w-full">
						<Link to="/login">{t('auth.signup.back_to_login')}</Link>
					</Button>
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader className="text-center">
				<CardTitle>{t('auth.signup.title')}</CardTitle>
				<CardDescription>{t('auth.signup.subtitle')}</CardDescription>
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
									<FormLabel>{t('auth.signup.email_label')}</FormLabel>
									<FormControl>
										<Input
											type="email"
											autoComplete="email"
											autoFocus
											placeholder={t('auth.signup.email_placeholder')}
											{...field}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={form.control}
							name="tenant_name"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('auth.signup.tenant_label')}</FormLabel>
									<FormControl>
										<Input
											type="text"
											autoComplete="organization"
											placeholder={t('auth.signup.tenant_placeholder')}
											{...field}
										/>
									</FormControl>
									<FormDescription>
										{t('auth.signup.tenant_help')}
									</FormDescription>
									<FormMessage />
								</FormItem>
							)}
						/>
						{form.formState.errors.root?.message && (
							<p className="text-sm text-destructive">
								{form.formState.errors.root.message}
							</p>
						)}
						<Button type="submit" className="w-full" disabled={submit.isPending}>
							{submit.isPending
								? t('auth.signup.submitting')
								: t('auth.signup.submit')}
						</Button>
					</form>
				</Form>
				<p className="mt-6 text-center text-sm text-muted-foreground">
					{t('auth.signup.already_have_account')}{' '}
					<Link to="/login" className="underline-offset-4 hover:underline">
						{t('auth.signup.login_cta')}
					</Link>
				</p>
			</CardContent>
		</Card>
	);
}

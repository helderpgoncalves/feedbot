/**
 * Sign-in page. Posts the email to /v1/auth/login, which (a) sends a
 * magic-link if the email exists and (b) sets the `mlnonce` httpOnly cookie
 * for PKCE binding. Response is identical for known/unknown emails to
 * prevent enumeration; we always show the "check your email" success card.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { Link, createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
	Form,
	FormControl,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { api, unwrap } from '@/lib/api';
import { getConfig } from '@/lib/config';

const schema = z.object({
	email: z.string().min(3).max(255).email(),
});
type FormValues = z.infer<typeof schema>;

export const Route = createFileRoute('/(auth)/login')({
	validateSearch: (search): { redirect?: string } => ({
		redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
	}),
	component: LoginPage,
});

function LoginPage() {
	const { t } = useTranslation();
	const cfg = getConfig();
	const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: { email: '' },
	});

	const submit = useMutation({
		mutationFn: (values: FormValues) =>
			unwrap(
				api.POST('/v1/auth/login', {
					body: { email: values.email },
				}),
			),
		onSuccess: (_data, vars) => setSubmittedEmail(vars.email),
		onError: () => {
			// Set the form-level message; global toast also fires from the
			// query client error handler.
			form.setError('root', { message: t('common.unknown_error') });
		},
	});

	if (submittedEmail) {
		return (
			<Card>
				<CardHeader>
					<CardTitle>{t('auth.login.sent_title')}</CardTitle>
					<CardDescription>
						{t('auth.login.sent_subtitle', { email: submittedEmail })}
					</CardDescription>
				</CardHeader>
				<CardContent>
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
				</CardContent>
			</Card>
		);
	}

	return (
		<Card>
			<CardHeader className="text-center">
				<CardTitle>{t('auth.login.title')}</CardTitle>
				<CardDescription>{t('auth.login.subtitle')}</CardDescription>
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
									<FormLabel>{t('auth.login.email_label')}</FormLabel>
									<FormControl>
										<Input
											type="email"
											autoComplete="email"
											autoFocus
											placeholder={t('auth.login.email_placeholder')}
											{...field}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						<Button type="submit" className="w-full" disabled={submit.isPending}>
							{submit.isPending
								? t('auth.login.submitting')
								: t('auth.login.submit')}
						</Button>
					</form>
				</Form>
				{cfg.allowSignup && (
					<p className="mt-6 text-center text-sm text-muted-foreground">
						{t('auth.login.no_account')}{' '}
						<Link to="/signup" className="underline-offset-4 hover:underline">
							{t('auth.login.signup_cta')}
						</Link>
					</p>
				)}
			</CardContent>
		</Card>
	);
}

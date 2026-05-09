/**
 * /account — owner-only personal/workspace controls.
 *
 * Two surfaces today: GDPR data export (one zip) and workspace deletion
 * (irreversible, email-reconfirmed). Visible to owners on cloud; on
 * self-host the page works the same way (the API endpoints don't gate
 * by deployment), it just isn't linked from the default chrome until
 * the operator chooses to surface it.
 */

import { useMutation } from '@tanstack/react-query';
import { Link, createFileRoute, redirect } from '@tanstack/react-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, TriangleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api';
import { meQueryOptions, useMe } from '@/lib/auth';

export const Route = createFileRoute('/(authed)/account')({
	beforeLoad: async ({ context }) => {
		const me = await context.queryClient.ensureQueryData(meQueryOptions());
		if (!me || me.user.role !== 'owner') {
			throw redirect({ to: '/projects' });
		}
	},
	component: AccountPage,
});

function AccountPage() {
	const { t } = useTranslation();
	const { data: me } = useMe();
	const [confirmOpen, setConfirmOpen] = useState(false);
	const [confirmEmail, setConfirmEmail] = useState('');

	const exportMut = useMutation({
		mutationFn: async () => {
			const res = await fetch('/api/v1/tenant/export', {
				credentials: 'same-origin',
			});
			if (!res.ok) {
				throw new ApiError(res.status, res.statusText, null);
			}
			// Blob download via a temporary anchor — same pattern Stripe
			// uses for invoice PDFs.
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download =
				res.headers
					.get('Content-Disposition')
					?.match(/filename="?([^";]+)"?/)?.[1] ?? 'feedbot-export.zip';
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		},
	});

	const deleteMut = useMutation({
		mutationFn: async (confirm: string) => {
			const res = await fetch('/api/v1/tenant/delete', {
				method: 'POST',
				credentials: 'same-origin',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ confirm_email: confirm }),
			});
			if (!res.ok) {
				let body: unknown = null;
				try {
					body = await res.json();
				} catch {
					/* empty */
				}
				const detail =
					(body as { detail?: string } | null)?.detail ?? res.statusText;
				throw new ApiError(res.status, detail, body);
			}
		},
		onSuccess: () => {
			// Tenant is gone — kick the user back to /login.
			window.location.assign('/login');
		},
	});

	if (!me) return null;

	return (
		<div className="space-y-6 max-w-2xl">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">
					{t('account.title')}
				</h1>
				<p className="text-sm text-muted-foreground mt-1">
					{t('account.subtitle')}
				</p>
			</div>

			<Card>
				<CardHeader>
					<CardTitle>{t('account.export.title')}</CardTitle>
					<CardDescription>{t('account.export.subtitle')}</CardDescription>
				</CardHeader>
				<CardContent className="flex items-center justify-between gap-4">
					<p className="text-sm text-muted-foreground">
						{t('account.export.body')}
					</p>
					<Button
						onClick={() => exportMut.mutate()}
						disabled={exportMut.isPending}
					>
						<Download className="mr-2 size-4" />
						{exportMut.isPending
							? t('account.export.preparing')
							: t('account.export.cta')}
					</Button>
				</CardContent>
			</Card>

			<Card className="border-destructive/40">
				<CardHeader>
					<CardTitle className="flex items-center gap-2 text-destructive">
						<TriangleAlert className="size-5" />
						{t('account.danger.title')}
					</CardTitle>
					<CardDescription>{t('account.danger.subtitle')}</CardDescription>
				</CardHeader>
				<CardContent>
					<Button
						variant="destructive"
						onClick={() => {
							setConfirmEmail('');
							setConfirmOpen(true);
						}}
					>
						{t('account.danger.cta')}
					</Button>
				</CardContent>
			</Card>

			<Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>{t('account.danger.confirm_title')}</DialogTitle>
						<DialogDescription>
							{t('account.danger.confirm_body', { email: me.user.email })}
						</DialogDescription>
					</DialogHeader>
					<div className="space-y-2">
						<Label htmlFor="confirm-email">
							{t('account.danger.confirm_label')}
						</Label>
						<Input
							id="confirm-email"
							type="email"
							autoComplete="off"
							value={confirmEmail}
							onChange={(e) => setConfirmEmail(e.target.value)}
							placeholder={me.user.email}
						/>
					</div>
					{deleteMut.isError && (
						<Alert variant="destructive">
							<AlertTitle>{t('account.danger.failed_title')}</AlertTitle>
							<AlertDescription>
								{deleteMut.error instanceof ApiError
									? deleteMut.error.message
									: t('common.unknown_error')}
							</AlertDescription>
						</Alert>
					)}
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmOpen(false)}>
							{t('common.cancel')}
						</Button>
						<Button
							variant="destructive"
							disabled={
								confirmEmail.toLowerCase() !== me.user.email.toLowerCase() ||
								deleteMut.isPending
							}
							onClick={() => deleteMut.mutate(confirmEmail)}
						>
							{deleteMut.isPending
								? t('account.danger.deleting')
								: t('account.danger.confirm_cta')}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			<p className="text-xs text-muted-foreground">
				{t('account.privacy_prefix')}{' '}
				<Link to="/projects" className="underline-offset-4 hover:underline">
					{t('account.privacy_link')}
				</Link>
			</p>
		</div>
	);
}

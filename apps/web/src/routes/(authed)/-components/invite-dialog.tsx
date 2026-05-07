/**
 * Invite-teammate dialog. Posts to /v1/invites which sends the magic link
 * email and adds the row to the pending-invites table.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
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
import { api, unwrap } from '@/lib/api';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';

const schema = z.object({
	email: z.string().email().max(255),
	role: z.enum(['admin', 'member']),
});
type FormValues = z.infer<typeof schema>;

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

export function InviteDialog({ open, onOpenChange }: Props) {
	const { t } = useTranslation();
	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: { email: '', role: 'member' },
	});

	const create = useMutation({
		mutationFn: (values: FormValues) =>
			unwrap(api.POST('/v1/invites', { body: values })),
		onSuccess: async () => {
			await queryClient.invalidateQueries({ queryKey: queryKeys.invites.all() });
			form.reset();
			onOpenChange(false);
		},
	});

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('team.invite_dialog.title')}</DialogTitle>
					<DialogDescription>{t('team.invite')}</DialogDescription>
				</DialogHeader>
				<Form {...form}>
					<form
						onSubmit={form.handleSubmit((v) => create.mutate(v))}
						className="space-y-4"
						noValidate
					>
						<FormField
							control={form.control}
							name="email"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('team.invite_dialog.email_label')}</FormLabel>
									<FormControl>
										<Input
											type="email"
											autoComplete="off"
											placeholder="teammate@example.com"
											autoFocus
											{...field}
										/>
									</FormControl>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={form.control}
							name="role"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('team.invite_dialog.role_label')}</FormLabel>
									<Select onValueChange={field.onChange} value={field.value}>
										<FormControl>
											<SelectTrigger>
												<SelectValue />
											</SelectTrigger>
										</FormControl>
										<SelectContent>
											<SelectItem value="member">
												{t('team.invite_dialog.role_member')}
											</SelectItem>
											<SelectItem value="admin">
												{t('team.invite_dialog.role_admin')}
											</SelectItem>
										</SelectContent>
									</Select>
									<FormMessage />
								</FormItem>
							)}
						/>
						<DialogFooter>
							<Button
								type="button"
								variant="outline"
								onClick={() => onOpenChange(false)}
								disabled={create.isPending}
							>
								{t('common.cancel')}
							</Button>
							<Button type="submit" disabled={create.isPending}>
								{create.isPending
									? t('common.saving')
									: t('team.invite_dialog.submit')}
							</Button>
						</DialogFooter>
					</form>
				</Form>
			</DialogContent>
		</Dialog>
	);
}

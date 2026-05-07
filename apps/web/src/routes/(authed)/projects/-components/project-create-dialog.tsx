/**
 * Create-project dialog. Slug must match the same regex the API enforces
 * (^[a-z0-9][a-z0-9_-]*$); we mirror it client-side so users get instant
 * feedback rather than a 422 round-trip.
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
	FormDescription,
	FormField,
	FormItem,
	FormLabel,
	FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { api, unwrap } from '@/lib/api';

const SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

const schema = z.object({
	slug: z
		.string()
		.min(1)
		.max(64)
		.regex(SLUG_PATTERN),
	name: z.string().min(1).max(120),
});
type FormValues = z.infer<typeof schema>;

interface Props {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreated: () => void | Promise<void>;
}

export function ProjectCreateDialog({ open, onOpenChange, onCreated }: Props) {
	const { t } = useTranslation();
	const form = useForm<FormValues>({
		resolver: zodResolver(schema),
		mode: 'onTouched',
		defaultValues: { slug: '', name: '' },
	});

	const create = useMutation({
		mutationFn: (values: FormValues) =>
			unwrap(
				api.POST('/v1/projects', {
					body: { slug: values.slug, name: values.name },
				}),
			),
		onSuccess: async () => {
			await onCreated();
			form.reset();
			onOpenChange(false);
		},
	});

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{t('projects.create_dialog.title')}</DialogTitle>
					<DialogDescription>{t('projects.title')}</DialogDescription>
				</DialogHeader>
				<Form {...form}>
					<form
						onSubmit={form.handleSubmit((v) => create.mutate(v))}
						className="space-y-4"
						noValidate
					>
						<FormField
							control={form.control}
							name="slug"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('projects.create_dialog.slug_label')}</FormLabel>
									<FormControl>
										<Input
											placeholder="demo"
											autoFocus
											className="font-mono"
											{...field}
										/>
									</FormControl>
									<FormDescription>
										{t('projects.create_dialog.slug_help')}
									</FormDescription>
									<FormMessage />
								</FormItem>
							)}
						/>
						<FormField
							control={form.control}
							name="name"
							render={({ field }) => (
								<FormItem>
									<FormLabel>{t('projects.create_dialog.name_label')}</FormLabel>
									<FormControl>
										<Input placeholder="Demo Project" {...field} />
									</FormControl>
									<FormDescription>
										{t('projects.create_dialog.name_help')}
									</FormDescription>
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
								{create.isPending ? t('common.saving') : t('common.create')}
							</Button>
						</DialogFooter>
					</form>
				</Form>
			</DialogContent>
		</Dialog>
	);
}

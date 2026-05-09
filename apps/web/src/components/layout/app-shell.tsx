/**
 * Top-bar nav for the authed app shell. Kept tiny — branding, primary
 * navigation, signed-in user dropdown.
 */

import { Link, useNavigate } from '@tanstack/react-router';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CreditCard, LogOut, Settings, ShieldCheck, User as UserIcon, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { api, unwrap } from '@/lib/api';
import { isAdmin, useMe } from '@/lib/auth';
import { getConfig } from '@/lib/config';
import { queryKeys } from '@/lib/query-keys';
import { queryClient } from '@/lib/query-client';

export function AppShell({ children }: { children: React.ReactNode }) {
	const { t } = useTranslation();
	const { data: me } = useMe();
	const navigate = useNavigate();

	const logout = useMutation({
		mutationFn: () => unwrap(api.POST('/v1/auth/logout')),
		onSuccess: async () => {
			// Drop every cached auth response, including /v1/me.
			queryClient.removeQueries({ queryKey: queryKeys.me() });
			await navigate({ to: '/login' });
		},
	});

	if (!me) {
		// The (authed) layout's beforeLoad already redirects unauthenticated
		// users — this branch only runs during the brief window where the
		// query is invalidating. Render nothing instead of flashing.
		return null;
	}

	return (
		<div className="min-h-screen flex flex-col">
			<header className="border-b sticky top-0 z-10 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
				<div className="mx-auto max-w-6xl flex items-center justify-between gap-4 px-6 h-14">
					<Link
						to="/projects"
						className="flex items-center gap-2 text-sm font-semibold tracking-tight"
					>
						<span className="inline-block size-2.5 rounded-full bg-emerald-500" />
						feedbot
					</Link>
					<nav className="flex items-center gap-1 text-sm">
						<Button asChild variant="ghost" size="sm">
							<Link to="/projects" activeProps={{ className: 'bg-accent' }}>
								{t('nav.projects')}
							</Link>
						</Button>
						{isAdmin(me.user.role) && (
							<Button asChild variant="ghost" size="sm">
								<Link to="/team" activeProps={{ className: 'bg-accent' }}>
									{t('nav.team')}
								</Link>
							</Button>
						)}
					</nav>
					<DropdownMenu>
						<DropdownMenuTrigger asChild>
							<Button variant="ghost" size="sm" className="font-mono text-xs">
								{me.user.email}
							</Button>
						</DropdownMenuTrigger>
						<DropdownMenuContent align="end">
							<DropdownMenuLabel className="font-normal text-muted-foreground">
								{t('common.signed_in_as', { email: me.user.email })}
							</DropdownMenuLabel>
							<DropdownMenuSeparator />
							<DropdownMenuItem asChild>
								<Link to="/security" className="cursor-pointer">
									<ShieldCheck className="mr-2 size-4" />
									{t('nav.security')}
								</Link>
							</DropdownMenuItem>
							{isAdmin(me.user.role) && (
								<DropdownMenuItem asChild>
									<Link to="/team" className="cursor-pointer">
										<Users className="mr-2 size-4" />
										{t('nav.team')}
									</Link>
								</DropdownMenuItem>
							)}
							{me.user.role === 'owner' && getConfig().billingEnabled && (
								<DropdownMenuItem asChild>
									<Link to="/billing" className="cursor-pointer">
										<CreditCard className="mr-2 size-4" />
										{t('nav.billing')}
									</Link>
								</DropdownMenuItem>
							)}
							{me.user.role === 'owner' && (
								<DropdownMenuItem asChild>
									<Link to="/account" className="cursor-pointer">
										<UserIcon className="mr-2 size-4" />
										{t('nav.account')}
									</Link>
								</DropdownMenuItem>
							)}
							{me.user.role === 'owner' &&
								getConfig().deployment !== 'cloud' && (
									<DropdownMenuItem asChild>
										<Link to="/settings" className="cursor-pointer">
											<Settings className="mr-2 size-4" />
											{t('nav.settings')}
										</Link>
									</DropdownMenuItem>
								)}
							<DropdownMenuSeparator />
							<DropdownMenuItem
								onClick={() => logout.mutate()}
								disabled={logout.isPending}
								className="cursor-pointer"
							>
								<LogOut className="mr-2 size-4" />
								{t('nav.sign_out')}
							</DropdownMenuItem>
						</DropdownMenuContent>
					</DropdownMenu>
				</div>
			</header>
			<main className="mx-auto w-full max-w-6xl px-6 py-8 flex-1">
				{children}
			</main>
		</div>
	);
}

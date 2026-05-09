/**
 * App shell with a permanent sidebar on md+ and a slide-over drawer on mobile.
 *
 * Layout:
 *   ┌──────────────┬─────────────────────────────────────────┐
 *   │ Sidebar      │ Main                                    │
 *   │ • Brand      │ ┌─────────────────────────────────────┐ │
 *   │ • Primary    │ │ (page content, max-w-6xl, p-8)      │ │
 *   │ • Secondary  │ └─────────────────────────────────────┘ │
 *   │ ─────        │                                         │
 *   │ User card    │                                         │
 *   └──────────────┴─────────────────────────────────────────┘
 *
 * Active link state is driven by TanStack Router's ``activeProps``.
 * Visibility of secondary entries (Team, Billing, Settings) follows the
 * same role/deployment rules the old top-bar enforced.
 */

import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import {
	CreditCard,
	FolderKanban,
	LogOut,
	Menu,
	Settings,
	ShieldCheck,
	User as UserIcon,
	Users,
	X,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Separator } from '@/components/ui/separator';
import { ThemeMenu } from '@/components/theme-toggle';
import { api, unwrap } from '@/lib/api';
import { isAdmin, useMe } from '@/lib/auth';
import { getConfig } from '@/lib/config';
import { queryClient } from '@/lib/query-client';
import { queryKeys } from '@/lib/query-keys';

type NavEntry = {
	to: string;
	label: string;
	icon: React.ComponentType<{ className?: string }>;
	visible: boolean;
};

export function AppShell({ children }: { children: React.ReactNode }) {
	const { t } = useTranslation();
	const { data: me } = useMe();
	const navigate = useNavigate();
	const [mobileOpen, setMobileOpen] = useState(false);

	const logout = useMutation({
		mutationFn: () => unwrap(api.POST('/v1/auth/logout')),
		onSuccess: async () => {
			queryClient.removeQueries({ queryKey: queryKeys.me() });
			await navigate({ to: '/login' });
		},
	});

	// Auto-close the drawer when the route changes (Link click → mobile).
	useEffect(() => {
		setMobileOpen(false);
	}, []);

	if (!me) return null;

	const cfg = getConfig();
	const role = me.user.role;

	const primary: NavEntry[] = [
		{
			to: '/projects',
			label: t('nav.projects'),
			icon: FolderKanban,
			visible: true,
		},
		{
			to: '/team',
			label: t('nav.team'),
			icon: Users,
			visible: isAdmin(role),
		},
	];

	const secondary: NavEntry[] = [
		{
			to: '/account',
			label: t('nav.account'),
			icon: UserIcon,
			visible: role === 'owner',
		},
		{
			to: '/billing',
			label: t('nav.billing'),
			icon: CreditCard,
			visible: role === 'owner' && cfg.billingEnabled,
		},
		{
			to: '/settings',
			label: t('nav.settings'),
			icon: Settings,
			visible: role === 'owner' && cfg.deployment !== 'cloud',
		},
		{
			to: '/security',
			label: t('nav.security'),
			icon: ShieldCheck,
			visible: true,
		},
	];

	const sidebar = (
		<SidebarBody
			productName={cfg.productName}
			email={me.user.email}
			primary={primary}
			secondary={secondary}
			onLogout={() => logout.mutate()}
			loggingOut={logout.isPending}
			onClose={() => setMobileOpen(false)}
		/>
	);

	return (
		<div className="min-h-screen flex bg-muted/30">
			{/* Permanent sidebar on md+. */}
			<aside className="hidden md:flex md:w-60 md:shrink-0 md:flex-col md:border-r md:bg-background">
				{sidebar}
			</aside>

			{/* Mobile drawer */}
			{mobileOpen && (
				<>
					<button
						type="button"
						aria-label={t('nav.close_menu')}
						onClick={() => setMobileOpen(false)}
						className="fixed inset-0 z-30 bg-background/70 backdrop-blur-sm md:hidden"
					/>
					<aside className="fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r bg-background shadow-xl md:hidden">
						{sidebar}
					</aside>
				</>
			)}

			<div className="flex min-w-0 flex-1 flex-col">
				{/* Mobile-only top bar with hamburger. */}
				<header className="md:hidden sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/60">
					<Button
						variant="ghost"
						size="icon"
						aria-label={t('nav.open_menu')}
						onClick={() => setMobileOpen(true)}
					>
						<Menu className="size-5" />
					</Button>
					<Link
						to="/projects"
						className="flex items-center gap-2 text-sm font-semibold tracking-tight"
					>
						<span className="inline-block size-2.5 rounded-full bg-emerald-500" />
						{cfg.productName.toLowerCase()}
					</Link>
					<div className="ml-auto">
						<ThemeMenu />
					</div>
				</header>

				<main className="flex-1">
					<div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-10">
						{children}
					</div>
				</main>
			</div>
		</div>
	);
}

function SidebarBody({
	productName,
	email,
	primary,
	secondary,
	onLogout,
	loggingOut,
	onClose,
}: {
	productName: string;
	email: string;
	primary: NavEntry[];
	secondary: NavEntry[];
	onLogout: () => void;
	loggingOut: boolean;
	onClose: () => void;
}) {
	const { t } = useTranslation();

	return (
		<div className="flex h-full min-h-0 flex-col">
			<div className="flex h-14 items-center justify-between gap-2 border-b px-4">
				<Link
					to="/projects"
					onClick={onClose}
					className="flex items-center gap-2 text-sm font-semibold tracking-tight"
				>
					<span className="inline-block size-2.5 rounded-full bg-emerald-500" />
					<span className="truncate">{productName.toLowerCase()}</span>
				</Link>
				<Button
					variant="ghost"
					size="icon"
					className="md:hidden"
					aria-label={t('nav.close_menu')}
					onClick={onClose}
				>
					<X className="size-4" />
				</Button>
			</div>

			<nav className="flex-1 overflow-y-auto px-2 py-3">
				<ul className="space-y-0.5">
					{primary
						.filter((e) => e.visible)
						.map((e) => (
							<li key={e.to}>
								<NavItem entry={e} onClick={onClose} />
							</li>
						))}
				</ul>

				{secondary.some((e) => e.visible) && (
					<>
						<Separator className="my-3" />
						<ul className="space-y-0.5">
							{secondary
								.filter((e) => e.visible)
								.map((e) => (
									<li key={e.to}>
										<NavItem entry={e} onClick={onClose} />
									</li>
								))}
						</ul>
					</>
				)}
			</nav>

			<Separator />
			<div className="flex items-center gap-2 p-2">
				<DropdownMenu>
					<DropdownMenuTrigger asChild>
						<button
							type="button"
							className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-accent transition-colors"
						>
							<span
								aria-hidden
								className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold uppercase text-primary"
							>
								{email.slice(0, 2)}
							</span>
							<span className="min-w-0 flex-1 truncate font-mono text-xs">
								{email}
							</span>
						</button>
					</DropdownMenuTrigger>
					<DropdownMenuContent align="end" side="top" className="w-56">
						<DropdownMenuLabel className="font-normal text-muted-foreground">
							{t('common.signed_in_as', { email })}
						</DropdownMenuLabel>
						<DropdownMenuSeparator />
						<DropdownMenuItem
							onClick={onLogout}
							disabled={loggingOut}
							className="cursor-pointer"
						>
							<LogOut className="mr-2 size-4" />
							{t('nav.sign_out')}
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
				<ThemeMenu />
			</div>
		</div>
	);
}

function NavItem({ entry, onClick }: { entry: NavEntry; onClick: () => void }) {
	const Icon = entry.icon;
	return (
		<Link
			to={entry.to}
			onClick={onClick}
			className="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
			activeProps={{
				className:
					'flex items-center gap-3 rounded-md px-2 py-1.5 text-sm font-medium bg-accent text-foreground',
			}}
		>
			<Icon className="size-4 shrink-0" />
			<span className="truncate">{entry.label}</span>
		</Link>
	);
}

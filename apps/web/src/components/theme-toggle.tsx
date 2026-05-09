/**
 * Compact theme toggle for the sidebar — single-click cycle between
 * light and dark. The dropdown variant (light / dark / system) lives in
 * the user dropdown menu instead.
 */

import { Monitor, Moon, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useTheme } from '@/lib/theme';

export function ThemeToggleButton() {
	const { t } = useTranslation();
	const { resolved, toggle } = useTheme();
	const Icon = resolved === 'dark' ? Sun : Moon;
	const label =
		resolved === 'dark' ? t('theme.switch_to_light') : t('theme.switch_to_dark');
	return (
		<Button
			type="button"
			variant="ghost"
			size="icon"
			aria-label={label}
			title={label}
			onClick={toggle}
		>
			<Icon className="size-4" />
		</Button>
	);
}

export function ThemeMenu() {
	const { t } = useTranslation();
	const { choice, setTheme } = useTheme();

	const Icon = choice === 'dark' ? Moon : choice === 'light' ? Sun : Monitor;
	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					aria-label={t('theme.menu_label')}
					title={t('theme.menu_label')}
				>
					<Icon className="size-4" />
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				<DropdownMenuItem onClick={() => setTheme('light')}>
					<Sun className="mr-2 size-4" />
					{t('theme.light')}
					{choice === 'light' && <span className="ml-auto text-xs">✓</span>}
				</DropdownMenuItem>
				<DropdownMenuItem onClick={() => setTheme('dark')}>
					<Moon className="mr-2 size-4" />
					{t('theme.dark')}
					{choice === 'dark' && <span className="ml-auto text-xs">✓</span>}
				</DropdownMenuItem>
				<DropdownMenuItem onClick={() => setTheme('system')}>
					<Monitor className="mr-2 size-4" />
					{t('theme.system')}
					{choice === 'system' && <span className="ml-auto text-xs">✓</span>}
				</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}

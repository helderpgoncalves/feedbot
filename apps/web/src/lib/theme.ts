/**
 * Theme management — light / dark / system.
 *
 * The pre-paint script in `index.html` already applied the resolved theme
 * to <html> before React mounts, so `useTheme()` only has to keep the DOM
 * and localStorage in sync once the user toggles.
 *
 * Storage keys:
 *   - `feedbot-theme` = "light" | "dark"      (explicit preference)
 *   - absent                                  (follow system)
 *
 * The DOM contract:
 *   - `<html class="dark">` toggles Tailwind's dark variant.
 *   - `<html data-theme="dark|light">` records the explicit choice; absent
 *     means "system". Useful for CSS that wants to scope to the choice.
 */

import { useEffect, useState } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'feedbot-theme';

function readStored(): ThemeChoice {
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		return v === 'light' || v === 'dark' ? v : 'system';
	} catch {
		return 'system';
	}
}

function systemTheme(): ResolvedTheme {
	if (typeof window === 'undefined' || !window.matchMedia) return 'light';
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolve(choice: ThemeChoice): ResolvedTheme {
	return choice === 'system' ? systemTheme() : choice;
}

function apply(choice: ThemeChoice) {
	const resolved = resolve(choice);
	const root = document.documentElement;
	root.classList.toggle('dark', resolved === 'dark');
	if (choice === 'system') {
		delete root.dataset.theme;
	} else {
		root.dataset.theme = choice;
	}
}

export function useTheme() {
	const [choice, setChoice] = useState<ThemeChoice>(() => readStored());

	// Re-apply when the choice changes (covers React-driven flips).
	useEffect(() => {
		apply(choice);
		try {
			if (choice === 'system') localStorage.removeItem(STORAGE_KEY);
			else localStorage.setItem(STORAGE_KEY, choice);
		} catch {}
	}, [choice]);

	// Track system changes when the user is in 'system' mode.
	useEffect(() => {
		if (choice !== 'system' || typeof window === 'undefined') return;
		const mq = window.matchMedia('(prefers-color-scheme: dark)');
		const handler = () => apply('system');
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	}, [choice]);

	return {
		choice,
		resolved: resolve(choice),
		setTheme: setChoice,
		toggle: () => setChoice((c) => (resolve(c) === 'dark' ? 'light' : 'dark')),
	};
}

/**
 * i18next setup.
 *
 * Only `en` is shipped today, but every component already calls `t()` so
 * adding `pt-PT` (or any other locale) is a single JSON file plus an entry
 * in {@link SUPPORTED_LOCALES}. No component changes needed when more
 * locales come online.
 */

import i18next from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';

/**
 * Currently shipping locales. Add new ones here as JSON files arrive.
 * The shape is checked at runtime by i18next; we keep `en` as the
 * source-of-truth for keys.
 */
export const SUPPORTED_LOCALES = ['en'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = 'en';

void i18next
	.use(LanguageDetector)
	.use(initReactI18next)
	.init({
		resources: {
			en: { translation: en },
		},
		fallbackLng: DEFAULT_LOCALE,
		supportedLngs: SUPPORTED_LOCALES,
		interpolation: {
			// React already escapes by default; double-escaping breaks ' and " in copy.
			escapeValue: false,
		},
		detection: {
			// localStorage > navigator language; never query string (we don't
			// want a `?lng=` to leak around the app).
			order: ['localStorage', 'navigator', 'htmlTag'],
			caches: ['localStorage'],
			lookupLocalStorage: 'feedbot.locale',
		},
		react: {
			// Suspense is supported but we initialise synchronously since the
			// `en` bundle is imported at module scope.
			useSuspense: false,
		},
	});

export default i18next;

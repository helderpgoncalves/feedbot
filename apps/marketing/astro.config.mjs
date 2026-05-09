// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import starlightThemeBlack from 'starlight-theme-black';

const SITE = 'https://feedbot.dev';

// https://astro.build/config
export default defineConfig({
    site: SITE,
    integrations: [
        starlight({
            title: 'Feedbot',
            description:
                'Turn community chat into a structured product backlog. Open-source, self-hostable, MCP-native.',
            logo: {
                src: './src/assets/logo.svg',
                replacesTitle: false,
            },
            social: [
                {
                    icon: 'github',
                    label: 'GitHub',
                    href: 'https://github.com/helderpgoncalves/feedbot',
                },
            ],
            editLink: {
                baseUrl:
                    'https://github.com/helderpgoncalves/feedbot/edit/main/apps/marketing/',
            },
            lastUpdated: true,
            pagination: true,
            plugins: [
                starlightThemeBlack({
                    navLinks: [
                        { label: 'Docs', link: '/introduction/' },
                        { label: 'Pricing', link: '/pricing/' },
                        { label: 'App', link: 'https://app.feedbot.dev' },
                    ],
                    footerText:
                        'Built with Feedbot. Source on [GitHub](https://github.com/helderpgoncalves/feedbot).',
                }),
            ],
            // Starlight serves docs at /docs/* and the landing page lives
            // at the root via src/pages/index.astro (Starlight defers to
            // user pages when present).
            sidebar: [
                {
                    label: 'Get started',
                    items: [
                        { label: 'Introduction', slug: 'introduction' },
                        { label: 'Quickstart (cloud)', slug: 'quickstart-cloud' },
                        { label: 'Quickstart (self-host)', slug: 'quickstart-selfhost' },
                    ],
                },
                {
                    label: 'Self-hosting',
                    items: [
                        { label: 'Install one-liner', slug: 'self-hosting/install' },
                        { label: 'CLI reference', slug: 'self-hosting/cli' },
                        { label: 'Settings UI', slug: 'self-hosting/settings' },
                        { label: 'Backups & restore', slug: 'self-hosting/backups' },
                        { label: 'Upgrades', slug: 'self-hosting/upgrades' },
                    ],
                },
                {
                    label: 'API',
                    items: [
                        { label: 'Authentication', slug: 'api/authentication' },
                        { label: 'Submitting feedback', slug: 'api/feedbacks' },
                        { label: 'MCP server', slug: 'api/mcp' },
                    ],
                },
                {
                    label: 'Telegram bot',
                    autogenerate: { directory: 'telegram' },
                },
                {
                    label: 'Legal',
                    items: [
                        { label: 'Terms of Service', slug: 'legal/terms' },
                        { label: 'Privacy Policy', slug: 'legal/privacy' },
                        { label: 'Cookies', slug: 'legal/cookies' },
                        { label: 'Data Processing Addendum', slug: 'legal/dpa' },
                    ],
                },
            ],
            customCss: [
                '@fontsource/geist-sans/400.css',
                '@fontsource/geist-sans/500.css',
                '@fontsource/geist-sans/600.css',
                '@fontsource/geist-mono/400.css',
                './src/styles/landing.css',
            ],
            head: [
                {
                    tag: 'meta',
                    attrs: {
                        property: 'og:image',
                        content: `${SITE}/og.png`,
                    },
                },
                {
                    tag: 'meta',
                    attrs: {
                        property: 'twitter:image',
                        content: `${SITE}/og.png`,
                    },
                },
                {
                    tag: 'meta',
                    attrs: { name: 'twitter:card', content: 'summary_large_image' },
                },
            ],
        }),
        sitemap(),
    ],
});

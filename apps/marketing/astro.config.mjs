// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
    site: 'https://feedbot.dev',
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
            ],
            customCss: ['./src/styles/landing.css'],
            components: {
                // Use our own homepage; Starlight only takes over /docs/*.
            },
            head: [
                {
                    tag: 'meta',
                    attrs: {
                        property: 'og:image',
                        content: 'https://feedbot.dev/og.png',
                    },
                },
                {
                    tag: 'meta',
                    attrs: { name: 'twitter:card', content: 'summary_large_image' },
                },
            ],
        }),
    ],
});

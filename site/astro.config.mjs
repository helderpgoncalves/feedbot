// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import starlightThemeBlack from 'starlight-theme-black';

const SITE = 'https://feedbot.dev';

export default defineConfig({
	site: SITE,
	integrations: [
		starlight({
			title: 'Feedbot',
			description:
				'Feedback pipeline for product teams. Telegram → structured backlog → Claude Code resolves it. Self-host free, or use the cloud (coming soon).',
			logo: {
				src: './public/favicon.svg',
				replacesTitle: false,
			},
			favicon: '/favicon.svg',
			head: [
				{
					tag: 'meta',
					attrs: { property: 'og:image', content: `${SITE}/og.png` },
				},
				{
					tag: 'meta',
					attrs: { property: 'twitter:image', content: `${SITE}/og.png` },
				},
				{
					tag: 'meta',
					attrs: { name: 'twitter:card', content: 'summary_large_image' },
				},
			],
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/helderpgoncalves/feedbot',
				},
			],
			editLink: {
				baseUrl:
					'https://github.com/helderpgoncalves/feedbot/edit/main/site/',
			},
			lastUpdated: true,
			pagination: true,
			plugins: [
				starlightThemeBlack({
					navLinks: [
						{ label: 'Docs', link: '/getting-started/quickstart/' },
						{ label: 'Self-host', link: '/self-host/' },
						{ label: 'Cloud', link: '/cloud/' },
						{ label: 'Pricing', link: '/pricing/' },
					],
					footerText:
						'Built with Feedbot. Source on [GitHub](https://github.com/helderpgoncalves/feedbot).',
				}),
			],
			sidebar: [
				{
					label: 'Getting started',
					items: [
						{ label: 'Quickstart (5 min)', slug: 'getting-started/quickstart' },
						{ label: 'End-to-end test', slug: 'getting-started/end-to-end' },
					],
				},
				{
					label: 'Architecture',
					items: [{ label: 'Overview', slug: 'architecture/overview' }],
				},
				{
					label: 'Deploy (self-host)',
					items: [
						{ label: 'Coolify', slug: 'deploy/coolify' },
						{ label: 'Generic deployment', slug: 'deploy/deployment' },
					],
				},
				{
					label: 'Cloud',
					items: [{ label: 'Overview', slug: 'cloud/overview' }],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'MCP tools', slug: 'reference/mcp-tools' },
						{ label: 'LLM providers', slug: 'reference/llm-providers' },
						{ label: 'HTTP API', slug: 'reference/api' },
					],
				},
				{
					label: 'Community',
					items: [
						{ label: 'Contributing', slug: 'community/contributing' },
						{ label: 'Code of conduct', slug: 'community/code-of-conduct' },
						{ label: 'Security policy', slug: 'community/security' },
						{ label: 'Changelog', slug: 'community/changelog' },
					],
				},
			],
		}),
		sitemap(),
	],
});

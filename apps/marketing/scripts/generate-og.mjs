#!/usr/bin/env node
/**
 * Generate the social-share OG image at apps/marketing/public/og.png.
 *
 * 1200×630 is the size Twitter/X, Facebook, LinkedIn, Slack, and Discord
 * all crop from. We compose it from a hand-rolled SVG (sharp can render
 * SVG → PNG without a headless browser, which keeps CI fast).
 *
 * Run with `node scripts/generate-og.mjs` from the package root, or via
 * `pnpm gen:og`. We commit the resulting PNG so deploys don't need
 * Node-on-the-server.
 */

import { writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const W = 1200;
const H = 630;

// Black-on-near-white with the same green accent as the favicon.
const SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
	<defs>
		<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
			<stop offset="0%" stop-color="#0a0a0a"/>
			<stop offset="100%" stop-color="#171717"/>
		</linearGradient>
		<style>
			.brand { font: 600 56px ui-sans-serif, -apple-system, "Inter", sans-serif; fill: #fafafa; letter-spacing: -0.02em; }
			.h1 { font: 700 88px ui-sans-serif, -apple-system, "Inter", sans-serif; fill: #fafafa; letter-spacing: -0.03em; }
			.h2 { font: 400 36px ui-sans-serif, -apple-system, "Inter", sans-serif; fill: #a3a3a3; letter-spacing: -0.01em; }
			.tag { font: 500 22px ui-monospace, "Geist Mono", monospace; fill: #10b981; letter-spacing: 0.04em; }
		</style>
	</defs>
	<rect width="${W}" height="${H}" fill="url(#bg)"/>
	<!-- soft grid -->
	<g opacity="0.05" stroke="#fafafa" stroke-width="1">
		<line x1="0" y1="160" x2="${W}" y2="160"/>
		<line x1="0" y1="320" x2="${W}" y2="320"/>
		<line x1="0" y1="480" x2="${W}" y2="480"/>
	</g>
	<!-- brand mark + wordmark -->
	<g transform="translate(96, 88)">
		<circle cx="22" cy="22" r="14" fill="#10b981"/>
		<text x="60" y="38" class="brand">feedbot</text>
	</g>
	<!-- headline -->
	<g transform="translate(96, 250)">
		<text class="h1" y="0">Telegram → product</text>
		<text class="h1" y="98">backlog → resolved.</text>
		<text class="h2" y="170">Open-source. Self-hostable. MCP-native.</text>
	</g>
	<!-- footer chip -->
	<g transform="translate(96, 540)">
		<rect width="220" height="46" rx="23" fill="none" stroke="#10b981" stroke-width="1.5"/>
		<text x="22" y="30" class="tag">feedbot.dev</text>
	</g>
</svg>
`;

const OUT = join(ROOT, 'public', 'og.png');

const png = await sharp(Buffer.from(SVG)).png({ quality: 90 }).toBuffer();
await writeFile(OUT, png);
console.log(`Wrote ${OUT} (${png.length.toLocaleString()} bytes)`);

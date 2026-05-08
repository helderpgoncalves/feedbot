// Starlight 0.36 expects content collections defined here for type-safety
// on doc frontmatter. We use the default Starlight loader; no custom
// schemas needed.
import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
    docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};

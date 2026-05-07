import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import './src/i18n';

// Tear down each test's DOM so component state doesn't leak across tests.
afterEach(() => {
	cleanup();
});

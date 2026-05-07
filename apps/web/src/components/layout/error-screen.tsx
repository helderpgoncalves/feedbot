import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { normalizeError } from '@/lib/errors';

interface ErrorScreenProps {
	error: unknown;
	onReset?: () => void;
}

/**
 * Top-level error fallback used by TanStack Router when a route loader or
 * component throws. Aim is to recover gracefully (a "Try again" button)
 * without leaking stack traces in production.
 */
export function ErrorScreen({ error, onReset }: ErrorScreenProps) {
	const { t } = useTranslation();
	const { message } = normalizeError(error);

	return (
		<div className="min-h-screen flex items-center justify-center p-6">
			<Card className="max-w-md w-full">
				<CardHeader>
					<CardTitle>{t('common.unknown_error')}</CardTitle>
					<CardDescription>{message}</CardDescription>
				</CardHeader>
				<CardContent className="flex justify-end gap-2">
					{onReset && <Button onClick={onReset}>{t('common.confirm')}</Button>}
				</CardContent>
			</Card>
		</div>
	);
}

import { Link } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function NotFound() {
	const { t } = useTranslation();
	return (
		<div className="min-h-screen flex items-center justify-center p-6">
			<Card className="max-w-md w-full">
				<CardHeader>
					<CardTitle>404</CardTitle>
					<CardDescription>{t('errors.404')}</CardDescription>
				</CardHeader>
				<CardContent className="flex justify-end">
					<Button asChild>
						<Link to="/">{t('nav.projects')}</Link>
					</Button>
				</CardContent>
			</Card>
		</div>
	);
}

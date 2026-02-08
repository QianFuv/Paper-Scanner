'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { CalendarDays } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { getCurrentDatabase } from '@/lib/api';

export function WeeklyUpdatesFab() {
  const router = useRouter();

  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    const currentDb = getCurrentDatabase();
    const target = currentDb
      ? `/weekly-updates?db=${encodeURIComponent(currentDb)}`
      : '/weekly-updates';
    router.push(target);
  };

  return (
    <Button
      asChild
      size="icon"
      className="fixed bottom-6 right-6 z-40 h-12 w-12 rounded-full shadow-lg"
      aria-label="Open weekly updates"
      title="Weekly new articles"
    >
      <Link href="/weekly-updates" onClick={handleClick}>
        <CalendarDays className="h-5 w-5" />
      </Link>
    </Button>
  );
}

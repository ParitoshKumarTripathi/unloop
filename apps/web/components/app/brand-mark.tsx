'use client';

import { useI18n } from '@/lib/i18n';
import { cn } from '@/lib/shadcn/utils';

export function BrandMark({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <div
      className={cn('inline-flex max-w-full min-w-0 items-center gap-3', className)}
      aria-label="UNLOOP"
    >
      <svg
        viewBox="0 0 64 64"
        aria-hidden="true"
        className={cn('shrink-0', compact ? 'size-8' : 'size-14')}
      >
        <rect x="8" y="21" width="7" height="22" rx="3.5" fill="#0ea5e9" />
        <rect x="19" y="5" width="7" height="54" rx="3.5" fill="#06b6d4" />
        <rect x="30" y="13" width="7" height="38" rx="3.5" fill="#14b8a6" />
        <rect x="41" y="21" width="7" height="22" rx="3.5" fill="#10b981" />
        <rect x="52" y="17" width="7" height="30" rx="3.5" fill="#22c55e" />
      </svg>
      <div className="min-w-0 text-left">
        <div
          className={cn(
            'text-foreground font-black tracking-[-0.05em]',
            compact ? 'text-lg leading-none' : 'text-3xl leading-none md:text-4xl'
          )}
        >
          UNLOOP
        </div>
        {!compact && (
          <div className="mt-1 font-mono text-[8px] font-bold tracking-[0.16em] text-sky-600 uppercase sm:text-[9px] sm:tracking-[0.28em] dark:text-sky-400">
            {t('brand.tagline', 'Natural Customer Support')}
          </div>
        )}
      </div>
    </div>
  );
}

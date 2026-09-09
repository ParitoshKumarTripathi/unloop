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
        viewBox="0 0 48 48"
        aria-hidden="true"
        className={cn('shrink-0', compact ? 'size-8' : 'size-14')}
      >
        <path
          d="M35.8 12.8A17 17 0 1 0 39.6 31"
          fill="none"
          stroke="#0ea5e9"
          strokeWidth="5"
          strokeLinecap="round"
        />
        <path
          d="m34 7 3 7.5 7.5-3"
          fill="none"
          stroke="#10b981"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M14 24h5l2.5-6 5 12 2.5-6h5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
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
            {t('brand.tagline', 'Resolve. Adapt. Move forward.')}
          </div>
        )}
      </div>
    </div>
  );
}

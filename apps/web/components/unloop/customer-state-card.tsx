'use client';

import { Database, ShieldCheck } from 'lucide-react';
import type { SandboxSnapshot } from '@/hooks/useUnloopState';
import { useI18n } from '@/lib/i18n';

const HIDDEN = new Set(['customer_id']);
const shown = (value: unknown) =>
  value === null || value === undefined || value === '' ? '—' : String(value);

export function CustomerStateCard({ sandbox }: { sandbox: SandboxSnapshot }) {
  const { t, technical, engineText } = useI18n();
  return (
    <section className="via-background rounded-2xl border border-sky-500/35 bg-linear-to-br from-sky-500/10 to-emerald-500/5 p-4 shadow-[0_12px_35px_-24px_rgba(14,165,233,0.9)] ring-1 ring-sky-500/10">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="rounded-lg bg-sky-500/15 p-2 text-sky-700 dark:text-sky-300">
            <Database className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="font-mono text-[9px] font-bold tracking-[0.2em] text-sky-700 uppercase dark:text-sky-300">
              {t('customer.kicker', 'Live backend record')}
            </div>
            <h2 className="text-foreground mt-0.5 text-sm font-black tracking-tight">
              {t('customer.title', 'Current customer state')}
            </h2>
            <div className="text-muted-foreground mt-1 truncate text-[10px]">
              {t('customer.source', 'Authoritative SQLite sandbox')} ·{' '}
              {sandbox.customer?.customer_id ?? 'DEMO-1001'}
            </div>
          </div>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 font-mono text-[8px] font-bold text-emerald-700 uppercase dark:text-emerald-400">
          <ShieldCheck className="size-3" aria-hidden="true" />
          {t('customer.synthetic', 'Synthetic')}
        </span>
      </div>
      <div className="mt-3 space-y-3">
        {sandbox.records.map((record, index) => {
          const idKey = Object.keys(record).find((key) => key.endsWith('_id'));
          const identity = String((idKey && record[idKey]) ?? record.last4 ?? index);
          return (
            <div
              key={identity}
              className="bg-background/75 rounded-xl border border-sky-500/20 p-3 shadow-sm"
            >
              <div className="mb-2 font-mono text-[10px] font-bold tracking-wide text-sky-800 uppercase dark:text-sky-200">
                {technical(idKey ?? 'record')}: {identity}
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
                {Object.entries(record)
                  .filter(([key]) => !HIDDEN.has(key) && !key.endsWith('_id'))
                  .map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt className="text-muted-foreground">{technical(key)}</dt>
                      <dd className="text-right font-medium">{engineText(shown(value))}</dd>
                    </div>
                  ))}
              </dl>
            </div>
          );
        })}
      </div>
      {sandbox.recent_changes[0] && (
        <div className="mt-3 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 shadow-sm">
          <div className="font-mono text-[10px] font-bold tracking-wide text-emerald-700 uppercase dark:text-emerald-400">
            {t('customer.recentChange', 'Recent change')} ·{' '}
            {technical(sandbox.recent_changes[0].action)}
          </div>
          {sandbox.recent_changes[0].fields.map((change) => (
            <div key={change.field} className="mt-1 text-[11px]">
              <span className="text-muted-foreground">{technical(change.field)}: </span>
              <span className="line-through opacity-60">{engineText(shown(change.before))}</span>
              <span className="mx-1">→</span>
              <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                {engineText(shown(change.after))}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

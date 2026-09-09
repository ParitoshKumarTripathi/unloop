'use client';

import type { SandboxSnapshot } from '@/hooks/useUnloopState';
import { useI18n } from '@/lib/i18n';

const HIDDEN = new Set(['customer_id']);
const shown = (value: unknown) =>
  value === null || value === undefined || value === '' ? '—' : String(value);

export function CustomerStateCard({ sandbox }: { sandbox: SandboxSnapshot }) {
  const { technical, engineText } = useI18n();
  return (
    <section className="border-border bg-card rounded-xl border p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] font-bold tracking-[0.16em] uppercase">
            Current customer state
          </div>
          <div className="text-muted-foreground mt-1 text-[11px]">
            Authoritative SQLite sandbox · {sandbox.customer?.customer_id ?? 'DEMO-1001'}
          </div>
        </div>
        <span className="rounded-full bg-emerald-500/10 px-2 py-1 font-mono text-[9px] text-emerald-700 uppercase dark:text-emerald-400">
          Synthetic
        </span>
      </div>
      <div className="mt-3 space-y-3">
        {sandbox.records.map((record, index) => {
          const idKey = Object.keys(record).find((key) => key.endsWith('_id'));
          const identity = String((idKey && record[idKey]) ?? record.last4 ?? index);
          return (
            <div key={identity} className="border-border/70 rounded-lg border p-3">
              <div className="mb-2 font-mono text-[10px] font-semibold tracking-wide uppercase">
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
        <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
          <div className="font-mono text-[10px] font-bold tracking-wide text-emerald-700 uppercase dark:text-emerald-400">
            Recent change · {technical(sandbox.recent_changes[0].action)}
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

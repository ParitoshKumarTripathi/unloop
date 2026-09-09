'use client';

import type {
  Correction,
  Fact,
  HandoffPacket,
  Hypothesis,
  PendingTool,
  ResolutionSnapshot,
  ToolResult,
} from '@/hooks/useUnloopState';
import { useI18n } from '@/lib/i18n';

function Card({
  title,
  count,
  accent,
  children,
}: {
  title: string;
  count?: number | string;
  accent?: 'default' | 'danger' | 'success' | 'warn';
  children: React.ReactNode;
}) {
  const border = {
    default: 'border-border',
    danger: 'border-red-500/40',
    success: 'border-emerald-500/40',
    warn: 'border-amber-500/40',
  }[accent ?? 'default'];

  return (
    <section className={`rounded-md border ${border} bg-background/60 p-2.5`}>
      <header className="mb-1.5 flex items-baseline justify-between">
        <h3 className="text-[11px] font-semibold tracking-wide uppercase">{title}</h3>
        {count !== undefined && (
          <span className="text-muted-foreground font-mono text-[11px]">{count}</span>
        )}
      </header>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-muted-foreground text-[11px] italic">{children}</p>;
}

/** State version and the reason it last changed — the mechanic the whole demo rests on. */
export function VersionCard({ state }: { state: ResolutionSnapshot }) {
  const { t, engineText, technical } = useI18n();
  const lastBump = state.version_log[state.version_log.length - 1];
  return (
    <Card title={t('card.version', 'State version')} count={`v${state.state_version}`}>
      {lastBump ? (
        <div className="space-y-1">
          <div className="font-mono text-[11px]">
            v{lastBump.from_version} → v{lastBump.to_version}
          </div>
          <div className="text-muted-foreground text-[11px]">{engineText(lastBump.reason)}</div>
          {lastBump.invalidated_subjects.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              <span className="text-muted-foreground text-[10px]">
                {t('card.invalidated', 'invalidated:')}
              </span>
              {lastBump.invalidated_subjects.map((s) => (
                <span
                  key={s}
                  className="rounded bg-red-500/10 px-1 font-mono text-[10px] text-red-600 dark:text-red-400"
                >
                  {technical(s)}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <Empty>
          {t('card.noCorrections', 'No corrections yet. Nothing has been invalidated.')}
        </Empty>
      )}
    </Card>
  );
}

const STATUS_STYLE: Record<Hypothesis['status'], string> = {
  ACTIVE: 'bg-muted text-muted-foreground',
  SUPPORTED: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  REJECTED: 'bg-red-500/15 text-red-700 dark:text-red-400 line-through',
  RESOLVED: 'bg-blue-500/15 text-blue-700 dark:text-blue-400',
};

export function HypothesesCard({ hypotheses }: { hypotheses: Hypothesis[] }) {
  const { t, engineText } = useI18n();
  const rejected = hypotheses.filter((h) => h.status === 'REJECTED').length;
  return (
    <Card
      title={t('card.hypotheses', 'Hypotheses')}
      count={`${hypotheses.length} · ${rejected} ${t('card.rejected', 'rejected')}`}
      accent={rejected > 0 ? 'danger' : 'default'}
    >
      <ul className="space-y-1.5">
        {hypotheses.map((h) => (
          <li key={h.id} className="text-[11px]">
            <div className="flex items-start justify-between gap-2">
              <span className={`rounded px-1 font-mono text-[10px] ${STATUS_STYLE[h.status]}`}>
                {engineText(h.status)}
              </span>
              <span className="text-muted-foreground shrink-0 font-mono text-[10px]">
                {h.status === 'REJECTED' && h.rejected_at_version !== null
                  ? `${t('card.rejectedAt', 'rejected @')} v${h.rejected_at_version}`
                  : h.confidence.toFixed(2)}
              </span>
            </div>
            <div className="text-muted-foreground mt-0.5">{engineText(h.label)}</div>
            {h.status === 'REJECTED' && h.contradicting_evidence.length > 0 && (
              <div className="mt-0.5 border-l-2 border-red-500/30 pl-1.5 text-[10px] text-red-600/80 dark:text-red-400/80">
                {engineText(h.contradicting_evidence[h.contradicting_evidence.length - 1].summary)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function FactsCard({ facts }: { facts: Fact[] }) {
  const { t } = useI18n();
  return (
    <Card title={t('card.facts', 'Confirmed facts')} count={facts.length}>
      {facts.length === 0 ? (
        <Empty>{t('card.noFacts', 'Nothing established yet.')}</Empty>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 font-mono text-[11px]">
          {facts.map((f, i) => (
            <FactRow key={`${f.key}-${i}`} fact={f} />
          ))}
        </dl>
      )}
    </Card>
  );
}

function FactRow({ fact }: { fact: Fact }) {
  const { engineText, technical } = useI18n();
  return (
    <>
      <dt className="text-muted-foreground">{technical(fact.key)}</dt>
      <dd>{engineText(fact.value)}</dd>
    </>
  );
}

export function CorrectionsCard({ corrections }: { corrections: Correction[] }) {
  const { t, engineText, technical } = useI18n();
  return (
    <Card
      title={t('card.corrections', 'Caller corrections')}
      count={corrections.length}
      accent={corrections.length > 0 ? 'warn' : 'default'}
    >
      {corrections.length === 0 ? (
        <Empty>
          {t('card.noCallerCorrections', 'The caller has not contradicted anything yet.')}
        </Empty>
      ) : (
        <ul className="space-y-1.5">
          {corrections.map((c) => (
            <li key={c.id} className="text-[11px]">
              <div className="font-medium">{engineText(c.claim)}</div>
              <div className="text-muted-foreground">{engineText(c.evidence)}</div>
              <div className="text-muted-foreground font-mono text-[10px]">
                v{c.state_version_before} → v{c.state_version_after}
                {c.invalidates.length > 0 &&
                  ` · ${t('card.invalidated', 'invalidated:')} ${c.invalidates.map(technical).join(', ')}`}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * The tool timeline. This is the card the stress case lives in: a SUPERSEDED row is a
 * real result, from a real call, that arrived after the caller withdrew the question
 * and was refused the microphone.
 */
export function ToolTimelineCard({
  completed,
  pending,
}: {
  completed: ToolResult[];
  pending: PendingTool[];
}) {
  const { t: tr, technical, engineText } = useI18n();
  const staleCount = completed.filter((t) => t.stale).length;
  return (
    <Card
      title={tr('card.timeline', 'Tool timeline')}
      count={`${completed.length} ${tr('card.done', 'done')} · ${pending.length} ${tr('card.inFlight', 'in flight')} · ${staleCount} ${tr('card.fenced', 'fenced')}`}
      accent={staleCount > 0 ? 'danger' : 'default'}
    >
      <ul className="space-y-1">
        {pending.map((p) => (
          <li key={p.tool_call_id} className="flex items-center gap-2 text-[11px]">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
            <span className="font-mono">{technical(p.tool_name)}</span>
            <span className="text-muted-foreground">
              {tr('card.inFlight', 'in flight')} @v{p.state_version}
              {p.injected_delay_ms > 0 &&
                ` · +${p.injected_delay_ms}ms ${tr('card.injected', 'injected')}`}
            </span>
          </li>
        ))}
        {completed
          .slice()
          .reverse()
          .map((t) => (
            <li key={t.tool_call_id} className="text-[11px]">
              <div className="flex items-center gap-2">
                <span
                  className={[
                    'inline-block h-1.5 w-1.5 rounded-full',
                    t.stale ? 'bg-red-500' : t.status === 'OK' ? 'bg-emerald-500' : 'bg-amber-500',
                  ].join(' ')}
                />
                <span className="font-mono">{technical(t.tool_name)}</span>
                <span className="text-muted-foreground font-mono text-[10px]">
                  {tr('card.issued', 'issued')} @v{t.state_version}
                </span>
                {t.fence_verdict && (
                  <span
                    className={[
                      'rounded px-1 font-mono text-[10px]',
                      t.fence_verdict === 'SUPERSEDED'
                        ? 'bg-red-500/15 text-red-600 dark:text-red-400'
                        : t.fence_verdict === 'RECONCILABLE'
                          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                          : 'bg-muted text-muted-foreground',
                    ].join(' ')}
                  >
                    {engineText(t.fence_verdict)}
                  </span>
                )}
                {t.status !== 'OK' && (
                  <span className="rounded bg-amber-500/15 px-1 font-mono text-[10px] text-amber-700 dark:text-amber-400">
                    {engineText(t.status)}
                  </span>
                )}
              </div>
              {t.stale && (
                <div className="ml-3.5 text-[10px] text-red-600/80 dark:text-red-400/80">
                  {tr('card.fenced', 'fenced')} —{' '}
                  {tr('card.fencedDetail', 'result kept as evidence, refused speech')} (
                  {tr('card.spoke', 'spoke')}:{' '}
                  {t.triggered_speech ? tr('common.yes', 'yes') : tr('common.no', 'no')})
                </div>
              )}
            </li>
          ))}
        {completed.length === 0 && pending.length === 0 && (
          <Empty>{tr('card.noChecks', 'No checks run yet.')}</Empty>
        )}
      </ul>
    </Card>
  );
}

export function LoopCard({ state }: { state: ResolutionSnapshot }) {
  const { t, engineText, technical } = useI18n();
  const triggered = state.loop_score >= 3;
  return (
    <Card
      title={t('card.loop', 'Loop detector')}
      count={`${t('card.score', 'score')} ${state.loop_score}`}
      accent={triggered ? 'danger' : 'default'}
    >
      <div className="space-y-0.5 text-[11px]">
        <div>
          <span className="text-muted-foreground">{t('card.strategy', 'strategy:')} </span>
          <span className="font-mono">{technical(state.current_strategy)}</span>
        </div>
        <div>
          <span className="text-muted-foreground">{t('card.escalation', 'escalation:')} </span>
          <span className="font-mono">{engineText(state.escalation_status)}</span>
        </div>
        {triggered && (
          <div className="text-red-600 dark:text-red-400">
            {t('card.loopDetected', 'Loop detected — strategy must change or escalate.')}
          </div>
        )}
      </div>
    </Card>
  );
}

/** What the caller actually heard, versus what was generated. */
export function HeardCard({ state }: { state: ResolutionSnapshot }) {
  const { t, engineText } = useI18n();
  const records = state.speech_records.slice(-4).reverse();
  return (
    <Card title={t('card.heard', 'What the caller heard')} count={state.speech_records.length}>
      {records.length === 0 ? (
        <Empty>{t('card.notSpoken', 'The agent has not spoken yet.')}</Empty>
      ) : (
        <ul className="space-y-1.5">
          {records.map((r) => (
            <li key={r.speech_id} className="text-[11px]">
              <div className="flex items-center gap-2">
                <span
                  className={[
                    'rounded px-1 font-mono text-[10px]',
                    r.heard_status === 'INTERRUPTED'
                      ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                      : r.heard_status === 'COMPLETED'
                        ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                        : 'bg-muted text-muted-foreground',
                  ].join(' ')}
                >
                  {engineText(r.heard_status)}
                </span>
                <span className="text-muted-foreground font-mono text-[10px]">
                  @v{r.state_version}
                  {r.aligned && ` · ${t('card.wordAligned', 'word-aligned')}`}
                </span>
              </div>
              {r.heard_text && (
                <div className="text-muted-foreground mt-0.5">&ldquo;{r.heard_text}&rdquo;</div>
              )}
              {r.heard_status === 'INTERRUPTED' && !r.heard_text && (
                <div className="text-muted-foreground mt-0.5 text-[10px] italic">
                  {t(
                    'card.cutBeforeAudio',
                    'cut before any audio reached the caller — not counted as communicated'
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** The structured handoff. The point is that it is state, not a transcript. */
export function HandoffCard({ handoff }: { handoff: HandoffPacket }) {
  const { t, engineText, technical } = useI18n();
  const hasContent =
    handoff.confirmed.length > 0 || handoff.rejected.length > 0 || handoff.attempted.length > 0;
  return (
    <Card
      title={t('card.handoff', 'Handoff packet')}
      count={handoff.case_id ?? t('card.notCreated', 'not created')}
      accent={handoff.case_id ? 'success' : 'default'}
    >
      {!hasContent ? (
        <Empty>{t('card.nothingToHandoff', 'Nothing to hand over yet.')}</Empty>
      ) : (
        <div className="space-y-1.5 text-[11px]">
          {handoff.confirmed.length > 0 && (
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">
                {t('card.confirmed', 'confirmed')}
              </div>
              <div className="font-mono text-[10px]">
                {handoff.confirmed
                  .map((c) => `${technical(c.key)}=${engineText(c.value)}`)
                  .join(' · ')}
              </div>
            </div>
          )}
          {handoff.rejected.length > 0 && (
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">
                {t('card.ruledOut', 'ruled out')}
              </div>
              {handoff.rejected.map((r) => (
                <div key={r.id}>
                  <span className="line-through">{engineText(r.label)}</span>
                  {r.because[0] && (
                    <span className="text-muted-foreground"> — {engineText(r.because[0])}</span>
                  )}
                </div>
              ))}
            </div>
          )}
          {handoff.conflicts.length > 0 && (
            <div>
              <div className="text-[10px] text-amber-600 uppercase">
                {t('card.conflicts', 'conflicts')}
              </div>
              {handoff.conflicts.map((c, i) => (
                <div key={i} className="text-amber-700 dark:text-amber-400">
                  {engineText(c)}
                </div>
              ))}
            </div>
          )}
          {handoff.open_questions.length > 0 && (
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">
                {t('card.open', 'open')}
              </div>
              {handoff.open_questions.slice(0, 3).map((q, i) => (
                <div key={i} className="text-muted-foreground">
                  {engineText(q)}
                </div>
              ))}
            </div>
          )}
          <div>
            <span className="text-muted-foreground text-[10px] uppercase">
              {t('card.routedTo', 'routed to ')}{' '}
            </span>
            <span className="font-medium">{engineText(handoff.recommended_destination)}</span>
          </div>
          {handoff.stale_results_fenced > 0 && (
            <div className="font-mono text-[10px] text-red-600 dark:text-red-400">
              {handoff.stale_results_fenced}{' '}
              {handoff.stale_results_fenced === 1
                ? t('card.staleResult', 'stale result')
                : t('card.staleResults', 'stale results')}{' '}
              {t('card.fencedThisCall', 'fenced this call')}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

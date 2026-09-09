'use client';

import { CustomerStateCard } from '@/components/unloop/customer-state-card';
import {
  CorrectionsCard,
  FactsCard,
  HandoffCard,
  HeardCard,
  HypothesesCard,
  LoopCard,
  ToolTimelineCard,
  VersionCard,
} from '@/components/unloop/resolution-cards';
import { SpeechBadge } from '@/components/unloop/speech-badge';
import { useUnloopState } from '@/hooks/useUnloopState';
import { useI18n } from '@/lib/i18n';

/**
 * The judge-facing panel.
 *
 * Everything shown is streamed from the Python worker's deterministic engine. The
 * panel is a viewer: it renders state, it does not compute it. Test controls can
 * inject timing/failure conditions or restore the deterministic SQLite seed.
 */
export function DebugPanel({ demoMode = true }: { demoMode?: boolean }) {
  const { data, connected, setToolDelay, clearDelays, resetDemoData } = useUnloopState();
  const { t, engineText, technical, isHindi } = useI18n();

  if (!connected || !data) {
    return (
      <aside className="border-border bg-muted/20 flex h-full w-full flex-col gap-3 overflow-y-auto border-l p-3">
        <SpeechBadge speech={null} />
        <div className="border-muted-foreground/30 text-muted-foreground rounded-md border border-dashed p-4 text-center text-[11px]">
          {t('debug.waiting', 'Waiting for the agent to publish its resolution state.')}
          <div className="mt-1.5">{t('debug.start', 'Start a call to begin.')}</div>
        </div>
      </aside>
    );
  }

  const { state, speech, fixture, handoff, sandbox } = data;
  const currentDelay = fixture.tool_delays_ms[fixture.primary_delay_tool] ?? 0;

  return (
    <aside className="border-border bg-muted/20 flex h-full w-full flex-col gap-2.5 overflow-y-auto border-l p-3">
      <CustomerStateCard sandbox={sandbox} />
      <SpeechBadge speech={speech} />

      <div className="border-border bg-background/60 rounded-md border p-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold tracking-wide uppercase">
            {t('debug.issue', 'Issue')}
          </div>
          <div className="bg-muted rounded-full px-2 py-0.5 font-mono text-[9px] tracking-wider uppercase">
            {engineText(
              fixture.domains.find((d) => d.id === fixture.domain)?.label ?? fixture.domain
            )}
          </div>
        </div>
        <div className="text-muted-foreground mt-0.5 text-[11px]">
          {engineText(state.issue_summary)}
        </div>
        <div className="text-muted-foreground mt-1 font-mono text-[10px]">
          {isHindi ? technical(fixture.fixture_id) : fixture.fixture_id} · {t('debug.turn', 'turn')}{' '}
          {state.turn} · {t('debug.session', 'session')} {state.session_id.slice(0, 12)}
        </div>
      </div>

      <VersionCard state={state} />
      <ToolTimelineCard completed={state.completed_tools} pending={state.pending_tools} />
      <HypothesesCard hypotheses={state.hypotheses} />
      <CorrectionsCard corrections={state.user_corrections} />
      <FactsCard facts={state.confirmed_facts} />
      <HeardCard state={state} />
      <LoopCard state={state} />
      <HandoffCard handoff={handoff} />

      {demoMode && (
        <DemoControls
          currentDelay={currentDelay}
          onSetDelay={(ms) => setToolDelay(fixture.primary_delay_tool, ms)}
          onClear={clearDelays}
          onReset={resetDemoData}
          fixtureLabel={fixture.label}
          localizedTool={technical(fixture.primary_delay_tool)}
        />
      )}
    </aside>
  );
}

/**
 * Demo controls.
 *
 * These never write a transcript, force a hypothesis, or fabricate a successful
 * result. They control stress timing and deterministically restore synthetic records.
 */
function DemoControls({
  currentDelay,
  onSetDelay,
  onClear,
  onReset,
  fixtureLabel,
  localizedTool,
}: {
  currentDelay: number;
  onSetDelay: (ms: number) => void;
  onClear: () => void;
  onReset: () => void;
  fixtureLabel: string;
  localizedTool: string;
}) {
  const { t, engineText } = useI18n();
  return (
    <section className="border-border bg-background/40 rounded-md border border-dashed p-2.5">
      <h3 className="text-[11px] font-semibold tracking-wide uppercase">
        {t('debug.demoControls', 'Demo controls')}
      </h3>
      <p className="text-muted-foreground mt-0.5 text-[10px]">
        {t('debug.demoHelp', 'Sets fixture conditions only. Cannot script the conversation.')}
      </p>

      <div className="mt-2">
        <div className="text-muted-foreground font-mono text-[10px] uppercase">
          {localizedTool} {t('debug.delay', 'delay')}
        </div>
        <div className="mt-1 flex gap-1">
          {[0, 3000, 5000].map((ms) => (
            <button
              key={ms}
              type="button"
              onClick={() => onSetDelay(ms)}
              className={[
                'rounded border px-2 py-1 font-mono text-[10px] transition-colors',
                currentDelay === ms
                  ? 'border-foreground bg-foreground text-background'
                  : 'border-border hover:bg-muted',
              ].join(' ')}
            >
              {ms === 0 ? t('debug.none', 'none') : `${ms / 1000}s`}
            </button>
          ))}
          <button
            type="button"
            onClick={onClear}
            className="border-border hover:bg-muted rounded border px-2 py-1 text-[10px]"
          >
            {t('debug.clear', 'clear all')}
          </button>
        </div>
      </div>

      <div className="border-border/50 mt-2 border-t pt-1.5">
        <div className="text-muted-foreground text-[10px] uppercase">
          {t('debug.scenario', 'demo preset')}
        </div>
        <div className="mt-0.5 text-[11px]">{engineText(fixtureLabel)}</div>
        <p className="text-muted-foreground mt-1 text-[10px]">
          {t(
            'debug.scenarioHelp',
            'This test profile injects deterministic timing or failure conditions. SQLite customer records and the conversational goal remain separate.'
          )}
        </p>
      </div>
      <button
        type="button"
        onClick={onReset}
        className="border-border hover:bg-muted mt-2 w-full rounded border px-2 py-1 text-[10px]"
      >
        Reset synthetic customer data
      </button>
    </section>
  );
}

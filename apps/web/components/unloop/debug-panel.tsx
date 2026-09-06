'use client';

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

/**
 * The judge-facing panel.
 *
 * Everything shown is streamed from the Python worker's deterministic engine. The
 * panel is a viewer: it renders state, it does not compute it. The only thing it can
 * send back is a fixture condition (see DemoControls), which changes *when* a real
 * tool result arrives, never *what* it says.
 */
export function DebugPanel({ demoMode = true }: { demoMode?: boolean }) {
  const { data, connected, setToolDelay, clearDelays } = useUnloopState();

  if (!connected || !data) {
    return (
      <aside className="border-border bg-muted/20 flex h-full w-full flex-col gap-3 overflow-y-auto border-l p-3">
        <SpeechBadge speech={null} />
        <div className="border-muted-foreground/30 text-muted-foreground rounded-md border border-dashed p-4 text-center text-[11px]">
          Waiting for the agent to publish its resolution state.
          <div className="mt-1.5">Start a call to begin.</div>
        </div>
      </aside>
    );
  }

  const { state, speech, fixture, handoff } = data;
  const currentDelay = fixture.tool_delays_ms['get_card_status'] ?? 0;

  return (
    <aside className="border-border bg-muted/20 flex h-full w-full flex-col gap-2.5 overflow-y-auto border-l p-3">
      <SpeechBadge speech={speech} />

      <div className="border-border bg-background/60 rounded-md border p-2.5">
        <div className="text-[11px] font-semibold tracking-wide uppercase">Issue</div>
        <div className="text-muted-foreground mt-0.5 text-[11px]">{state.issue_summary}</div>
        <div className="text-muted-foreground mt-1 font-mono text-[10px]">
          {fixture.fixture_id} · turn {state.turn} · session {state.session_id.slice(0, 12)}
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
          onSetDelay={(ms) => setToolDelay('get_card_status', ms)}
          onClear={clearDelays}
          fixtureLabel={fixture.label}
        />
      )}
    </aside>
  );
}

/**
 * Demo controls.
 *
 * These set fixture conditions only. There is deliberately no control that writes a
 * transcript, forces a hypothesis, or changes what a tool returns — everything a judge
 * sees is the real engine reacting to a real (synthetic) backend. The only lever is
 * how long a tool takes, which is what makes the interruption window reproducible.
 */
function DemoControls({
  currentDelay,
  onSetDelay,
  onClear,
  fixtureLabel,
}: {
  currentDelay: number;
  onSetDelay: (ms: number) => void;
  onClear: () => void;
  fixtureLabel: string;
}) {
  return (
    <section className="border-border bg-background/40 rounded-md border border-dashed p-2.5">
      <h3 className="text-[11px] font-semibold tracking-wide uppercase">Demo controls</h3>
      <p className="text-muted-foreground mt-0.5 text-[10px]">
        Sets fixture conditions only. Cannot script the conversation.
      </p>

      <div className="mt-2">
        <div className="text-muted-foreground text-[10px] uppercase">get_card_status delay</div>
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
              {ms === 0 ? 'none' : `${ms / 1000}s`}
            </button>
          ))}
          <button
            type="button"
            onClick={onClear}
            className="border-border hover:bg-muted rounded border px-2 py-1 text-[10px]"
          >
            clear all
          </button>
        </div>
      </div>

      <div className="border-border/50 mt-2 border-t pt-1.5">
        <div className="text-muted-foreground text-[10px] uppercase">scenario</div>
        <div className="mt-0.5 text-[11px]">{fixtureLabel}</div>
        <p className="text-muted-foreground mt-1 text-[10px]">
          Scenario is chosen by the worker at call start via <code>UNLOOP_FIXTURE</code>. Restart
          the agent to change it.
        </p>
      </div>
    </section>
  );
}

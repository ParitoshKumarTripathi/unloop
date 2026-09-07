'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { RoomEvent } from 'livekit-client';
import { useSessionContext } from '@livekit/components-react';

/**
 * Live resolution state, streamed from the Python agent over the LiveKit data channel.
 *
 * The browser is a *viewer* of this state, never an author. Everything rendered in the
 * debug panel is produced by the deterministic engine in the worker; the panel cannot
 * set a hypothesis, write a transcript, or change what a tool returns. The only thing
 * it can send back is a fixture condition (which scenario, how slow a tool is).
 */

export const STATE_TOPIC = 'unloop.state';
export const CONTROL_TOPIC = 'unloop.control';

export interface Hypothesis {
  id: string;
  label: string;
  status: 'ACTIVE' | 'SUPPORTED' | 'REJECTED' | 'RESOLVED';
  confidence: number;
  branch: string;
  times_suggested_to_user: number;
  rejected_at_version: number | null;
  supporting_evidence: Evidence[];
  contradicting_evidence: Evidence[];
}

export interface Evidence {
  id: string;
  source: 'TOOL' | 'USER' | 'SYSTEM';
  summary: string;
  observed_at_version: number;
  supports: boolean;
}

export interface ToolResult {
  tool_call_id: string;
  tool_name: string;
  subject: string;
  /** The version the call was ISSUED under, not the version it returned into. */
  state_version: number;
  status: 'OK' | 'ERROR' | 'TIMEOUT';
  payload: Record<string, unknown>;
  error: string | null;
  stale: boolean;
  triggered_speech: boolean;
  fence_verdict: 'FRESH' | 'RECONCILABLE' | 'SUPERSEDED' | null;
  started_at: number;
  completed_at: number | null;
}

export interface PendingTool {
  tool_call_id: string;
  tool_name: string;
  subject: string;
  state_version: number;
  injected_delay_ms: number;
}

export interface Correction {
  id: string;
  target_hypothesis: string | null;
  claim: string;
  evidence: string;
  invalidates: string[];
  state_version_before: number;
  state_version_after: number;
}

export interface VersionBump {
  from_version: number;
  to_version: number;
  reason: string;
  correction_id: string | null;
  invalidated_subjects: string[];
}

export interface Fact {
  key: string;
  value: string;
  source: string;
}

export interface SpeechRecord {
  speech_id: string;
  state_version: number;
  text: string;
  asserted_hypotheses: string[];
  heard_status: 'NOT_STARTED' | 'PARTIAL' | 'COMPLETED' | 'INTERRUPTED';
  heard_text: string;
  aligned: boolean;
}

export interface ResolutionSnapshot {
  session_id: string;
  case_id: string | null;
  state_version: number;
  turn: number;
  issue_type: string;
  issue_summary: string;
  current_strategy: string;
  loop_score: number;
  escalation_status: string;
  escalation_reason: string | null;
  confirmed_facts: Fact[];
  user_corrections: Correction[];
  hypotheses: Hypothesis[];
  rejected_hypotheses: string[];
  attempted_actions: string[];
  pending_tools: PendingTool[];
  completed_tools: ToolResult[];
  stale_tool_count: number;
  version_log: VersionBump[];
  speech_records: SpeechRecord[];
  interrupted_agent_turns: string[];
}

export interface SpeechProvider {
  provider: string;
  model: string;
  speaker: string;
  language: string;
  transport: string;
  base_url: string;
  resolved_endpoint: string;
  region: string;
  sample_rate: number;
  segment: string;
  audio_format: string;
}

export interface HandoffPacket {
  case_id: string | null;
  issue: string;
  confirmed: Array<{ key: string; value: string; source: string }>;
  rejected: Array<{ id: string; label: string; because: string[] }>;
  observed: Array<{ id: string; label: string; summary: string }>;
  user_corrections: Array<{ claim: string; evidence: string; target: string | null }>;
  attempted: string[];
  open_questions: string[];
  recommended_destination: string;
  conflicts: string[];
  stale_results_fenced: number;
}

export interface FixtureInfo {
  domain: string;
  fixture_id: string;
  label: string;
  primary_delay_tool: string;
  tool_delays_ms: Record<string, number>;
  available: Array<{ fixture_id: string; domain: string; label: string; description: string }>;
  domains: Array<{ id: string; label: string; issue: string; fixture_id: string }>;
}

export interface UnloopPayload {
  type: 'state';
  state: ResolutionSnapshot;
  speech: SpeechProvider;
  fixture: FixtureInfo;
  loop: { score: number; strategy: string };
  handoff: HandoffPacket;
}

export interface UnloopState {
  data: UnloopPayload | null;
  /** True once at least one snapshot has arrived from the agent. */
  connected: boolean;
  /** Wall-clock ms of the last snapshot, for a staleness indicator. */
  lastUpdate: number | null;
  setToolDelay: (tool: string, delayMs: number) => void;
  clearDelays: () => void;
}

const decoder = new TextDecoder();
const encoder = new TextEncoder();

export function useUnloopState(): UnloopState {
  const session = useSessionContext();
  const room = session.room;
  const [data, setData] = useState<UnloopPayload | null>(null);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const roomRef = useRef(room);
  roomRef.current = room;

  useEffect(() => {
    if (!room) return;

    const onData = (
      payload: Uint8Array,
      _participant?: unknown,
      _kind?: unknown,
      topic?: string
    ) => {
      if (topic !== STATE_TOPIC) return;
      try {
        const parsed = JSON.parse(decoder.decode(payload)) as UnloopPayload;
        if (parsed?.type === 'state') {
          setData(parsed);
          setLastUpdate(Date.now());
        }
      } catch {
        // A malformed frame must never take down the panel. The agent is the source
        // of truth; the panel just stops updating until the next good frame.
      }
    };

    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  // Reset when the session ends, so a stale snapshot from a previous call is never
  // shown next to a fresh one.
  useEffect(() => {
    if (!session.isConnected) {
      setData(null);
      setLastUpdate(null);
    }
  }, [session.isConnected]);

  const publishControl = useCallback((message: Record<string, unknown>) => {
    const current = roomRef.current;
    if (!current) return;
    void current.localParticipant.publishData(encoder.encode(JSON.stringify(message)), {
      topic: CONTROL_TOPIC,
      reliable: true,
    });
  }, []);

  const setToolDelay = useCallback(
    (tool: string, delayMs: number) => {
      publishControl({ action: 'set_tool_delay', tool, delay_ms: delayMs });
    },
    [publishControl]
  );

  const clearDelays = useCallback(() => {
    publishControl({ action: 'clear_delays' });
  }, [publishControl]);

  return {
    data,
    connected: data !== null,
    lastUpdate,
    setToolDelay,
    clearDelays,
  };
}

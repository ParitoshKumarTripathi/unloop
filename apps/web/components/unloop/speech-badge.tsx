'use client';

import type { SpeechProvider } from '@/hooks/useUnloopState';
import { useI18n } from '@/lib/i18n';

/**
 * The active speech provider, read from the agent's live configuration.
 *
 * Deliberately not a hard-coded "SPEECH: RIME" string. Every field here comes from
 * the running worker's config, so if the provider, model, voice, endpoint or transport
 * were ever changed, this badge would say so. A badge that cannot be wrong is not
 * evidence of anything.
 */
export function SpeechBadge({ speech }: { speech: SpeechProvider | null }) {
  const { t } = useI18n();
  if (!speech) {
    return (
      <div className="border-muted-foreground/40 text-muted-foreground rounded-md border border-dashed px-3 py-2 text-xs">
        {t('speech.title', 'SPEECH')}:{' '}
        <span className="font-mono">{t('speech.waiting', 'waiting for agent…')}</span>
      </div>
    );
  }

  const isRime = speech.provider?.toLowerCase() === 'rime';

  return (
    <div
      className={[
        'rounded-md border px-3 py-2',
        isRime ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-amber-500/60 bg-amber-500/10',
      ].join(' ')}
    >
      <div className="flex items-center gap-2">
        <span
          className={[
            'inline-block h-2 w-2 rounded-full',
            isRime ? 'bg-emerald-500' : 'bg-amber-500',
          ].join(' ')}
        />
        <span className="text-xs font-semibold tracking-wide uppercase">
          {t('speech.title', 'Speech')}: {speech.provider}
        </span>
        {!isRime && (
          <span className="text-[10px] font-medium text-amber-600 uppercase">
            {t('speech.notJudged', 'not the judged path')}
          </span>
        )}
      </div>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px] leading-tight">
        <dt className="text-muted-foreground">{t('speech.model', 'model')}</dt>
        <dd>{speech.model}</dd>
        <dt className="text-muted-foreground">{t('speech.voice', 'voice')}</dt>
        <dd>{speech.speaker}</dd>
        <dt className="text-muted-foreground">{t('speech.language', 'lang')}</dt>
        <dd>
          {speech.label} ({speech.mode})
        </dd>
        <dt className="text-muted-foreground">STT</dt>
        <dd>{speech.stt_language}</dd>
        <dt className="text-muted-foreground">Rime</dt>
        <dd>{speech.language}</dd>
        <dt className="text-muted-foreground">{t('speech.transport', 'transport')}</dt>
        <dd>{speech.transport}</dd>
        <dt className="text-muted-foreground">{t('speech.rate', 'rate')}</dt>
        <dd>
          {speech.sample_rate} Hz · {speech.audio_format}
        </dd>
        <dt className="text-muted-foreground">{t('speech.segment', 'segment')}</dt>
        <dd>{speech.segment}</dd>
        <dt className="text-muted-foreground">{t('speech.region', 'region')}</dt>
        <dd>{speech.region}</dd>
      </dl>

      <div className="border-border/50 mt-2 border-t pt-1.5">
        <div className="text-muted-foreground text-[10px] uppercase">
          {t('speech.endpoint', 'resolved endpoint')}
        </div>
        <div className="text-muted-foreground mt-0.5 font-mono text-[10px] break-all">
          {speech.resolved_endpoint}
        </div>
      </div>
    </div>
  );
}

import {
  Building2,
  Landmark,
  PhoneCall,
  Scissors,
  ShoppingBag,
  UtensilsCrossed,
} from 'lucide-react';
import { BrandMark } from '@/components/app/brand-mark';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
  selectedDomain: string;
  onSelectDomain: (domain: string) => void;
  testMode: boolean;
  selectedFixture: string;
  onSelectFixture: (fixture: string) => void;
  selectedLanguage: string;
  onSelectLanguage: (language: string) => void;
}

const SUPPORT_DOMAINS = [
  ['banking', 'Banking', 'Account and payment support', Landmark],
  ['ecommerce', 'E-commerce', 'Order and refund support', ShoppingBag],
  ['restaurant', 'Restaurant', 'Existing reservation support', UtensilsCrossed],
  ['salon', 'Salon', 'Existing appointment support', Scissors],
  ['hotel', 'Hotel', 'Existing booking support', Building2],
] as const;

const SUPPORT_LANGUAGES = [
  ['english', 'English', 'English conversation'],
  ['hindi', 'हिन्दी', 'हिन्दी में बातचीत'],
] as const;

const TEST_FIXTURES: Record<string, readonly (readonly [string, string])[]> = {
  banking: [
    ['otp_slow_tool', 'Slow OTP lookup + interruption'],
    ['otp_normal', 'Normal OTP delivery failure'],
    ['otp_correction', 'OTP correction'],
    ['otp_escalation', 'OTP escalation'],
    ['otp_tool_failure', 'OTP tool failure'],
  ],
  ecommerce: [['ecommerce_refund_missing', 'Refund backend baseline']],
  restaurant: [['restaurant_missing_reservation', 'Restaurant backend baseline']],
  salon: [['salon_appointment_changed', 'Salon backend baseline']],
  hotel: [['hotel_booking_conflict', 'Hotel backend baseline']],
};

export const WelcomeView = ({
  startButtonText,
  onStartCall,
  selectedDomain,
  onSelectDomain,
  testMode,
  selectedFixture,
  onSelectFixture,
  selectedLanguage,
  onSelectLanguage,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const selected = SUPPORT_DOMAINS.find(([id]) => id === selectedDomain);
  const { t } = useI18n();
  const scenarioText = (id: string, field: string, fallback: string) =>
    t(`scenario.${id}${field}`, fallback);

  return (
    <div
      ref={ref}
      className="w-full max-w-[100vw] min-w-0 overflow-x-hidden px-4 py-6 md:px-5 md:py-8"
    >
      <section className="bg-background mx-auto flex w-full max-w-5xl min-w-0 flex-col items-center justify-center text-center">
        <BrandMark className="mb-5" />

        <h1 className="text-foreground max-w-2xl text-2xl font-semibold tracking-tight md:text-4xl">
          {t('welcome.title', 'Customer support that adapts on the fly.')}
        </h1>
        <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-6 md:text-base">
          {t(
            'welcome.description',
            'Choose a support service, start a call, and describe your issue naturally. The agent can investigate, take action, adapt when corrected, and escalate with context.'
          )}
        </p>

        <div className="mt-6 w-full max-w-full min-w-0 text-left md:mt-8">
          <div className="text-foreground mb-3 text-center text-xs font-semibold tracking-wide uppercase">
            {t('welcome.domain', 'Choose support domain')}
          </div>
          <div className="grid w-full min-w-0 grid-cols-2 gap-2 lg:grid-cols-5">
            {SUPPORT_DOMAINS.map(([id, label, description, Icon]) => {
              const active = id === selectedDomain;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectDomain(id)}
                  className={[
                    'min-h-[82px] min-w-0 overflow-hidden rounded-xl border p-3 text-left transition-all md:min-h-28 md:p-4',
                    active
                      ? 'border-foreground bg-foreground text-background shadow-lg'
                      : 'border-border bg-card hover:border-foreground/40 hover:bg-muted/50',
                  ].join(' ')}
                >
                  <span className="flex items-center gap-2 text-sm font-bold">
                    <Icon className="size-4 shrink-0" strokeWidth={2.25} aria-hidden="true" />
                    {scenarioText(id, '', label)}
                  </span>
                  <span className="mt-1.5 block text-[10px] leading-4 wrap-break-word opacity-70 md:text-[11px]">
                    {scenarioText(id, 'Description', description)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {testMode && (
          <details className="border-border bg-muted/30 mt-5 w-full max-w-md rounded-xl border p-3 text-left">
            <summary className="cursor-pointer text-center font-mono text-xs font-semibold tracking-wide uppercase">
              Demo / Test Controls
            </summary>
            <label className="mt-3 block text-xs">
              Deterministic backend fixture
              <select
                value={selectedFixture}
                onChange={(event) => onSelectFixture(event.target.value)}
                className="border-border bg-card text-foreground mt-2 w-full rounded-lg border px-3 py-2"
              >
                {(TEST_FIXTURES[selectedDomain] ?? []).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-muted-foreground mt-2 text-[11px] leading-4">
              Test mode only: selects backend facts and stress conditions. It never sets the
              conversational goal.
            </p>
          </details>
        )}

        <div className="mt-6 w-full max-w-2xl text-left">
          <div className="text-foreground mb-3 text-center text-xs font-semibold tracking-wide uppercase">
            {t('welcome.language', 'Choose conversation language')}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {SUPPORT_LANGUAGES.map(([id, label, description]) => {
              const active = id === selectedLanguage;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectLanguage(id)}
                  className={[
                    'rounded-xl border px-3 py-3 text-center transition-all',
                    active
                      ? 'border-emerald-500 bg-emerald-500/10 ring-1 ring-emerald-500/30'
                      : 'border-border bg-card hover:border-foreground/40 hover:bg-muted/50',
                  ].join(' ')}
                >
                  <span className="block text-sm font-semibold">{t(`language.${id}`, label)}</span>
                  <span className="mt-1 block text-[10px] leading-4 opacity-65">
                    {t(`language.${id}Description`, description)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <Button
          size="lg"
          onClick={onStartCall}
          className="mt-7 w-full max-w-72 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          <PhoneCall className="size-4" aria-hidden="true" />
          {startButtonText}: {selected && scenarioText(selected[0], '', selected[1])} ·{' '}
          {t(
            `language.${selectedLanguage}`,
            SUPPORT_LANGUAGES.find(([id]) => id === selectedLanguage)?.[1] ?? selectedLanguage
          )}
        </Button>
      </section>
    </div>
  );
};

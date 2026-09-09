import { Button } from '@/components/ui/button';
import { useI18n } from '@/lib/i18n';

function WelcomeImage() {
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="text-fg0 mb-4 size-16"
    >
      <path
        d="M15 24V40C15 40.7957 14.6839 41.5587 14.1213 42.1213C13.5587 42.6839 12.7956 43 12 43C11.2044 43 10.4413 42.6839 9.87868 42.1213C9.31607 41.5587 9 40.7957 9 40V24C9 23.2044 9.31607 22.4413 9.87868 21.8787C10.4413 21.3161 11.2044 21 12 21C12.7956 21 13.5587 21.3161 14.1213 21.8787C14.6839 22.4413 15 23.2044 15 24ZM22 5C21.2044 5 20.4413 5.31607 19.8787 5.87868C19.3161 6.44129 19 7.20435 19 8V56C19 56.7957 19.3161 57.5587 19.8787 58.1213C20.4413 58.6839 21.2044 59 22 59C22.7956 59 23.5587 58.6839 24.1213 58.1213C24.6839 57.5587 25 56.7957 25 56V8C25 7.20435 24.6839 6.44129 24.1213 5.87868C23.5587 5.31607 22.7956 5 22 5ZM32 13C31.2044 13 30.4413 13.3161 29.8787 13.8787C29.3161 14.4413 29 15.2044 29 16V48C29 48.7957 29.3161 49.5587 29.8787 50.1213C30.4413 50.6839 31.2044 51 32 51C32.7956 51 33.5587 50.6839 34.1213 50.1213C34.6839 49.5587 35 48.7957 35 48V16C35 15.2044 34.6839 14.4413 34.1213 13.8787C33.5587 13.3161 32.7956 13 32 13ZM42 21C41.2043 21 40.4413 21.3161 39.8787 21.8787C39.3161 22.4413 39 23.2044 39 24V40C39 40.7957 39.3161 41.5587 39.8787 42.1213C40.4413 42.6839 41.2043 43 42 43C42.7957 43 43.5587 42.6839 44.1213 42.1213C44.6839 41.5587 45 40.7957 45 40V24C45 23.2044 44.6839 22.4413 44.1213 21.8787C43.5587 21.3161 42.7957 21 42 21ZM52 17C51.2043 17 50.4413 17.3161 49.8787 17.8787C49.3161 18.4413 49 19.2044 49 20V44C49 44.7957 49.3161 45.5587 49.8787 46.1213C50.4413 46.6839 51.2043 47 52 47C52.7957 47 53.5587 46.6839 54.1213 46.1213C54.6839 45.5587 55 44.7957 55 44V20C55 19.2044 54.6839 18.4413 54.1213 17.8787C53.5587 17.3161 52.7957 17 52 17Z"
        fill="currentColor"
      />
    </svg>
  );
}

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
  ['banking', 'Banking', 'Account and payment support'],
  ['ecommerce', 'E-commerce', 'Order, return, and refund support'],
  ['restaurant', 'Restaurant', 'Existing reservation support'],
  ['salon', 'Salon', 'Existing appointment support'],
  ['hotel', 'Hotel', 'Existing booking support'],
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
    <div ref={ref} className="w-full px-5 py-8">
      <section className="bg-background mx-auto flex w-full max-w-5xl flex-col items-center justify-center text-center">
        <WelcomeImage />

        <p className="text-muted-foreground font-mono text-[11px] tracking-[0.24em] uppercase">
          {t('brand.kicker', 'Unloop resolution agent')}
        </p>
        <h1 className="text-foreground mt-2 max-w-2xl text-2xl font-semibold tracking-tight md:text-4xl">
          {t('welcome.title', 'Customer support that changes strategy when it is wrong.')}
        </h1>
        <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-6 md:text-base">
          {t(
            'welcome.description',
            'Choose a support service, start a call, and describe your issue naturally. The agent can investigate, take action, adapt when corrected, and escalate with context.'
          )}
        </p>

        <div className="mt-8 w-full text-left">
          <div className="text-foreground mb-3 text-center text-xs font-semibold tracking-wide uppercase">
            {t('welcome.domain', 'Choose support domain')}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {SUPPORT_DOMAINS.map(([id, label, description]) => {
              const active = id === selectedDomain;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectDomain(id)}
                  className={[
                    'min-h-32 rounded-xl border p-4 text-left transition-all',
                    active
                      ? 'border-foreground bg-foreground text-background shadow-lg'
                      : 'border-border bg-card hover:border-foreground/40 hover:bg-muted/50',
                  ].join(' ')}
                >
                  <span className="font-mono text-[10px] tracking-wider uppercase opacity-70">
                    {t('welcome.domainLabel', 'Support domain')}
                  </span>
                  <span className="mt-2 block text-sm font-semibold">
                    {scenarioText(id, '', label)}
                  </span>
                  <span className="mt-2 block text-[11px] leading-4 opacity-70">
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
          className="mt-7 w-72 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
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

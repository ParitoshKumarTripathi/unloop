'use client';

import { useEffect, useMemo, useState } from 'react';
import { TokenSource } from 'livekit-client';
import { useSession, useSessionContext } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { BrandMark } from '@/components/app/brand-mark';
import { ThemeToggle } from '@/components/app/theme-toggle';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { I18nProvider, useI18n } from '@/lib/i18n';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();

  return null;
}

function LocalizedChrome() {
  const { t } = useI18n();
  const { isConnected } = useSessionContext();
  return (
    <>
      <header className="fixed top-0 left-0 z-50 hidden w-full flex-row justify-between p-6 md:flex">
        {isConnected ? <BrandMark compact /> : <div aria-hidden="true" />}
        <span className="text-foreground font-mono text-xs font-bold tracking-wider uppercase">
          {t('chrome.builtWith', 'Built with')}{' '}
          <a
            target="_blank"
            rel="noopener noreferrer"
            href="https://docs.livekit.io/agents"
            className="underline underline-offset-4"
          >
            LiveKit Agents
          </a>
        </span>
      </header>
      <div className="group fixed bottom-0 left-1/2 z-50 mb-2 -translate-x-1/2">
        <ThemeToggle className="translate-y-20 transition-transform delay-150 duration-300 group-hover:translate-y-0" />
      </div>
    </>
  );
}

interface AppProps {
  agentName?: string;
  /** Show the demo/fixture controls in the resolution panel. */
  demoMode?: boolean;
}

export function App({ agentName, demoMode = true }: AppProps) {
  const tokenSource = useMemo(() => TokenSource.endpoint('/api/token'), []);
  const [selectedDomain, setSelectedDomain] = useState('banking');
  const [selectedLanguage, setSelectedLanguage] = useState('english');
  const [testMode, setTestMode] = useState(false);
  const [selectedFixture, setSelectedFixture] = useState('otp_slow_tool');

  const defaultFixtures: Record<string, string> = {
    banking: 'otp_slow_tool',
    ecommerce: 'ecommerce_refund_missing',
    restaurant: 'restaurant_missing_reservation',
    salon: 'salon_appointment_changed',
    hotel: 'hotel_booking_conflict',
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setTestMode(params.get('debug') === 'true' || params.get('demo') === 'true');
  }, []);

  const selectDomain = (domain: string) => {
    setSelectedDomain(domain);
    setSelectedFixture(defaultFixtures[domain] ?? 'otp_slow_tool');
  };

  const session = useSession(tokenSource, {
    ...(agentName ? { agentName } : {}),
    agentMetadata: JSON.stringify({
      domain: selectedDomain,
      language: selectedLanguage,
      ...(testMode ? { fixture: selectedFixture } : {}),
    }),
  });

  return (
    <AgentSessionProvider session={session}>
      <I18nProvider language={selectedLanguage}>
        <LocalizedChrome />
        <AppSetup />
        <main className="min-h-svh w-full max-w-[100vw] overflow-x-hidden overflow-y-auto">
          <ViewController
            demoMode={demoMode}
            selectedDomain={selectedDomain}
            onSelectDomain={selectDomain}
            testMode={testMode}
            selectedFixture={selectedFixture}
            onSelectFixture={setSelectedFixture}
            selectedLanguage={selectedLanguage}
            onSelectLanguage={setSelectedLanguage}
          />
        </main>
        <StartAudioButton
          label={selectedLanguage === 'hindi' ? 'ऑडियो शुरू करें' : 'Start Audio'}
        />
        <Toaster
          icons={{
            warning: <WarningIcon weight="bold" />,
          }}
          position="top-center"
          className="toaster group"
          style={
            {
              '--normal-bg': 'var(--popover)',
              '--normal-text': 'var(--popover-foreground)',
              '--normal-border': 'var(--border)',
            } as React.CSSProperties
          }
        />
      </I18nProvider>
    </AgentSessionProvider>
  );
}

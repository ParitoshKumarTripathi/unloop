'use client';

import { useTheme } from 'next-themes';
import { AnimatePresence, motion } from 'motion/react';
import { useSessionContext } from '@livekit/components-react';
import { AgentSessionView_01 } from '@/components/agents-ui/blocks/agent-session-view-01';
import { WelcomeView } from '@/components/app/welcome-view';
import { DebugPanel } from '@/components/unloop/debug-panel';
import { useI18n } from '@/lib/i18n';

const MotionWelcomeView = motion.create(WelcomeView);
const MotionSessionView = motion.create(AgentSessionView_01);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
    },
    hidden: {
      opacity: 0,
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

/**
 * UNLOOP adaptation of the starter's view controller.
 *
 * The starter's session view is kept intact and unmodified — audio visualiser,
 * transcript, control bar, pre-connect buffer all still come from
 * `AgentSessionView_01`. The only change is layout: on a wide screen the session view
 * shares the row with the resolution debug panel, so a judge can watch the state move
 * while the call is happening. On a narrow screen the panel drops below, and on the
 * welcome screen it is not rendered at all.
 */
export function ViewController({
  demoMode = true,
  selectedDomain,
  onSelectDomain,
  testMode,
  selectedFixture,
  onSelectFixture,
  selectedLanguage,
  onSelectLanguage,
}: {
  demoMode?: boolean;
  selectedDomain: string;
  onSelectDomain: (domain: string) => void;
  testMode: boolean;
  selectedFixture: string;
  onSelectFixture: (fixture: string) => void;
  selectedLanguage: string;
  onSelectLanguage: (language: string) => void;
}) {
  const { isConnected, start } = useSessionContext();
  const { resolvedTheme } = useTheme();
  const { t } = useI18n();

  return (
    <AnimatePresence mode="wait">
      {/* Welcome view */}
      {!isConnected && (
        <MotionWelcomeView
          key="welcome"
          {...VIEW_MOTION_PROPS}
          startButtonText={t('welcome.start', 'Start call')}
          onStartCall={start}
          selectedDomain={selectedDomain}
          onSelectDomain={onSelectDomain}
          testMode={testMode}
          selectedFixture={selectedFixture}
          onSelectFixture={onSelectFixture}
          selectedLanguage={selectedLanguage}
          onSelectLanguage={onSelectLanguage}
        />
      )}

      {/* Session view + resolution panel */}
      {isConnected && (
        <motion.div
          key="session-with-panel"
          {...VIEW_MOTION_PROPS}
          className="fixed inset-0 grid grid-cols-1 lg:grid-cols-[1fr_420px]"
        >
          <div className="relative min-h-0">
            <MotionSessionView
              key="session-view"
              supportsChatInput={true}
              supportsVideoInput={false}
              supportsScreenShare={false}
              isPreConnectBufferEnabled={true}
              themeMode={resolvedTheme === 'dark' ? 'dark' : 'light'}
              className="absolute inset-0"
            />
          </div>
          <div className="hidden min-h-0 lg:block">
            <DebugPanel demoMode={demoMode} />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

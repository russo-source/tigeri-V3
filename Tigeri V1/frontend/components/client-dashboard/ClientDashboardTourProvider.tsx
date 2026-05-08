"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { getClientActiveAgents } from "@/lib/api";

type TourContextValue = {
  startTour: () => void;
  isRunning: boolean;
};

type TourStep = {
  routePattern: string;
  title: string;
  description: string;
  selector: string;
  continueLabel: string;
  requiredClick: boolean;
  optionalAction?: boolean;
  guidance?: string | string[];
  showGuidanceInTour?: boolean;
};

// Add blink animation style
const blinkAnimation = `
  @keyframes tour-blink {
    0%, 100% {
      border-color: #6366f1;
      box-shadow: 0 0 0 1px #6366f1, 0 0 12px rgba(99, 102, 241, 0.8);
    }
    50% {
      border-color: #ffffff;
      box-shadow: 0 0 0 1px #ffffff, 0 0 12px rgba(255, 255, 255, 0.6);
    }
  }
`;

const TOUR_COMPLETED_KEY = "client-dashboard-tour:completed";

function buildTourSteps(hasAgents: boolean): TourStep[] {
  const integrationSteps: TourStep[] = [
    {
      routePattern: "/client-dashboard/*",
      title: "Go To Integrations",
      description:
        "Navigate using the sidebar. Click Integrations to move to connection setup.",
      selector: '[data-tour-id="sidebar-nav-integrations"]',
      continueLabel: "Continue",
      requiredClick: true,
      guidance: "Use sidebar navigation to continue.",
      showGuidanceInTour: false,
    },
    {
      routePattern: "/client-dashboard/integration",
      title: "Pick WhatsApp Or Telegram",
      description:
        "Select either WhatsApp or Telegram provider card. We recommend connecting one channel first.",
      selector:
        '[data-tour-id="integration-provider-whatsapp"], [data-tour-id="integration-provider-telegram"]',
      continueLabel: "Next",
      requiredClick: true,
      guidance: "Click WhatsApp or Telegram provider card.",
      optionalAction: true,
      showGuidanceInTour: false,
    },
    {
      routePattern: "/client-dashboard/integration",
      title: "Connect Selected Provider",
      description:
        "Now click Connect to complete the platform connection flow for the selected provider.",
      selector: '[data-tour-id="integration-connect-selected"]',
      continueLabel: "Continue",
      requiredClick: false,
      guidance: [
        "Open Telegram and search @BotFather",
        "Run /newbot and finish bot creation",
        "Copy the bot API token",
        "Return here and paste token in API key",
        "Click Connect",
      ],
      optionalAction: true,
      showGuidanceInTour: false,
    },
  ];

  if (!hasAgents) {
    return [
      {
        routePattern: "/client-dashboard/home",
        title: "No Agents Yet",
        description:
          "You do not have active agents yet. First request an agent, then continue setup.",
        selector: '[data-tour-id="home-agents-table"]',
        continueLabel: "Next",
        requiredClick: false,
      },
      {
        routePattern: "/client-dashboard/*",
        title: "Go To New Agent",
        description:
          "Click New Agent in the sidebar to request your first agent.",
        selector: '[data-tour-id="sidebar-nav-settings"]',
        continueLabel: "Continue",
        requiredClick: true,
        guidance: "Use sidebar navigation to continue.",
      },
      {
        routePattern: "/client-dashboard/new-agent",
        title: "Request Any Agent",
        description:
          "Choose any available agent and click Request Agent to start your workflow setup.",
        selector: '[data-tour-id="settings-request-first"]',
        continueLabel: "Continue",
        requiredClick: true,
        optionalAction: true,
        guidance: "Click Request Agent to continue.",
      },
      ...integrationSteps,
      {
        routePattern: "/client-dashboard/*",
        title: "Go To Request Status",
        description:
          "Click Request Status to track approval and onboarding progress.",
        selector: '[data-tour-id="sidebar-nav-request-status"]',
        continueLabel: "Continue",
        requiredClick: true,
        guidance: "Use sidebar navigation to continue.",
      },
      {
        routePattern: "/client-dashboard/request-status",
        title: "Request Status Timeline",
        description:
          "Use this page to track your latest request stage and admin notes.",
        selector: '[data-tour-id="request-status-card"]',
        continueLabel: "Finish Tour",
        requiredClick: false,
      },
    ];
  }

  return [
    {
      routePattern: "/client-dashboard/home",
      title: "Welcome to Your Dashboard",
      description:
        "This table is your control center. Click any agent row to open detailed metrics and controls.",
      selector: '[data-tour-id="home-agents-table"]',
      continueLabel: "Next",
      requiredClick: true,
      guidance: "Click the highlighted area to continue.",
    },
    {
      routePattern: "/client-dashboard/home/*",
      title: "Pause Or Resume Agent",
      description:
        "Use this action button to pause or resume the selected agent. Click it once to continue.",
      selector: '[data-tour-id="agent-detail-toggle-button"]',
      continueLabel: "Continue",
      requiredClick: true,
      guidance: "Click pause/resume to continue.",
    },
    ...integrationSteps,
    {
      routePattern: "/client-dashboard/*",
      title: "Go To Request Status",
      description:
        "Click Request Status in the sidebar to review onboarding and approval progress.",
      selector: '[data-tour-id="sidebar-nav-request-status"]',
      continueLabel: "Continue",
      requiredClick: true,
      guidance: "Use sidebar navigation to continue.",
    },
    {
      routePattern: "/client-dashboard/request-status",
      title: "Request Status Timeline",
      description:
        "Use this page to track your latest request stage and read admin notes.",
      selector: '[data-tour-id="request-status-card"]',
      continueLabel: "Next",
      requiredClick: false,
    },
    {
      routePattern: "/client-dashboard/*",
      title: "Go To New Agent",
      description: "Click New Agent in sidebar to open agent request tools.",
      selector: '[data-tour-id="sidebar-nav-settings"]',
      continueLabel: "Continue",
      requiredClick: true,
      guidance: "Use sidebar navigation to continue.",
    },
    {
      routePattern: "/client-dashboard/new-agent",
      title: "Request New Agents",
      description:
        "Use this highlighted Request Agent button to submit a new agent request. Approval progress appears in Request Status.",
      selector: '[data-tour-id="settings-request-first"]',
      continueLabel: "Finish Tour",
      requiredClick: true,
      optionalAction: true,
      guidance: "Click Request Agent to submit (optional in tour mode).",
    },
  ];
}

const ClientDashboardTourContext = createContext<TourContextValue | null>(null);

export function useClientDashboardTour() {
  const context = useContext(ClientDashboardTourContext);
  if (!context) {
    return {
      startTour: () => undefined,
      isRunning: false,
    };
  }
  return context;
}

export default function ClientDashboardTourProvider({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();

  const [currentStepIndex, setCurrentStepIndex] = useState<number>(-1);
  const [highlightRect, setHighlightRect] = useState<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const [hasAgents, setHasAgents] = useState<boolean>(true);
  const [isTourReady, setIsTourReady] = useState(false);

  const tourSteps = useMemo(() => buildTourSteps(hasAgents), [hasAgents]);

  const isRunning = currentStepIndex >= 0;
  const currentStep =
    currentStepIndex >= 0 && currentStepIndex < tourSteps.length
      ? tourSteps[currentStepIndex]
      : null;

  useEffect(() => {
    let isMounted = true;

    async function resolveTourContext() {
      try {
        const agentsResponse = await getClientActiveAgents();
        const detectedHasAgents =
          (agentsResponse.active_agents ?? []).length > 0;
        if (!isMounted) {
          return;
        }
        setHasAgents(detectedHasAgents);
      } catch {
        if (!isMounted) {
          return;
        }
        setHasAgents(true);
      } finally {
        if (isMounted) {
          setIsTourReady(true);
        }
      }
    }

    void resolveTourContext();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!isTourReady) {
      return;
    }

    const completed = window.localStorage.getItem(TOUR_COMPLETED_KEY) === "1";
    if (!completed) {
      const timer = window.setTimeout(() => {
        setCurrentStepIndex(0);
      }, 0);

      return () => window.clearTimeout(timer);
    }
  }, [isTourReady]);

  const routeMatches = useCallback((pattern: string, path: string) => {
    if (pattern.endsWith("/*")) {
      const prefix = pattern.slice(0, -1);
      return path.startsWith(prefix);
    }
    return path === pattern;
  }, []);

  const advanceStep = useCallback(() => {
    setCurrentStepIndex((prev) => {
      if (prev >= tourSteps.length - 1) {
        window.localStorage.setItem(TOUR_COMPLETED_KEY, "1");
        return -1;
      }

      return prev + 1;
    });
  }, [tourSteps.length]);

  const updateHighlight = useCallback(() => {
    if (!currentStep || !routeMatches(currentStep.routePattern, pathname)) {
      setHighlightRect(null);
      return;
    }

    const targets = Array.from(
      document.querySelectorAll<HTMLElement>(currentStep.selector),
    );

    if (targets.length === 0) {
      setHighlightRect(null);
      return;
    }

    targets[0].scrollIntoView({ block: "center", inline: "nearest" });

    const merged = targets.reduce(
      (acc, element) => {
        const rect = element.getBoundingClientRect();
        return {
          top: Math.min(acc.top, rect.top),
          left: Math.min(acc.left, rect.left),
          right: Math.max(acc.right, rect.right),
          bottom: Math.max(acc.bottom, rect.bottom),
        };
      },
      {
        top: Number.POSITIVE_INFINITY,
        left: Number.POSITIVE_INFINITY,
        right: Number.NEGATIVE_INFINITY,
        bottom: Number.NEGATIVE_INFINITY,
      },
    );

    const padding = 6;

    setHighlightRect({
      top: Math.max(merged.top - padding, 4),
      left: Math.max(merged.left - padding, 4),
      width: Math.max(merged.right - merged.left + padding * 2, 24),
      height: Math.max(merged.bottom - merged.top + padding * 2, 24),
    });
  }, [currentStep, pathname, routeMatches]);

  useLayoutEffect(() => {
    const rafId = window.requestAnimationFrame(() => {
      updateHighlight();
    });

    const onScrollOrResize = () => updateHighlight();
    window.addEventListener("resize", onScrollOrResize);
    document.addEventListener("scroll", onScrollOrResize, true);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onScrollOrResize);
      document.removeEventListener("scroll", onScrollOrResize, true);
    };
  }, [updateHighlight]);

  const finishTour = useCallback(() => {
    window.localStorage.setItem(TOUR_COMPLETED_KEY, "1");
    setCurrentStepIndex(-1);
  }, []);

  const startTour = useCallback(() => {
    setCurrentStepIndex(0);
  }, []);

  const onNext = useCallback(() => {
    advanceStep();
  }, [advanceStep]);

  const onBack = useCallback(() => {
    setCurrentStepIndex((prev) => Math.max(prev - 1, 0));
  }, []);

  useEffect(() => {
    if (!isRunning || !currentStep) {
      return;
    }

    if (!routeMatches(currentStep.routePattern, pathname)) {
      return;
    }

    if (!currentStep.requiredClick) {
      return;
    }

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) {
        return;
      }

      const matched = target.closest(currentStep.selector);
      if (matched) {
        window.setTimeout(() => {
          advanceStep();
        }, 50);
      }
    };

    document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("click", onClick, true);
    };
  }, [advanceStep, currentStep, isRunning, pathname, routeMatches]);

  const contextValue = useMemo(
    () => ({
      startTour,
      isRunning,
    }),
    [startTour, isRunning],
  );

  const tourCardStyle = useMemo(() => {
    if (!highlightRect || typeof window === "undefined") {
      return {
        bottom: "24px",
        right: "24px",
      } as const;
    }

    const margin = 16;
    const gap = 10;
    const estimatedCardHeight = 280;
    const preferredWidth = 420;
    const cardWidth = Math.min(preferredWidth, window.innerWidth - margin * 2);

    const maxLeft = Math.max(margin, window.innerWidth - cardWidth - margin);
    const left = Math.min(Math.max(highlightRect.left, margin), maxLeft);

    const belowTop = highlightRect.top + highlightRect.height + gap;
    const canPlaceBelow =
      belowTop + estimatedCardHeight <= window.innerHeight - margin;
    const aboveTop = highlightRect.top - estimatedCardHeight - gap;

    const top = canPlaceBelow
      ? belowTop
      : Math.max(
          margin,
          Math.min(aboveTop, window.innerHeight - estimatedCardHeight - margin),
        );

    return {
      top: `${top}px`,
      left: `${left}px`,
      width: `${cardWidth}px`,
      maxWidth: `${cardWidth}px`,
    } as const;
  }, [highlightRect]);

  return (
    <ClientDashboardTourContext.Provider value={contextValue}>
      <style>{blinkAnimation}</style>
      {children}

      {isRunning && currentStep ? (
        <div className="pointer-events-none fixed inset-0 z-120">
          <div className="absolute inset-0 bg-black/18" />
          {highlightRect ? (
            <div
              className={`absolute rounded-md transition-all duration-200 ${
                currentStep.requiredClick
                  ? "bg-gray-200/20 border-2 border-indigo-600 animate-pulse"
                  : "bg-gray-100/10 border-2 border-indigo-500"
              }`}
              style={{
                top: `${highlightRect.top}px`,
                left: `${highlightRect.left}px`,
                width: `${highlightRect.width}px`,
                height: `${highlightRect.height}px`,
                animation: currentStep.requiredClick
                  ? "tour-blink 1.5s ease-in-out infinite"
                  : "none",
              }}
            />
          ) : null}
          <div
            className="pointer-events-auto absolute w-full max-w-md rounded-xl border border-border-5 bg-surface p-4 shadow-2xl"
            style={tourCardStyle}
          >
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.08em] text-text-muted">
                Client Dashboard Tour
              </p>
              <span className="text-xs text-text-muted">
                Step {currentStepIndex + 1} of {tourSteps.length}
              </span>
            </div>

            <h3 className="text-lg font-semibold text-text-primary">
              {currentStep.title}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-text-secondary">
              {currentStep.description}
            </p>
            {currentStep.showGuidanceInTour !== false &&
            currentStep.guidance ? (
              Array.isArray(currentStep.guidance) ? (
                <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-background-blue">
                  {currentStep.guidance.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ol>
              ) : (
                <p className="mt-2 text-xs text-background-blue">
                  {currentStep.guidance}
                </p>
              )
            ) : null}
            {currentStep.optionalAction ? (
              <p className="mt-1 text-xs text-text-muted">
                This action is optional in tour mode.
              </p>
            ) : null}

            <div className="mt-6 flex flex-col gap-3">
              <button
                type="button"
                onClick={onNext}
                disabled={currentStep.requiredClick && highlightRect !== null}
                className="w-full rounded-xs bg-background-blue px-4 py-2 text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {currentStep.continueLabel}
              </button>

              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={onBack}
                  disabled={currentStepIndex === 0}
                  className="rounded-xs border border-border-5 px-3 py-2 text-sm text-text-secondary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={finishTour}
                  className="rounded-xs border border-border-5 px-3 py-2 text-sm text-text-muted"
                >
                  Skip Tour
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </ClientDashboardTourContext.Provider>
  );
}

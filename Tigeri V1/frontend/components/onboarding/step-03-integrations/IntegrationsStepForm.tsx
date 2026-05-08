"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";
import { isSectionComplete } from "@/components/onboarding/section-completion";

const financeOptions = [
  "SAP S/4HANA",
  "SAP ECC",
  "Oracle Fusion",
  "Oracle EBS",
  "Microsoft Dynamics 365",
  "NetSuite",
  "Sage Intacct",
  "Coupa (Procurement)",
  "Ariba",
  "QuickBooks Enterprise",
  "Xero",
  "Custom ERP (API)",
  "None",
  "Others",
];

const crmOptions = [
  "Salesforce Sales Cloud",
  "Salesforce Service Cloud",
  "HubSpot CRM",
  "Microsoft Dynamics CRM",
  "Zendesk",
  "Intercom",
  "Marketo",
  "Custom CRM (API)",
  "None",
  "Others",
];

const hrOptions = [
  "Workday HCM",
  "BambooHR",
  "Microsoft 365 / SharePoint",
  "Confluence",
  "Jira / Jira Service Mgmt",
  "Slack",
  "Microsoft Teams",
  "ServiceNow ITSM",
  "Notion",
  "Google Workspace",
  "None",
  "Others",
];

export default function IntegrationsStepForm() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [completedMap, setCompletedMap] = useState<Record<string, boolean>>({});
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const sections = useMemo(
    () => [
      {
        id: "03.A",
        title: "ERP & Finance Systems",
        subtitle: "Core operational and financial integrations",
        status: "Active",
        content: (
          <div className="grid gap-3 px-1 py-6 md:grid-cols-4 md:py-8">
            {financeOptions.map((item) => (
              <label
                key={item}
                className="inline-flex items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base text-text-primary"
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-background-blue"
                />
                <span>{item}</span>
              </label>
            ))}
          </div>
        ),
      },
      {
        id: "03.B",
        title: "CRM & Customer Systems",
        subtitle: "Sales, marketing, and customer data integrations",
        status: "Active",
        content: (
          <div className="grid gap-3 px-1 py-6 md:grid-cols-4 md:py-8">
            {crmOptions.map((item) => (
              <label
                key={item}
                className="inline-flex items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base text-text-primary"
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-background-blue"
                />
                <span>{item}</span>
              </label>
            ))}
          </div>
        ),
      },
      {
        id: "03.C",
        title: "HR, Collaboration & Productivity",
        subtitle: "People systems, communication, and document management",
        status: "Active",
        content: (
          <div className="grid gap-3 px-1 py-6 md:grid-cols-4 md:py-8">
            {hrOptions.map((item) => (
              <label
                key={item}
                className="inline-flex items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base text-text-primary"
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-background-blue"
                />
                <span>{item}</span>
              </label>
            ))}
          </div>
        ),
      },
    ],
    [],
  );

  const recalculateCompletion = useCallback(() => {
    setCompletedMap(
      sections.reduce<Record<string, boolean>>((acc, section) => {
        acc[section.id] = isSectionComplete(sectionRefs.current[section.id]);
        return acc;
      }, {}),
    );
  }, [sections]);

  useEffect(() => {
    recalculateCompletion();
  }, [recalculateCompletion]);

  useEffect(() => {
    const onNextSubsection = (event: Event) => {
      const customEvent = event as CustomEvent<{ stepId?: string }>;
      if (customEvent.detail?.stepId !== "3") {
        return;
      }

      const allSectionsComplete = sections.every((section) =>
        isSectionComplete(sectionRefs.current[section.id]),
      );

      if (!allSectionsComplete) {
        if (activeIndex < sections.length - 1) {
          setActiveIndex((prev) => prev + 1);
        }
        event.preventDefault();
      }
    };

    window.addEventListener("onboarding-next-subsection", onNextSubsection);
    return () => {
      window.removeEventListener(
        "onboarding-next-subsection",
        onNextSubsection,
      );
    };
  }, [activeIndex, sections]);

  return (
    <div
      className="space-y-5"
      onInput={recalculateCompletion}
      onChange={recalculateCompletion}
    >
      <div className="border-l-4 border-background-blue bg-background-5 px-4 py-2 text-text-secondary">
        <p className="text-base">
          <span className="text-text-primary">
            Integration Scope Definition
          </span>{" "}
          - Select all systems the Nexus AI platform should connect to. Deeper
          integration coverage creates stronger context and more valuable
          generation outputs.
        </p>
      </div>

      <div className="overflow-hidden">
        {sections.map((section, index) => {
          const isActive = index === activeIndex;

          return (
            <div key={section.id}>
              <button
                type="button"
                onClick={() => setActiveIndex(index)}
                className={`flex w-full items-center rounded-xs px-4 py-2 text-left ${
                  isActive
                    ? "bg-background-blue text-white"
                    : "mb-2 bg-background-5 text-text-secondary"
                }`}
              >
                <p
                  className={`w-12 text-base ${isActive ? "text-white" : "text-text-primary"}`}
                >
                  {section.id}
                </p>
                <div className="flex-1">
                  <p className="text-base">{section.title}</p>
                </div>
                <span
                  className={`text-base ${
                    isActive ? "text-white/80" : "text-text-muted"
                  }`}
                >
                  {completedMap[section.id] ? "Complete" : "Incomplete"}
                </span>
                <span
                  className={`ml-4 ${isActive ? "text-white/80" : "text-text-muted"}`}
                  aria-hidden
                >
                  {isActive ? (
                    <ChevronUp size={20} />
                  ) : (
                    <ChevronDown size={20} />
                  )}
                </span>
              </button>

              <motion.div
                ref={(node) => {
                  sectionRefs.current[section.id] = node;
                }}
                initial={false}
                animate={{
                  height: isActive ? "auto" : 0,
                  opacity: isActive ? 1 : 0,
                }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className={`overflow-hidden ${isActive ? "" : "pointer-events-none"}`}
                aria-hidden={!isActive}
              >
                {section.content}
              </motion.div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";
import AnnualPlatformInvestmentModelSubForm from "@/components/onboarding/step-05-investment/AnnualPlatformInvestmentModelSubForm";
import { isSectionComplete } from "@/components/onboarding/section-completion";

const sections = [
  {
    id: "05",
    title: "Annual Platform Investment Model",
    subtitle:
      "Full platform budget, procurement timeline, and decision stakeholders",
    status: "Incomplete",
    Form: AnnualPlatformInvestmentModelSubForm,
  },
];

export default function InvestmentStepForm() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [completedMap, setCompletedMap] = useState<Record<string, boolean>>({});
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const recalculateCompletion = () => {
    setCompletedMap(
      sections.reduce<Record<string, boolean>>((acc, section) => {
        acc[section.id] = isSectionComplete(sectionRefs.current[section.id]);
        return acc;
      }, {}),
    );
  };

  useEffect(() => {
    recalculateCompletion();
  }, []);

  useEffect(() => {
    const onNextSubsection = (event: Event) => {
      const customEvent = event as CustomEvent<{ stepId?: string }>;
      if (customEvent.detail?.stepId !== "5") {
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
  }, [activeIndex]);

  return (
    <div
      className="overflow-hidden"
      onInput={recalculateCompletion}
      onChange={recalculateCompletion}
    >
      {sections.map((section, index) => {
        const isActive = index === activeIndex;
        const CurrentForm = section.Form;

        return (
          <div key={section.id} className="">
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
                {isActive ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
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
              <CurrentForm />
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import FullPageLoader from "@/components/ui/full-page-loader";
import Image from "next/image";
import OrganizationStepForm from "@/components/onboarding/step-01-organization/OrganizationStepForm";
import PlatformLayersStepForm from "@/components/onboarding/step-02-platform-layers/PlatformLayersStepForm";
import IntegrationsStepForm from "@/components/onboarding/step-03-integrations/IntegrationsStepForm";
import ComplianceStepForm from "@/components/onboarding/step-04-compliance/ComplianceStepForm";
import InvestmentStepForm from "@/components/onboarding/step-05-investment/InvestmentStepForm";
import ReadinessStepForm from "@/components/onboarding/step-06-readiness/ReadinessStepForm";
import OnboardingSidebar from "@/components/onboarding/OnboardingSidebar";
import {
  getCachedResolvedRoute,
  getCurrentUser,
  resolveUserRoute,
  setCachedResolvedRoute,
  submitOnboarding,
} from "@/lib/api";
import {
  sanitizeBusinessText,
  sanitizeEmailInput,
  sanitizeMultilineText,
  sanitizePersonName,
  sanitizePhoneInput,
} from "@/lib/input-validation";
import type { CurrentUser, OnboardingStepPayload } from "@/lib/type";
import GlobalHeader from "@/components/ui/GlobalHeader";
import GlobalFooter from "@/components/ui/GlobalFooter";

const stepItems = [
  { id: 1, label: "Organization", form: OrganizationStepForm },
  { id: 2, label: "Platform Layers", form: PlatformLayersStepForm },
  { id: 3, label: "Integrations", form: IntegrationsStepForm },
  { id: 4, label: "Compliance", form: ComplianceStepForm },
  { id: 5, label: "Investment", form: InvestmentStepForm },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [activeStep, setActiveStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [isCheckingAccess, setIsCheckingAccess] = useState(true);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [hasDraftRestored, setHasDraftRestored] = useState(false);
  const formRootRef = useRef<HTMLDivElement>(null);
  const [persistedSteps, setPersistedSteps] = useState<unknown[]>([]);
  const persistedStepsRef = useRef<unknown[]>([]);

  const draftStorageKey = useMemo(() => {
    if (!currentUser?.email) {
      return null;
    }
    return `onboarding:draft:${currentUser.email.toLowerCase()}`;
  }, [currentUser?.email]);

  const allSteps = useMemo(
    () => [...stepItems, { id: 6, label: "Readiness", form: null }],
    [],
  );

  useEffect(() => {
    persistedStepsRef.current = persistedSteps;
  }, [persistedSteps]);

  const hydrateStepFromSnapshot = useCallback(
    (stepIndex: number, snapshot: unknown) => {
      const root = formRootRef.current;
      if (!root) {
        return;
      }

      const stepElements = Array.from(
        root.querySelectorAll<HTMLElement>("[data-onboarding-step]"),
      );
      const stepEl = stepElements[stepIndex];
      if (!stepEl) {
        return;
      }

      const parsed = snapshot as {
        forms?: { fields?: Record<string, unknown> }[];
      };

      const keyToValues = new Map<string, string[]>();
      parsed?.forms?.forEach((form) => {
        Object.entries(form?.fields ?? {}).forEach(([key, val]) => {
          if (Array.isArray(val)) {
            keyToValues.set(
              key,
              val.map((entry) => String(entry)),
            );
            return;
          }
          keyToValues.set(key, [String(val ?? "")]);
        });
      });

      if (!keyToValues.size) {
        return;
      }

      const getFieldKey = (
        fieldEl: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
        fieldIndex: number,
      ) => {
        const labelText =
          fieldEl.closest("label")?.textContent?.replace(/\s+/g, " ").trim() ??
          "";
        const candidateKey =
          fieldEl.name ||
          fieldEl.id ||
          labelText ||
          fieldEl.getAttribute("placeholder") ||
          `field_${fieldIndex + 1}`;
        return sanitizeKey(candidateKey) || `field_${fieldIndex + 1}`;
      };

      const applyInputs = (
        container: HTMLElement,
        scopedFields?: Record<string, unknown>,
      ) => {
        const scopedMap = new Map<string, string[]>();
        if (scopedFields) {
          Object.entries(scopedFields).forEach(([key, val]) => {
            if (Array.isArray(val)) {
              scopedMap.set(
                key,
                val.map((entry) => String(entry)),
              );
              return;
            }
            scopedMap.set(key, [String(val ?? "")]);
          });
        }

        const sourceMap = scopedMap.size ? scopedMap : keyToValues;

        container
          .querySelectorAll<
            HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
          >("input, select, textarea")
          .forEach((fieldEl, idx) => {
            const key = getFieldKey(fieldEl, idx);
            const values = sourceMap.get(key);
            if (!values || !values.length) {
              return;
            }

            if (
              fieldEl instanceof HTMLInputElement &&
              (fieldEl.type === "checkbox" || fieldEl.type === "radio")
            ) {
              fieldEl.checked =
                values.includes(fieldEl.value) || values.includes("selected");
              fieldEl.dispatchEvent(new Event("change", { bubbles: true }));
              return;
            }

            fieldEl.value = values[0];
            fieldEl.dispatchEvent(new Event("input", { bubbles: true }));
            fieldEl.dispatchEvent(new Event("change", { bubbles: true }));
          });
      };

      const formEls = Array.from(
        stepEl.querySelectorAll<HTMLFormElement>("form"),
      );
      if (formEls.length) {
        const forms = parsed?.forms ?? [];
        formEls.forEach((formEl, idx) => {
          applyInputs(formEl, forms[idx]?.fields);
        });
        return;
      }

      applyInputs(stepEl);
    },
    [],
  );

  useEffect(() => {
    async function guardOnboardingRoute() {
      try {
        const user = await getCurrentUser();
        if (user.is_admin || user.client_id) {
          const cachedRoute = getCachedResolvedRoute();
          if (cachedRoute) {
            router.replace(cachedRoute);
            return;
          }
          const route = await resolveUserRoute(user);
          setCachedResolvedRoute(route);
          router.replace(route);
          return;
        }
        setCurrentUser(user);
      } catch {
        router.replace("/sign-in");
      } finally {
        setIsCheckingAccess(false);
      }
    }
    void guardOnboardingRoute();
  }, [router]);

  useEffect(() => {
    if (!draftStorageKey || hasDraftRestored) {
      return;
    }

    try {
      const rawDraft = window.localStorage.getItem(draftStorageKey);
      if (!rawDraft) {
        setHasDraftRestored(true);
        return;
      }

      const parsedDraft = JSON.parse(rawDraft) as {
        activeStep?: unknown;
        persistedSteps?: unknown[];
      };

      if (typeof parsedDraft.activeStep === "number") {
        const safeStep = Math.min(
          allSteps.length - 1,
          Math.max(0, Math.floor(parsedDraft.activeStep)),
        );
        setActiveStep(safeStep);
      }

      if (Array.isArray(parsedDraft.persistedSteps)) {
        persistedStepsRef.current = parsedDraft.persistedSteps;
        setPersistedSteps(parsedDraft.persistedSteps);
      }
    } catch {
      window.localStorage.removeItem(draftStorageKey);
    } finally {
      setHasDraftRestored(true);
    }
  }, [allSteps.length, draftStorageKey, hasDraftRestored]);

  useEffect(() => {
    if (!hasDraftRestored || !persistedStepsRef.current.length) {
      return;
    }

    const timer = window.setTimeout(() => {
      persistedStepsRef.current.forEach((snapshot, idx) => {
        hydrateStepFromSnapshot(idx, snapshot);
      });
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, [activeStep, hasDraftRestored, hydrateStepFromSnapshot]);

  useEffect(() => {
    if (!hasDraftRestored || !draftStorageKey) {
      return;
    }

    const payload = {
      activeStep,
      persistedSteps,
      updatedAt: new Date().toISOString(),
    };

    try {
      window.localStorage.setItem(draftStorageKey, JSON.stringify(payload));
    } catch {
      // Ignore localStorage quota/privacy errors.
    }
  }, [activeStep, draftStorageKey, hasDraftRestored, persistedSteps]);

  const progress = useMemo(() => {
    return Math.max(5, Math.round(((activeStep + 1) / allSteps.length) * 100));
  }, [activeStep, allSteps.length]);

  const sanitizeKey = (value: string) => {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  };

  const clearFieldValidationState = (container: HTMLElement) => {
    const invalidFieldClasses = [
      "border-red-400",
      "focus:border-red-400",
      "bg-red-500/10",
      "ring-1",
      "ring-red-400/40",
    ];

    container
      .querySelectorAll<HTMLButtonElement>(
        "button[data-field-invalid-select='true']",
      )
      .forEach((triggerEl) => {
        triggerEl.classList.remove(...invalidFieldClasses);
        triggerEl.removeAttribute("aria-invalid");
        triggerEl.removeAttribute("data-field-invalid-select");
      });

    container
      .querySelectorAll<
        HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >("input, select, textarea")
      .forEach((fieldEl) => {
        fieldEl.classList.remove(...invalidFieldClasses);
        fieldEl.removeAttribute("aria-invalid");
      });
  };

  const markFieldInvalid = (
    fieldEl: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
  ) => {
    const invalidFieldClasses = [
      "border-red-400",
      "focus:border-red-400",
      "bg-red-500/10",
      "ring-1",
      "ring-red-400/40",
    ];

    fieldEl.classList.add(...invalidFieldClasses);
    fieldEl.setAttribute("aria-invalid", "true");

    if (fieldEl instanceof HTMLSelectElement) {
      const triggerEl = fieldEl.nextElementSibling;
      if (triggerEl instanceof HTMLButtonElement) {
        triggerEl.classList.add(...invalidFieldClasses);
        triggerEl.setAttribute("aria-invalid", "true");
        triggerEl.setAttribute("data-field-invalid-select", "true");
      }
    }
  };

  const isSelectValueMissing = (value: string) => {
    const normalized = value.trim().toLowerCase();
    if (!normalized) return true;
    if (normalized === "select" || normalized === "country code") return true;
    return normalized.startsWith("select ");
  };

  const validateStepFields = useCallback((stepIndex: number) => {
    const root = formRootRef.current;
    if (!root) {
      return { valid: true, missingCount: 0 };
    }

    const stepElements = Array.from(
      root.querySelectorAll<HTMLElement>("[data-onboarding-step]"),
    );
    const stepEl = stepElements[stepIndex];
    if (!stepEl) {
      return { valid: true, missingCount: 0 };
    }

    clearFieldValidationState(stepEl);

    let missingCount = 0;

    const checkboxRadioGroups = new Map<
      string,
      { checked: boolean; elements: HTMLInputElement[] }
    >();

    stepEl
      .querySelectorAll<
        HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >("input, select, textarea")
      .forEach((fieldEl, fieldIndex) => {
        if (fieldEl.dataset.optional === "true") {
          return;
        }

        if (fieldEl.disabled) {
          return;
        }

        if (
          fieldEl instanceof HTMLInputElement &&
          ["hidden", "button", "submit", "reset"].includes(fieldEl.type)
        ) {
          return;
        }

        const labelText =
          fieldEl.closest("label")?.textContent?.replace(/\s+/g, " ").trim() ??
          "";
        const candidateKey =
          fieldEl.name ||
          fieldEl.id ||
          labelText ||
          fieldEl.getAttribute("placeholder") ||
          `field_${fieldIndex + 1}`;
        const key = sanitizeKey(candidateKey) || `field_${fieldIndex + 1}`;

        if (
          fieldEl instanceof HTMLInputElement &&
          (fieldEl.type === "checkbox" || fieldEl.type === "radio")
        ) {
          // Only enforce checkbox/radio validation when the input is explicitly required.
          if (!fieldEl.required) {
            return;
          }

          const group = checkboxRadioGroups.get(key) ?? {
            checked: false,
            elements: [],
          };
          group.checked = group.checked || fieldEl.checked;
          group.elements.push(fieldEl);
          checkboxRadioGroups.set(key, group);
          return;
        }

        const rawValue = fieldEl.value?.trim() ?? "";
        const isMissing =
          rawValue === "" ||
          (fieldEl instanceof HTMLSelectElement &&
            isSelectValueMissing(fieldEl.value));

        if (isMissing) {
          missingCount += 1;
          markFieldInvalid(fieldEl);
        }
      });

    checkboxRadioGroups.forEach((group) => {
      if (group.checked) return;
      missingCount += 1;
      group.elements.forEach((element) => markFieldInvalid(element));
    });

    return { valid: missingCount === 0, missingCount };
  }, []);

  const sanitizeFieldValue = (
    fieldEl: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
    rawValue: string,
    key: string,
  ) => {
    if (fieldEl instanceof HTMLSelectElement) return rawValue;
    const normalizedKey = key.toLowerCase();
    if (fieldEl instanceof HTMLTextAreaElement)
      return sanitizeMultilineText(rawValue, 1200);
    if (fieldEl instanceof HTMLInputElement) {
      if (fieldEl.type === "email") return sanitizeEmailInput(rawValue);
      if (
        fieldEl.type === "tel" ||
        normalizedKey.includes("phone") ||
        normalizedKey.includes("telephone")
      )
        return sanitizePhoneInput(rawValue);
      if (fieldEl.type === "password") return rawValue.slice(0, 128);
      if (fieldEl.type === "date" || fieldEl.type === "range") return rawValue;
    }
    if (normalizedKey.includes("full_name") || normalizedKey.endsWith("name"))
      return sanitizePersonName(rawValue, 80);
    if (normalizedKey.includes("title") || normalizedKey.includes("role"))
      return sanitizeBusinessText(rawValue, 80);
    if (normalizedKey.includes("email")) return sanitizeEmailInput(rawValue);
    return sanitizeBusinessText(rawValue, 200);
  };

  const serializeStep = useCallback((stepIndex: number) => {
    const root = formRootRef.current;
    if (!root) return null;

    const stepElements = Array.from(
      root.querySelectorAll<HTMLElement>("[data-onboarding-step]"),
    );
    const stepEl = stepElements[stepIndex];
    if (!stepEl) return null;

    const stepId = stepEl.dataset.stepId ?? String(stepIndex + 1);
    const stepLabel = stepEl.dataset.stepLabel ?? `Step ${stepIndex + 1}`;

    const collectFields = (container: HTMLElement): Record<string, unknown> => {
      const fields: Record<string, unknown> = {};

      container
        .querySelectorAll<
          HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
        >("input, select, textarea")
        .forEach((fieldEl, fieldIndex) => {
          const labelText =
            fieldEl
              .closest("label")
              ?.textContent?.replace(/\s+/g, " ")
              .trim() ?? "";
          const candidateKey =
            fieldEl.name ||
            fieldEl.id ||
            labelText ||
            fieldEl.getAttribute("placeholder") ||
            `field_${fieldIndex + 1}`;
          const key = sanitizeKey(candidateKey) || `field_${fieldIndex + 1}`;

          if (
            fieldEl instanceof HTMLInputElement &&
            (fieldEl.type === "checkbox" || fieldEl.type === "radio")
          ) {
            if (!fieldEl.checked) return;
            if (!Array.isArray(fields[key])) fields[key] = [];
            (fields[key] as string[]).push(
              fieldEl.value && fieldEl.value !== "on"
                ? fieldEl.value
                : "selected",
            );
            return;
          }

          if (fieldEl.value !== "") {
            fields[key] = sanitizeFieldValue(fieldEl, fieldEl.value, key);
          }
        });

      return fields;
    };

    const formEls = Array.from(
      stepEl.querySelectorAll<HTMLFormElement>("form"),
    );

    if (formEls.length > 0) {
      return {
        stepId,
        stepLabel,
        forms: formEls.map((formEl, i) => ({
          formId: formEl.id || `form_${i + 1}`,
          formIndex: i + 1,
          fields: collectFields(formEl),
        })),
      };
    }

    return {
      stepId,
      stepLabel,
      forms: [
        {
          formId: "form_1",
          formIndex: 1,
          fields: collectFields(stepEl),
        },
      ],
    };
  }, []);

  const snapshotStep = useCallback(
    (stepIndex: number) => {
      const snapshot = serializeStep(stepIndex);
      const updated = [...persistedStepsRef.current];
      if (snapshot) updated[stepIndex] = snapshot;
      persistedStepsRef.current = updated;
      setPersistedSteps(updated);
      return updated;
    },
    [serializeStep],
  );

  const goToNextStep = useCallback(() => {
    const event = new CustomEvent("onboarding-next-subsection", {
      cancelable: true,
      detail: { stepId: String(activeStep + 1) },
    });

    const shouldContinue = window.dispatchEvent(event);
    if (!shouldContinue) {
      return;
    }

    setActiveStep((prev) => {
      if (prev >= allSteps.length - 1) return prev;
      snapshotStep(prev);
      return prev + 1;
    });
  }, [activeStep, allSteps.length, snapshotStep]);

  const goToPreviousStep = useCallback(() => {
    setActiveStep((prev) => {
      if (prev <= 0) return prev;
      snapshotStep(prev);
      return prev - 1;
    });
  }, [snapshotStep]);

  const previewSteps = useMemo(() => {
    return Array.from(
      { length: allSteps.length - 1 },
      (_, i) =>
        persistedSteps[i] ?? {
          stepId: String(i + 1),
          stepLabel: allSteps[i].label,
          forms: [],
        },
    );
  }, [persistedSteps, allSteps]);

  const buildPayloadFromForms = useCallback(() => {
    const latest = [...persistedStepsRef.current];
    const live = serializeStep(activeStep);
    if (live) latest[activeStep] = live;

    const steps = Array.from(
      { length: allSteps.length - 1 },
      (_, i) =>
        latest[i] ?? {
          stepId: String(i + 1),
          stepLabel: allSteps[i].label,
          forms: [],
        },
    );

    return { submittedAt: new Date().toISOString(), progress, steps };
  }, [activeStep, allSteps, progress, serializeStep]);

  const submitAllSteps = async () => {
    if (isSubmitting) {
      return;
    }

    setSubmitError(null);
    setSubmitSuccess(null);
    setIsSubmitting(true);

    try {
      if (!currentUser?.email) {
        throw new Error("User session is missing. Please sign in again.");
      }

      snapshotStep(activeStep);

      const nowIso = new Date().toISOString();
      const payload = buildPayloadFromForms();
      const result = await submitOnboarding({
        submittedAt: payload.submittedAt,
        progress: payload.progress,
        serverSavedAt: nowIso,
        schemaVersion: 1,
        email: currentUser.email,
        client_id: currentUser.client_id ?? currentUser.id,
        steps: payload.steps as OnboardingStepPayload[],
      });

      if (draftStorageKey) {
        window.localStorage.removeItem(draftStorageKey);
      }

      setSubmitSuccess(
        result.message ??
          `Submitted successfully. Request ID: ${result.request_id}`,
      );
      router.replace("/request-status");
    } catch (error) {
      setSubmitError(
        error instanceof Error
          ? error.message
          : "Failed to submit onboarding data",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const onPrimaryAction = () => {
    if (isSubmitting) {
      return;
    }

    setSubmitError(null);

    if (activeStep < allSteps.length - 1) {
      const validation = validateStepFields(activeStep);
      if (!validation.valid) {
        setSubmitError(
          `Please fill all required fields before continuing (${validation.missingCount} missing).`,
        );
        return;
      }
      goToNextStep();
      return;
    }

    for (let i = 0; i < allSteps.length - 1; i += 1) {
      const validation = validateStepFields(i);
      if (!validation.valid) {
        setActiveStep(i);
        setSubmitError(
          `Please complete all required fields in ${allSteps[i].label} (${validation.missingCount} missing).`,
        );
        return;
      }
    }

    void submitAllSteps();
  };

  if (isCheckingAccess) {
    return <FullPageLoader />;
  }

  return (
    <main className="min-h-screen bg-background text-text-primary">
      <GlobalHeader />
      <div className="relative max-w-full overflow-hidden">
        <Image
          src="/images/onboardbg.svg"
          alt="Tigeri onboarding"
          fill
          priority
          className=" object-cover"
        />

        <div className="relative grid min-h-[calc(100vh-20px)] md:grid-cols-[600px_minmax(0,1fr)]">
          <OnboardingSidebar steps={allSteps} activeStep={activeStep} />

          <section className="min-w-0 rounded-xs bg-background p-4 md:p-12 dark:bg-background/85">
            <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
              <h1 className="text-xl text-text-primary">
                Set up your AI Settings
              </h1>
              <p className="rounded-full bg-background-5 px-4 py-2 text-sm font-medium text-text-secondary">
                {progress}% Complete
              </p>
            </div>

            <div ref={formRootRef} className="min-w-0">
              {allSteps.map((step, index) => {
                const isVisible = index === activeStep;
                const StepForm = step.form as React.ComponentType | null;

                return (
                  <div
                    key={step.id}
                    data-onboarding-step
                    data-step-id={String(step.id)}
                    data-step-label={step.label}
                    className={isVisible ? "block" : "hidden"}
                  >
                    {step.id === 6 ? (
                      <ReadinessStepForm steps={previewSteps} />
                    ) : StepForm ? (
                      <StepForm />
                    ) : null}
                  </div>
                );
              })}
            </div>

            {submitError && (
              <p className="mt-4 text-sm text-red-600">{submitError}</p>
            )}
            {submitSuccess && (
              <p className="mt-4 text-sm text-emerald-700">{submitSuccess}</p>
            )}

            <div className="mt-7 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={goToPreviousStep}
                disabled={activeStep === 0}
                className="rounded-full border border-border-5 bg-background-5 px-5 py-2 text-base font-medium text-text-secondary transition hover:bg-background-10 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Back
              </button>
              <button
                type="button"
                onClick={onPrimaryAction}
                disabled={isSubmitting}
                className="rounded-full bg-background-blue px-6 py-2 text-base font-medium text-white transition hover:opacity-90"
              >
                {activeStep === allSteps.length - 1
                  ? isSubmitting
                    ? "Saving..."
                    : "Submit"
                  : "Next"}
              </button>
            </div>
          </section>
        </div>
      </div>
      <GlobalFooter />
    </main>
  );
}

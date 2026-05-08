"use client";

import { useEffect, useMemo, useState } from "react";
import {
  connectApiKeyProvider,
  disconnectProvider,
  getApproverConfig,
  getCurrentUser,
  getIntegrationProviders,
  getIntegrationStatusByClient,
  getStripeWebhookUrl,
  initiateOAuthProvider,
  saveStripeWebhookSecret,
  updateApproverConfig,
} from "@/lib/api";
import {
  isValidEmailFormat,
  sanitizeBusinessText,
  sanitizeEmailInput,
  sanitizeSecretLike,
} from "@/lib/input-validation";
import type { ClientIntegration, IntegrationProvider } from "@/lib/type";
import { ClientIntegrationsSkeleton } from "@/components/ui/skeletons";
import { PageErrorState } from "@/components/ui/page-states";
import Image from "next/image";

const PROVIDER_LOGOS: Record<string, string> = {
  xero: "/images/provider-logo/xero.svg",
  quickbooks: "/images/provider-logo/quickbook.svg",
  google: "/images/provider-logo/google.svg",
  outlook: "/images/provider-logo/microsoft.svg",
  paypal: "/images/provider-logo/paypal.svg",
  stripe: "/images/provider-logo/stripe.svg",
  telegram: "/images/provider-logo/telegram.svg",
  whatsapp: "/images/provider-logo/whatsaap.svg",
  twilio_whatsapp: "/images/provider-logo/whatsaap.svg",
};

export default function IntegrationsPage() {
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [selectedProvider, setSelectedProvider] =
    useState<IntegrationProvider | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [extraFieldValues, setExtraFieldValues] = useState<
    Record<string, string>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [stripeWebhookUrl, setStripeWebhookUrl] = useState<string | null>(null);
  const [stripeInstructions, setStripeInstructions] = useState<string | null>(
    null,
  );
  const [stripeWebhookSecret, setStripeWebhookSecret] = useState("");
  const [stripeSecretSaved, setStripeSecretSaved] = useState(false);
  const [savingSecret, setSavingSecret] = useState(false);
  const [integrations, setIntegrations] = useState<ClientIntegration[]>([]);
  const [disconnectingProvider, setDisconnectingProvider] = useState<
    string | null
  >(null);
  const [approverChatId, setApproverChatId] = useState("");
  const [approverWhatsapp, setApproverWhatsapp] = useState("");
  const [approveEmail, setApproveEmail] = useState("");
  const [initialApproverChatId, setInitialApproverChatId] = useState("");
  const [initialApproverWhatsapp, setInitialApproverWhatsapp] = useState("");
  const [initialApproveEmail, setInitialApproveEmail] = useState("");
  const [isSavingApproverConfig, setIsSavingApproverConfig] = useState(false);
  const [approverError, setApproverError] = useState<string | null>(null);
  const [approverSuccess, setApproverSuccess] = useState<string | null>(null);
  const [whatsappTab, setWhatsappTab] = useState<
    "whatsapp" | "twilio_whatsapp"
  >("whatsapp");

  const connectedProviders = useMemo(
    () =>
      new Set(
        integrations
          .filter((item) => item.connected)
          .map((item) => item.provider),
      ),
    [integrations],
  );

  const mutuallyExclusiveGroups = useMemo(
    () => [
      ["xero", "quickbooks"],
      ["google", "outlook"],
      ["paypal", "stripe"],
    ],
    [],
  );

  const providerLabelById = useMemo(() => {
    const map = new Map<string, string>();
    providers.forEach((p) => map.set(p.provider, p.label));
    return map;
  }, [providers]);

  const isProviderConnected = (providerId: string) =>
    connectedProviders.has(providerId);

  const getMutuallyConnectedProvider = (providerId: string): string | null => {
    if (providerId === "telegram" || providerId === "whatsapp") return null;
    const group = mutuallyExclusiveGroups.find((g) => g.includes(providerId));
    if (!group) return null;
    const other = group.find(
      (id) => id !== providerId && connectedProviders.has(id),
    );
    return other ?? null;
  };

  const isBlockedByMutualExclusion = (providerId: string): boolean => {
    if (isProviderConnected(providerId)) return false;
    return Boolean(getMutuallyConnectedProvider(providerId));
  };

  useEffect(() => {
    async function loadData() {
      try {
        const [providersRes, user] = await Promise.all([
          getIntegrationProviders(),
          getCurrentUser(),
        ]);

        const integrationsRes = await getIntegrationStatusByClient(
          user.client_id as string,
        );

        setProviders(providersRes.providers);
        setIntegrations(integrationsRes.integrations);

        // Keep integrations usable even when approver-config endpoint is unavailable.
        try {
          const approverConfig = await getApproverConfig();
          const chatId = approverConfig.approver_chat_id ?? "";
          const whatsapp = approverConfig.approver_whatsapp ?? "";
          const email = approverConfig.approve_email ?? "";
          setApproverChatId(chatId);
          setApproverWhatsapp(whatsapp);
          setApproveEmail(email);
          setInitialApproverChatId(chatId);
          setInitialApproverWhatsapp(whatsapp);
          setInitialApproveEmail(email);
        } catch {
          setApproverError(
            "Approver configuration is currently unavailable. You can still manage integrations.",
          );
        }
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load providers",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadData();
  }, []);

  const hasApproverConfigChanges =
    approverChatId.trim() !== initialApproverChatId.trim() ||
    approverWhatsapp.trim() !== initialApproverWhatsapp.trim() ||
    approveEmail.trim() !== initialApproveEmail.trim();

  const onSelectProvider = (provider: IntegrationProvider) => {
    if (selectedProvider?.provider !== provider.provider) {
      setApiKey("");
      setExtraFieldValues({});
    }
    setSelectedProvider(provider);
    setSuccess(null);
    setError(null);
  };

  const onSaveStripeSecret = async () => {
    if (!stripeWebhookSecret) return;
    setSavingSecret(true);
    try {
      await saveStripeWebhookSecret(stripeWebhookSecret);
      setStripeSecretSaved(true);
      setStripeWebhookSecret("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save webhook secret",
      );
    } finally {
      setSavingSecret(false);
    }
  };

  const onConnect = async (provider: IntegrationProvider) => {
    setError(null);
    setSuccess(null);
    setIsSubmitting(true);

    try {
      if (provider.auth_type === "oauth2") {
        const response = await initiateOAuthProvider(provider.provider);
        window.location.href = response.auth_url;
        return;
      }

      if (!apiKey) throw new Error("API key is required for this provider.");

      const extraFields = provider.extra_fields ?? [];
      const extraPayload = extraFields.reduce<Record<string, string>>(
        (acc, f) => {
          const val = (extraFieldValues[f.key] ?? "").trim();
          if (val) acc[f.key] = val;
          return acc;
        },
        {},
      );
      await connectApiKeyProvider({
        provider: provider.provider,
        api_key: apiKey,
        extra: Object.keys(extraPayload).length > 0 ? extraPayload : undefined,
      });

      setSuccess(`${provider.label} connected successfully.`);
      setApiKey("");
      setExtraFieldValues({});
      setIntegrations((prev) =>
        prev.map((item) =>
          item.provider === provider.provider
            ? {
                ...item,
                connected: true,
                connected_at: item.connected_at ?? new Date().toISOString(),
              }
            : item,
        ),
      );
      setSelectedProvider(null);

      if (provider.provider === "stripe") {
        try {
          const stripeInfo = await getStripeWebhookUrl();
          setStripeWebhookUrl(stripeInfo.webhook_url);
          setStripeInstructions(stripeInfo.instructions);
        } catch {}
      }
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Failed to connect provider",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const onDisconnect = async (provider: IntegrationProvider) => {
    setError(null);
    setSuccess(null);
    setDisconnectingProvider(provider.provider);

    try {
      await disconnectProvider(provider.provider);
      setIntegrations((prev) =>
        prev.map((item) =>
          item.provider === provider.provider
            ? {
                ...item,
                connected: false,
                connected_at: null,
              }
            : item,
        ),
      );
      setSuccess(`${provider.label} disconnected successfully.`);

      if (selectedProvider?.provider === provider.provider) {
        setSelectedProvider(null);
      }
      if (provider.provider === "stripe") {
        setStripeWebhookUrl(null);
        setStripeInstructions(null);
        setStripeSecretSaved(false);
      }
    } catch (disconnectError) {
      setError(
        disconnectError instanceof Error
          ? disconnectError.message
          : "Failed to disconnect provider",
      );
    } finally {
      setDisconnectingProvider(null);
    }
  };

  const onSaveApproverConfig = async () => {
    setApproverError(null);
    setApproverSuccess(null);

    const nextApproveEmail = sanitizeEmailInput(approveEmail);
    if (nextApproveEmail && !isValidEmailFormat(nextApproveEmail)) {
      setApproverError("Please enter a valid approver email address.");
      return;
    }

    setIsSavingApproverConfig(true);
    try {
      const updated = await updateApproverConfig({
        approver_chat_id: approverChatId.trim() || null,
        approver_whatsapp: approverWhatsapp.trim() || null,
        approve_email: nextApproveEmail || null,
      });

      const chatId = updated.approver_chat_id ?? "";
      const whatsapp = updated.approver_whatsapp ?? "";
      const email = updated.approve_email ?? "";
      setApproverChatId(chatId);
      setApproverWhatsapp(whatsapp);
      setApproveEmail(email);
      setInitialApproverChatId(chatId);
      setInitialApproverWhatsapp(whatsapp);
      setInitialApproveEmail(email);
      setApproverSuccess("Approver configuration saved.");
    } catch (saveError) {
      setApproverError(
        saveError instanceof Error
          ? saveError.message
          : "Failed to update approver configuration",
      );
    } finally {
      setIsSavingApproverConfig(false);
    }
  };

  if (isLoading) return <ClientIntegrationsSkeleton />;

  return (
    <div className="mx-auto w-full max-w-full">
      <h1 className="text-2xl font-semibold text-text-primary">Integrations</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Connect providers for your approved agents
      </p>

      {error ? <PageErrorState message={error} /> : null}
      {success ? (
        <p className="mt-3 text-sm text-emerald-700">{success}</p>
      ) : null}

      <div className="mt-5 space-y-4">
        <div
          className="rounded-xs border border-border-5 bg-surface p-4 text-black"
          data-tour-id="integration-provider-selection"
        >
          <p className="text-sm font-medium text-text-primary">
            Provider Selection
          </p>
          <p className="mt-1 text-xs text-text-secondary">
            Select a provider and complete its connection flow.
          </p>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {providers
              .filter((p) => p.provider !== "twilio_whatsapp")
              .map((provider, providerIndex) => {
                if (provider.provider === "whatsapp") {
                  const twilioProvider = providers.find(
                    (p) => p.provider === "twilio_whatsapp",
                  );
                  const activeProvider =
                    whatsappTab === "whatsapp"
                      ? provider
                      : (twilioProvider ?? provider);
                  const isActiveConnected = isProviderConnected(
                    activeProvider.provider,
                  );
                  const isWhatsappConnected = isProviderConnected("whatsapp");
                  const isTwilioConnected = twilioProvider
                    ? isProviderConnected("twilio_whatsapp")
                    : false;
                  const isCardSelected =
                    selectedProvider?.provider === "whatsapp" ||
                    selectedProvider?.provider === "twilio_whatsapp";
                  const isActiveDisconnecting =
                    disconnectingProvider === activeProvider.provider;
                  const showWhatsappFields =
                    !isActiveConnected &&
                    isCardSelected &&
                    activeProvider.auth_type === "apikey";
                  const isConnectDisabled =
                    isSubmitting ||
                    disconnectingProvider !== null ||
                    (showWhatsappFields && !apiKey);

                  const handleTabSwitch = (
                    tab: "whatsapp" | "twilio_whatsapp",
                  ) => {
                    setWhatsappTab(tab);
                    const next = tab === "whatsapp" ? provider : twilioProvider;
                    if (isCardSelected && next) onSelectProvider(next);
                  };

                  return (
                    <div
                      key="whatsapp-combined"
                      data-tour-id="integration-provider-whatsapp"
                      onClick={() => {
                        if (
                          !isActiveConnected &&
                          !disconnectingProvider &&
                          !isSubmitting
                        ) {
                          onSelectProvider(activeProvider);
                        }
                      }}
                      role="button"
                      tabIndex={isActiveConnected ? -1 : 0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          if (
                            !isActiveConnected &&
                            !disconnectingProvider &&
                            !isSubmitting
                          ) {
                            onSelectProvider(activeProvider);
                          }
                        }
                      }}
                      className={`rounded-xs border px-3 py-2 text-left text-sm transition-colors ${
                        isActiveConnected
                          ? "tag-connected cursor-default border border-border-5"
                          : isCardSelected
                            ? "cursor-pointer border-background-blue bg-background-5 text-text-primary"
                            : "cursor-pointer border-border-5 bg-background-5 text-text-secondary hover:border-background-blue/50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-4">
                          <Image
                            src={PROVIDER_LOGOS.whatsapp}
                            alt="WhatsApp"
                            width={30}
                            height={30}
                            className="shrink-0 object-contain"
                          />
                          <p className="font-medium">WhatsApp</p>
                        </div>

                        {twilioProvider ? (
                          <div
                            className="flex gap-0.5 rounded-xs border border-border-5 bg-background-5 p-0.5"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTabSwitch("whatsapp");
                              }}
                              className={`flex items-center gap-1.5 rounded-xs px-2.5 py-1 text-xs font-medium transition-colors ${
                                whatsappTab === "whatsapp"
                                  ? "bg-surface text-text-primary shadow-sm"
                                  : "text-text-muted hover:text-text-secondary"
                              }`}
                            >
                              {isWhatsappConnected ? (
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                              ) : null}
                              360dialog
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTabSwitch("twilio_whatsapp");
                              }}
                              className={`flex items-center gap-1.5 rounded-xs px-2.5 py-1 text-xs font-medium transition-colors ${
                                whatsappTab === "twilio_whatsapp"
                                  ? "bg-surface text-text-primary shadow-sm"
                                  : "text-text-muted hover:text-text-secondary"
                              }`}
                            >
                              {isTwilioConnected ? (
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                              ) : null}
                              Twilio
                            </button>
                          </div>
                        ) : null}

                        {isActiveConnected ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void onDisconnect(activeProvider);
                            }}
                            disabled={isActiveDisconnecting}
                            className="border-ui-danger rounded-md border px-2.5 py-1 text-xs font-medium text-text-danger hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-70"
                          >
                            {isActiveDisconnecting
                              ? "Disconnecting..."
                              : "Disconnect"}
                          </button>
                        ) : (
                          <button
                            type="button"
                            data-tour-id={
                              isCardSelected
                                ? "integration-connect-selected"
                                : "integration-connect-whatsapp"
                            }
                            onClick={(event) => {
                              event.stopPropagation();
                              if (
                                activeProvider.auth_type === "apikey" &&
                                !isCardSelected
                              ) {
                                onSelectProvider(activeProvider);
                                return;
                              }
                              void onConnect(activeProvider);
                            }}
                            disabled={isConnectDisabled}
                            className="rounded-md bg-background-blue px-3 py-1.5 text-xs font-medium cursor-pointer hover:scale-105 duration-200 text-white hover:bg-background-blue disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {isSubmitting && isCardSelected
                              ? "Connecting..."
                              : "Connect"}
                          </button>
                        )}
                      </div>

                      {showWhatsappFields ? (
                        <div className="mt-3 space-y-3">
                          {whatsappTab === "whatsapp" ? (
                            <div className="rounded-xs border border-border-5 bg-background-5 p-3">
                              <p className="text-xs font-medium text-text-primary">
                                WhatsApp API Key Steps
                              </p>
                              <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                                <li>Open your 360dialog dashboard</li>
                                <li>Generate or copy your WhatsApp API key</li>
                                <li>
                                  Copy your registered WhatsApp phone number
                                </li>
                                <li>
                                  Paste API key and phone number in the fields
                                  below
                                </li>
                                <li>Click Connect</li>
                              </ol>
                            </div>
                          ) : (
                            <div className="rounded-xs border border-border-5 bg-background-5 p-3">
                              <p className="text-xs font-medium text-text-primary">
                                Twilio WhatsApp Steps
                              </p>
                              <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                                <li>Log in to your Twilio Console</li>
                                <li>Copy your Account SID and Auth Token</li>
                                <li>
                                  Copy your WhatsApp-enabled phone number (no +
                                  prefix)
                                </li>
                                <li>
                                  Paste Auth Token as API Key, then fill in
                                  Account SID and Phone Number below
                                </li>
                                <li>Click Connect</li>
                              </ol>
                            </div>
                          )}

                          <label className="block">
                            <span className="mb-1 block text-xs text-text-muted">
                              {activeProvider.field_label ?? "API Key"}
                            </span>
                            <input
                              value={apiKey}
                              maxLength={512}
                              onChange={(event) =>
                                setApiKey(
                                  sanitizeSecretLike(event.target.value, 512),
                                )
                              }
                              onClick={(event) => event.stopPropagation()}
                              className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                              placeholder={
                                activeProvider.field_placeholder ??
                                "Enter API key"
                              }
                            />
                          </label>

                          {(activeProvider.extra_fields ?? []).map((field) => (
                            <label key={field.key} className="block">
                              <span className="mb-1 block text-xs text-text-muted">
                                {field.label}
                              </span>
                              <input
                                value={extraFieldValues[field.key] ?? ""}
                                maxLength={120}
                                onChange={(event) =>
                                  setExtraFieldValues((prev) => ({
                                    ...prev,
                                    [field.key]: sanitizeBusinessText(
                                      event.target.value,
                                      120,
                                    ),
                                  }))
                                }
                                onClick={(event) => event.stopPropagation()}
                                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                                placeholder={
                                  field.placeholder ??
                                  `Enter ${field.label.toLowerCase()}`
                                }
                              />
                            </label>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                }

                const isSelected =
                  selectedProvider?.provider === provider.provider;
                const isConnected = isProviderConnected(provider.provider);
                const blockingProvider = getMutuallyConnectedProvider(
                  provider.provider,
                );
                const isMutuallyDisabled = isBlockedByMutualExclusion(
                  provider.provider,
                );
                const isDisconnecting =
                  disconnectingProvider === provider.provider;
                const showApiKeyFields =
                  !isConnected && isSelected && provider.auth_type === "apikey";
                const isConnectButtonDisabled =
                  isSubmitting ||
                  disconnectingProvider !== null ||
                  isMutuallyDisabled ||
                  (showApiKeyFields && !apiKey);

                return (
                  <div
                    key={provider.provider}
                    data-tour-id={
                      provider.provider === "whatsapp"
                        ? "integration-provider-whatsapp"
                        : provider.provider === "telegram"
                          ? "integration-provider-telegram"
                          : undefined
                    }
                    onClick={() => {
                      if (
                        !isConnected &&
                        !isMutuallyDisabled &&
                        !disconnectingProvider &&
                        !isSubmitting
                      ) {
                        onSelectProvider(provider);
                      }
                    }}
                    role="button"
                    tabIndex={isConnected || isMutuallyDisabled ? -1 : 0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        if (
                          !isConnected &&
                          !isMutuallyDisabled &&
                          !disconnectingProvider &&
                          !isSubmitting
                        ) {
                          onSelectProvider(provider);
                        }
                      }
                    }}
                    className={`rounded-xs border px-3 py-2 text-left text-sm transition-colors ${
                      isConnected
                        ? "tag-connected cursor-default border border-border-5"
                        : isMutuallyDisabled
                          ? "cursor-not-allowed border-border-5 bg-background-5 text-text-muted opacity-70"
                          : isSelected
                            ? "cursor-pointer border-background-blue bg-background-5 text-text-primary"
                            : "cursor-pointer border-border-5 bg-background-5 text-text-secondary hover:border-background-blue/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-4">
                        {PROVIDER_LOGOS[provider.provider] ? (
                          <Image
                            src={PROVIDER_LOGOS[provider.provider]}
                            alt={provider.label}
                            width={30}
                            height={30}
                            className="shrink-0 object-contain"
                          />
                        ) : null}
                        <p className="font-medium">{provider.label}</p>
                      </div>

                      {isConnected ? (
                        <button
                          type="button"
                          data-tour-id={
                            isSelected &&
                            (provider.provider === "whatsapp" ||
                              provider.provider === "telegram")
                              ? "integration-connect-selected"
                              : provider.provider === "whatsapp"
                                ? "integration-connect-whatsapp"
                                : provider.provider === "telegram"
                                  ? "integration-connect-telegram"
                                  : providerIndex === 0
                                    ? "integration-connect-first"
                                    : undefined
                          }
                          onClick={(event) => {
                            event.stopPropagation();
                            void onDisconnect(provider);
                          }}
                          disabled={isDisconnecting}
                          className="border-ui-danger rounded-md border px-2.5 py-1 text-xs font-medium text-text-danger hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-70"
                        >
                          {isDisconnecting ? "Disconnecting..." : "Disconnect"}
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-tour-id={
                            isSelected &&
                            (provider.provider === "whatsapp" ||
                              provider.provider === "telegram")
                              ? "integration-connect-selected"
                              : provider.provider === "whatsapp"
                                ? "integration-connect-whatsapp"
                                : provider.provider === "telegram"
                                  ? "integration-connect-telegram"
                                  : providerIndex === 0
                                    ? "integration-connect-first"
                                    : undefined
                          }
                          onClick={(event) => {
                            event.stopPropagation();

                            if (
                              provider.auth_type === "apikey" &&
                              !isSelected
                            ) {
                              if (isMutuallyDisabled) return;
                              onSelectProvider(provider);
                              return;
                            }

                            void onConnect(provider);
                          }}
                          disabled={isConnectButtonDisabled}
                          className="rounded-md bg-background-blue px-3 py-1.5 text-xs font-medium cursor-pointer hover:scale-105 duration-200 text-white hover:bg-background-blue disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {isSubmitting && isSelected
                            ? "Connecting..."
                            : "Connect"}
                        </button>
                      )}
                    </div>

                    {!isConnected && isMutuallyDisabled && blockingProvider ? (
                      <p className="mt-2 text-xs text-text-muted">
                        Disconnect{" "}
                        {providerLabelById.get(blockingProvider) ??
                          blockingProvider}{" "}
                        to connect this provider.
                      </p>
                    ) : null}

                    {!isConnected && showApiKeyFields ? (
                      <div className="mt-3 space-y-3">
                        {provider.provider === "telegram" ? (
                          <div className="rounded-xs border border-border-5 bg-background-5 p-3">
                            <p className="text-xs font-medium text-text-primary">
                              Telegram Bot API Key Steps
                            </p>
                            <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                              <li>Open Telegram and search @BotFather</li>
                              <li>Type /newbot and complete bot creation</li>
                              <li>
                                Copy the bot API token provided by BotFather
                              </li>
                              <li>Paste token in API key field below</li>
                              <li>Click Connect</li>
                            </ol>
                          </div>
                        ) : null}

                        {provider.provider === "whatsapp" ? (
                          <div className="rounded-xs border border-border-5 bg-background-5 p-3">
                            <p className="text-xs font-medium text-text-primary">
                              WhatsApp API Key Steps
                            </p>
                            <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                              <li>Open your 360dialog dashboard</li>
                              <li>Generate or copy your WhatsApp API key</li>
                              <li>
                                Copy your registered WhatsApp phone number
                              </li>
                              <li>
                                Paste API key and phone number in the fields
                                below
                              </li>
                              <li>Click Connect</li>
                            </ol>
                          </div>
                        ) : null}

                        {provider.provider === "stripe" ? (
                          <div className="rounded-xs border border-border-5 bg-background-5 p-3">
                            <p className="text-xs font-medium text-text-primary">
                              Stripe API Key Steps
                            </p>
                            <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                              <li>Sign in to your Stripe Dashboard</li>
                              <li>Go to Developers - API keys</li>
                              <li>Copy your Secret key (starts with sk_)</li>
                              <li>Paste the key in the API key field below</li>
                              <li>Click Connect</li>
                            </ol>
                          </div>
                        ) : null}

                        <label className="block">
                          <span className="mb-1 block text-xs text-text-muted">
                            {provider.field_label ?? "API Key"}
                          </span>
                          <input
                            value={apiKey}
                            maxLength={512}
                            onChange={(event) =>
                              setApiKey(
                                sanitizeSecretLike(event.target.value, 512),
                              )
                            }
                            onClick={(event) => event.stopPropagation()}
                            className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                            placeholder={
                              provider.field_placeholder ?? "Enter API key"
                            }
                          />
                        </label>

                        {(provider.extra_fields ?? []).map((field) => (
                          <label key={field.key} className="block">
                            <span className="mb-1 block text-xs text-text-muted">
                              {field.label}
                            </span>
                            <input
                              value={extraFieldValues[field.key] ?? ""}
                              maxLength={120}
                              onChange={(event) =>
                                setExtraFieldValues((prev) => ({
                                  ...prev,
                                  [field.key]: sanitizeBusinessText(
                                    event.target.value,
                                    120,
                                  ),
                                }))
                              }
                              onClick={(event) => event.stopPropagation()}
                              className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                              placeholder={
                                field.placeholder ??
                                `Enter ${field.label.toLowerCase()}`
                              }
                            />
                          </label>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
          </div>
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-4 space-y-3">
          <p className="text-sm font-medium text-text-primary">
            Approver Configuration
          </p>
          <p className="text-xs text-text-secondary">
            Add approval contacts used for approval notifications and actions.
          </p>

          {approverError ? (
            <p className="text-sm text-red-600">{approverError}</p>
          ) : null}
          {approverSuccess ? (
            <p className="text-sm text-emerald-700">{approverSuccess}</p>
          ) : null}

          <div className="grid gap-3 md:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Approver Chat ID
              </span>
              <input
                value={approverChatId}
                maxLength={120}
                onChange={(event) =>
                  setApproverChatId(
                    sanitizeBusinessText(event.target.value, 120),
                  )
                }
                className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                placeholder="Enter chat ID"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Approver WhatsApp
              </span>
              <input
                value={approverWhatsapp}
                maxLength={20}
                onChange={(event) =>
                  setApproverWhatsapp(
                    sanitizeBusinessText(event.target.value, 20),
                  )
                }
                className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                placeholder="e.g. +1234567890"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Approver Email
              </span>
              <input
                value={approveEmail}
                maxLength={254}
                onChange={(event) =>
                  setApproveEmail(sanitizeEmailInput(event.target.value, 254))
                }
                className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                placeholder="approver@company.com"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => void onSaveApproverConfig()}
            disabled={!hasApproverConfigChanges || isSavingApproverConfig}
            className="rounded-lg bg-background-blue px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSavingApproverConfig ? "Saving..." : "Save Approver Config"}
          </button>
        </div>

        {!stripeWebhookUrl ? (
          <div className="rounded-xs border border-border-5 bg-surface p-4">
            <p className="text-sm font-medium text-text-primary">
              Connection Method
            </p>
            <p className="mt-1 text-xs text-text-secondary">
              OAuth providers will redirect to their authorization page. API key
              providers connect directly.
            </p>
          </div>
        ) : null}

        {stripeWebhookUrl ? (
          <div className="rounded-xs border border-border-5 bg-surface p-4 space-y-3">
            <p className="text-sm font-medium text-text-primary">
              Stripe Webhook Setup
            </p>
            <p className="text-xs text-text-secondary">{stripeInstructions}</p>

            <div className="rounded-xs border border-border-5 bg-background-5 px-3 py-2">
              <p className="text-xs text-text-muted mb-1">Webhook URL</p>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-text-secondary break-all">
                  {stripeWebhookUrl}
                </p>
                <button
                  onClick={() =>
                    void navigator.clipboard.writeText(stripeWebhookUrl)
                  }
                  className="shrink-0 rounded border border-border-5 px-2 py-1 text-xs text-text-secondary hover:bg-background-5"
                >
                  Copy
                </button>
              </div>
            </div>

            {stripeSecretSaved ? (
              <p className="text-sm text-emerald-300">
                Webhook secret saved. Setup complete.
              </p>
            ) : (
              <div className="space-y-2">
                <label className="block">
                  <span className="mb-1 block text-xs text-text-muted">
                    Paste Stripe Signing Secret
                  </span>
                  <input
                    value={stripeWebhookSecret}
                    maxLength={512}
                    onChange={(e) =>
                      setStripeWebhookSecret(
                        sanitizeSecretLike(e.target.value, 512),
                      )
                    }
                    placeholder="whsec_..."
                    className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
                  />
                </label>
                <button
                  onClick={() => void onSaveStripeSecret()}
                  disabled={!stripeWebhookSecret || savingSecret}
                  className="rounded-lg bg-background-blue px-4 py-2 text-sm text-white disabled:opacity-60"
                >
                  {savingSecret ? "Saving..." : "Save Webhook Secret"}
                </button>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

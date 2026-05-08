export type LogLevel = "debug" | "info" | "warn" | "error";

export type LogContext = Record<string, unknown>;

function serializeError(error: unknown) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    };
  }

  return error;
}

function canUseConsole(level: LogLevel) {
  if (typeof window === "undefined") {
    return true;
  }

  const noisy = level === "debug";
  return process.env.NODE_ENV !== "production" || !noisy;
}

export function log(level: LogLevel, message: string, context: LogContext = {}) {
  if (!canUseConsole(level)) {
    return;
  }

  const event = {
    level,
    message,
    timestamp: new Date().toISOString(),
    ...context,
  };

  if (level === "error") {
    console.error(event);
    return;
  }

  if (level === "warn") {
    console.warn(event);
    return;
  }

  if (level === "info") {
    console.info(event);
    return;
  }

  console.debug(event);
}

export function logError(message: string, error: unknown, context: LogContext = {}) {
  log("error", message, {
    ...context,
    error: serializeError(error),
  });
}

export function reportError(error: unknown, context: LogContext = {}) {
  logError("Unhandled frontend error", error, context);
}

export function createTraceId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

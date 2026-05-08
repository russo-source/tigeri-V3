type PageStateProps = {
  title?: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function PageErrorState({
  title = "Something went wrong",
  message = "We could not load this section.",
  actionLabel = "Retry",
  onAction,
}: PageStateProps) {
  return (
    <div className="rounded-xs border border-red-300/40 bg-red-500/10 p-4">
      <p className="text-sm font-semibold text-red-300">{title}</p>
      <p className="mt-1 text-sm text-red-100/90">{message}</p>
      {onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="mt-3 rounded-xs border border-red-300/60 px-3 py-1.5 text-sm text-red-100"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function PageEmptyState({
  title = "No data available",
  message = "There is nothing to show yet.",
  actionLabel,
  onAction,
}: PageStateProps) {
  return (
    <div className="rounded-xs border border-border-5 bg-surface p-6 text-center">
      <p className="text-sm font-semibold text-text-primary">{title}</p>
      <p className="mt-1 text-sm text-text-secondary">{message}</p>
      {onAction && actionLabel ? (
        <button
          type="button"
          onClick={onAction}
          className="mt-4 rounded-xs border border-border-5 px-3 py-1.5 text-sm text-text-primary"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

import { Loader2 } from "lucide-react";

type FullPageLoaderProps = {
  wrapperClassName?: string;
  spinnerClassName?: string;
  label?: string;
};

export default function FullPageLoader({
  wrapperClassName,
  spinnerClassName,
  label = "Loading",
}: FullPageLoaderProps) {
  const wrapperClasses =
    `flex min-h-screen items-center justify-center bg-background-dashboard px-6 text-text-primary ${wrapperClassName ?? ""}`.trim();
  const spinnerClasses =
    spinnerClassName ?? "h-14 w-14 animate-spin text-navy";

  return (
    <main className={wrapperClasses}>
      <Loader2 className={spinnerClasses} aria-label={label} />
    </main>
  );
}

import Link from "next/link";

interface GlobalFooterProps {
  className?: string;
}

export default function GlobalFooter({ className = "" }: GlobalFooterProps) {
  return (
    <footer className={`border-t border-border bg-surface ${className}`}>
      <div className="max-w-full mx-auto px-4 md:px-8">
        <div className="flex min-h-11 flex-wrap items-center justify-between gap-3 py-3 text-sm text-text-muted">
          <p>© 2026 Tigeri. All rights reserved.</p>
          <div className="flex items-center gap-4">
            <Link href="/sign-in" className="hover:text-text-primary">
              Terms
            </Link>
            <Link href="/sign-up" className="hover:text-text-primary">
              Privacy
            </Link>
            <Link href="/sign-up" className="hover:text-text-primary">
              Support
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}

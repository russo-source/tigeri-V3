import Link from "next/link";

interface GlobalFooterProps {
  className?: string;
}

export default function GlobalFooter({ className = "" }: GlobalFooterProps) {
  return (
    <footer className={`border-t border-border-10 bg-surface ${className}`}>
      <div className="max-w-full mx-auto px-4 md:px-8">
        <div className="flex min-h-11 flex-wrap items-center justify-between gap-3 py-3 text-sm text-text-muted">
          <p>© 2026 Tigeri. All rights reserved.</p>
          <div className="flex items-center gap-4">
            <Link href="/terms-conditions" className="hover:text-text-primary">
              Terms
            </Link>
            <Link href="/privacy-policy" className="hover:text-text-primary">
              Privacy
            </Link>
            <p>
              Made by{" "}
              <a
                href="https://engxlab.com"
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold hover:text-background-blue"
              >
                Engxlab
              </a>
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}

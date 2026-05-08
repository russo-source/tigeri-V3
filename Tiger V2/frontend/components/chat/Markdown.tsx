"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Markdown renderer for assistant bubbles. Themed to match the brand spec:
 * - Body uses IBM Plex Sans (inherits from --font-sans)
 * - Inline code + fenced code use IBM Plex Mono (--font-mono) on --surface
 * - Tables use 1px --border, no shadows
 * - Links use --color-navy and open in a new tab
 *
 * react-markdown sanitizes HTML by default; no rehype-raw here.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-tigeri text-sm leading-relaxed text-text-primary">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer"
              className="text-navy underline hover:opacity-80"
            />
          ),
          code: ({ children, className }) => {
            const isBlock = (className ?? "").startsWith("language-");
            if (isBlock) {
              return (
                <pre className="my-2 overflow-x-auto rounded-md border border-border bg-surface p-2 text-xs">
                  <code className="font-mono">{children}</code>
                </pre>
              );
            }
            return (
              <code className="rounded-sm bg-surface px-1 py-0.5 font-mono text-xs">
                {children}
              </code>
            );
          },
          table: (props) => (
            <div className="my-2 overflow-x-auto rounded-md border border-border">
              <table {...props} className="w-full border-collapse text-xs" />
            </div>
          ),
          thead: (props) => <thead {...props} className="bg-surface" />,
          th: (props) => (
            <th
              {...props}
              className="border-b border-border px-2 py-1 text-left font-medium"
            />
          ),
          td: (props) => (
            <td {...props} className="border-b border-border-5 px-2 py-1 align-top" />
          ),
          ul: (props) => <ul {...props} className="list-disc pl-5" />,
          ol: (props) => <ol {...props} className="list-decimal pl-5" />,
          li: (props) => <li {...props} className="my-0.5" />,
          h1: (props) => <h1 {...props} className="my-1 text-base font-semibold" />,
          h2: (props) => <h2 {...props} className="my-1 text-sm font-semibold" />,
          h3: (props) => <h3 {...props} className="my-1 text-sm font-semibold" />,
          p: (props) => <p {...props} className="my-1" />,
          strong: (props) => (
            <strong {...props} className="font-semibold text-text-primary" />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

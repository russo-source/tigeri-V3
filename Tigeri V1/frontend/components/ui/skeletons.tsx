function SkeletonBlock({ className }: { className: string }) {
  return (
    <div className={`animate-pulse rounded-xs bg-background-5 ${className}`} />
  );
}

function SkeletonHeader() {
  return (
    <div className="space-y-2">
      <SkeletonBlock className="h-8 w-56" />
      <SkeletonBlock className="h-4 w-80 max-w-full" />
    </div>
  );
}

function SkeletonTableRows({
  rows,
  columns,
}: {
  rows: number;
  columns: number;
}) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div
          key={rowIndex}
          className="grid gap-3"
          style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: columns }).map((__, colIndex) => (
            <SkeletonBlock
              key={`${rowIndex}-${colIndex}`}
              className={`h-8 rounded-xs ${colIndex === 0 ? "w-20" : "w-full"}`}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function AdminDashboardLayoutSkeleton() {
  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-background text-text-primary">
      <div className="h-14 shrink-0 border-b border-border-5 bg-surface px-5">
        <div className="flex h-full items-center justify-between">
          <SkeletonBlock className="h-6 w-36" />
          <SkeletonBlock className="h-8 w-48" />
        </div>
      </div>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="hidden w-64 shrink-0 border-r border-border-5 bg-surface p-4 lg:block">
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, index) => (
              <SkeletonBlock key={index} className="h-9 w-full" />
            ))}
          </div>
        </aside>
        <section className="min-w-0 flex-1 overflow-hidden bg-background-dashboard p-5">
          <div className="space-y-4">
            <SkeletonHeader />
            <SkeletonBlock className="h-40 w-full" />
            <SkeletonBlock className="h-64 w-full" />
          </div>
        </section>
      </div>
    </main>
  );
}

export function AdminOverviewSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />

      <div className="grid overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className={index !== 3 ? "border-r border-border-5 p-5" : "p-5"}
          >
            <SkeletonBlock className="h-10 w-20" />
            <SkeletonBlock className="mt-3 h-4 w-28" />
            <SkeletonBlock className="mt-2 h-3 w-36" />
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-12">
        <div className="overflow-hidden rounded-xs border border-border-5 bg-surface lg:col-span-8">
          <div className="border-b border-border-5 px-4 py-3">
            <SkeletonBlock className="h-4 w-36" />
          </div>
          <SkeletonTableRows rows={4} columns={5} />
        </div>
        <div className="rounded-xs border border-border-5 bg-surface p-4 lg:col-span-4">
          <div className="flex items-center justify-between border-b border-border-5 pb-2">
            <SkeletonBlock className="h-4 w-16" />
            <SkeletonBlock className="h-5 w-8" />
          </div>
          <div className="mt-3 space-y-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <div
                key={index}
                className="border-b border-border-5 pb-2 last:border-0"
              >
                <SkeletonBlock className="h-4 w-full" />
                <SkeletonBlock className="mt-2 h-3 w-3/4" />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3">
          <SkeletonBlock className="h-4 w-32" />
        </div>
        <SkeletonTableRows rows={5} columns={3} />
      </div>
    </div>
  );
}

export function AdminRequestsSkeleton() {
  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <SkeletonHeader />

      <div className="flex flex-wrap gap-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <SkeletonBlock key={index} className="h-8 w-28" />
        ))}
      </div>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-12">
        <div className="min-h-0 overflow-hidden rounded-xs border border-border-5 bg-surface lg:col-span-8">
          <div className="h-full overflow-hidden">
            <div className="border-b border-border-5 px-4 py-3">
              <SkeletonBlock className="h-4 w-full" />
            </div>
            <SkeletonTableRows rows={8} columns={5} />
          </div>
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-3 lg:col-span-4">
          <div className="flex items-center justify-between border-b border-border-5 pb-2">
            <SkeletonBlock className="h-4 w-28" />
            <SkeletonBlock className="h-4 w-4" />
          </div>
          <div className="space-y-2 py-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="flex items-center justify-between border-b border-border-5 pb-2"
              >
                <SkeletonBlock className="h-3 w-16" />
                <SkeletonBlock className="h-3 w-24" />
              </div>
            ))}
          </div>
          <SkeletonBlock className="h-20 w-full" />
          <div className="mt-3 grid grid-cols-2 gap-2">
            <SkeletonBlock className="h-9 w-full" />
            <SkeletonBlock className="h-9 w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AdminClientsSkeleton() {
  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <SkeletonHeader />

      <div className="flex items-center gap-2">
        <SkeletonBlock className="h-9 w-full max-w-[320px]" />
        <SkeletonBlock className="h-4 w-24" />
      </div>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-12">
        <div className="min-h-0 overflow-hidden rounded-xs border border-border-5 bg-surface lg:col-span-8">
          <div className="border-b border-border-5 px-4 py-3">
            <SkeletonBlock className="h-4 w-full" />
          </div>
          <SkeletonTableRows rows={8} columns={6} />
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-3 lg:col-span-4">
          <div className="flex items-center justify-between border-b border-border-5 pb-2">
            <SkeletonBlock className="h-4 w-24" />
            <SkeletonBlock className="h-4 w-4" />
          </div>
          <div className="space-y-2 py-3">
            <div className="flex items-center gap-2">
              <SkeletonBlock className="h-6 w-6 rounded-full" />
              <div className="space-y-1">
                <SkeletonBlock className="h-3 w-28" />
                <SkeletonBlock className="h-3 w-24" />
              </div>
            </div>
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="flex items-center justify-between border-b border-border-5 pb-2"
              >
                <SkeletonBlock className="h-3 w-16" />
                <SkeletonBlock className="h-3 w-24" />
              </div>
            ))}
          </div>
          <SkeletonBlock className="h-9 w-full" />
        </div>
      </div>
    </div>
  );
}

export function AdminMonitoringSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />

      <div className="grid overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className={index !== 3 ? "border-r border-border-5 p-5" : "p-5"}
          >
            <SkeletonBlock className="h-10 w-20" />
            <SkeletonBlock className="mt-2 h-4 w-24" />
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3">
          <SkeletonBlock className="h-4 w-24" />
        </div>
        <SkeletonTableRows rows={7} columns={6} />
      </div>
    </div>
  );
}

export function AdminLogsSkeleton() {
  return (
    <div className="mx-auto flex h-[calc(100vh-5.5rem)] w-full max-w-full flex-col space-y-4 overflow-hidden">
      <SkeletonHeader />

      <div className="flex flex-wrap items-center gap-2">
        <SkeletonBlock className="h-9 w-full max-w-[320px]" />
        {Array.from({ length: 5 }).map((_, index) => (
          <SkeletonBlock key={index} className="h-8 w-20" />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SkeletonBlock className="h-4 w-10" />
        <SkeletonBlock className="h-9 w-32" />
        <SkeletonBlock className="h-9 w-24" />
        <SkeletonBlock className="h-4 w-6" />
        <SkeletonBlock className="h-9 w-32" />
        <SkeletonBlock className="h-9 w-24" />
      </div>

      <div className="min-h-0 flex-1 overflow-hidden rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3">
          <SkeletonBlock className="h-4 w-full" />
        </div>
        <SkeletonTableRows rows={9} columns={4} />
      </div>
    </div>
  );
}

export function AdminSettingsSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <SkeletonBlock className="h-4 w-48" />
        <SkeletonBlock className="mt-2 h-3 w-72" />
        <SkeletonBlock className="mt-4 h-10 w-full" />

        <div className="mt-4 space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="rounded-xs border border-border-5 bg-background-5 px-3 py-3"
            >
              <div className="flex items-center justify-between">
                <SkeletonBlock className="h-4 w-28" />
                <SkeletonBlock className="h-5 w-24" />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <SkeletonBlock className="h-4 w-32" />
        <div className="mt-3 space-y-3 rounded-xs border border-border-5 bg-background-5 p-3">
          <div className="flex items-center justify-between">
            <div className="space-y-2">
              <SkeletonBlock className="h-4 w-36" />
              <SkeletonBlock className="h-3 w-44" />
            </div>
            <SkeletonBlock className="h-8 w-14 rounded-full" />
          </div>
          <div className="flex items-center gap-2 border-t border-border-5 pt-2">
            <SkeletonBlock className="h-8 w-16" />
            <SkeletonBlock className="h-3 w-16" />
            <SkeletonBlock className="ml-auto h-8 w-20" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function AdminAccessSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />
      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <div className="mb-4 flex items-center gap-2">
          <SkeletonBlock className="h-4 w-4" />
          <SkeletonBlock className="h-4 w-32" />
          <SkeletonBlock className="ml-auto h-5 w-8" />
        </div>
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="flex items-center justify-between rounded-xs border border-border-5 bg-background-5 px-4 py-3"
            >
              <div className="space-y-2">
                <SkeletonBlock className="h-4 w-36" />
                <SkeletonBlock className="h-3 w-48" />
              </div>
              <div className="flex items-center gap-2">
                <SkeletonBlock className="h-8 w-20" />
                <SkeletonBlock className="h-8 w-20" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ClientDashboardLayoutSkeleton() {
  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-background text-text-primary">
      <div className="h-14 shrink-0 border-b border-border-5 bg-surface px-5">
        <div className="flex h-full items-center justify-between">
          <SkeletonBlock className="h-6 w-36" />
          <SkeletonBlock className="h-8 w-48" />
        </div>
      </div>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="hidden w-64 shrink-0 border-r border-border-5 bg-surface p-4 lg:block">
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <SkeletonBlock key={index} className="h-9 w-full" />
            ))}
          </div>
        </aside>
        <section className="min-w-0 flex-1 overflow-hidden bg-background-dashboard p-5">
          <div className="space-y-4">
            <SkeletonHeader />
            <SkeletonBlock className="h-32 w-full" />
            <SkeletonBlock className="h-56 w-full" />
          </div>
        </section>
      </div>
    </main>
  );
}

export function ClientHomeSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonBlock className="h-20 w-full" />

      <div className="flex items-start justify-between gap-3">
        <SkeletonHeader />
        <SkeletonBlock className="h-9 w-28" />
      </div>

      <div className="rounded-xs border border-border-5 bg-background-5 p-3">
        <SkeletonBlock className="h-4 w-56" />
        <SkeletonBlock className="mt-2 h-3 w-72 max-w-full" />
      </div>

      <div className="grid grid-cols-2 overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <div
            key={index}
            className={`p-5 ${index !== 5 ? "border-r border-border-5" : ""}`}
          >
            <SkeletonBlock className="h-8 w-16" />
            <SkeletonBlock className="mt-2 h-4 w-20" />
            <SkeletonBlock className="mt-2 h-3 w-24" />
          </div>
        ))}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <SkeletonBlock className="h-6 w-28" />
          <SkeletonBlock className="h-9 w-36" />
        </div>
        <div className="overflow-hidden rounded-xs border border-border-5 bg-surface">
          <div className="border-b border-border-5 px-4 py-3">
            <SkeletonBlock className="h-4 w-full" />
          </div>
          <SkeletonTableRows rows={5} columns={7} />
        </div>
      </div>

      <div>
        <SkeletonBlock className="mb-2 h-6 w-56" />
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 2 }).map((_, index) => (
            <div
              key={index}
              className="rounded-xs border border-border-5 bg-surface p-4"
            >
              <SkeletonBlock className="h-4 w-32" />
              <div className="mt-3 space-y-2">
                {Array.from({ length: 4 }).map((__, rowIndex) => (
                  <div
                    key={rowIndex}
                    className="flex items-center justify-between border-b border-border-5 pb-2 last:border-0"
                  >
                    <SkeletonBlock className="h-3 w-16" />
                    <SkeletonBlock className="h-3 w-24" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ClientAgentDetailSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <SkeletonBlock className="h-8 w-44" />
            <SkeletonBlock className="h-6 w-16" />
          </div>
          <SkeletonBlock className="h-4 w-72 max-w-full" />
        </div>
        <SkeletonBlock className="h-9 w-24" />
      </div>

      <div className="grid overflow-hidden rounded-xs border border-border-5 bg-surface md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className={index !== 3 ? "border-r border-border-5 p-5" : "p-5"}
          >
            <SkeletonBlock className="h-8 w-20" />
            <SkeletonBlock className="mt-2 h-4 w-24" />
          </div>
        ))}
      </div>

      <div className="rounded-xs border border-border-5 bg-surface">
        <div className="border-b border-border-5 px-4 py-3">
          <SkeletonBlock className="h-4 w-24" />
        </div>
        <div className="border-b border-border-5 px-3 py-2">
          <SkeletonBlock className="h-3 w-full" />
        </div>
        <SkeletonTableRows rows={7} columns={4} />
      </div>
    </div>
  );
}

export function ClientIntegrationsSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full">
      <SkeletonHeader />

      <div className="mt-5 space-y-4">
        <div className="rounded-xs border border-border-5 bg-surface p-4">
          <SkeletonBlock className="h-4 w-40" />
          <SkeletonBlock className="mt-2 h-3 w-72 max-w-full" />

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="rounded-xs border border-border-5 bg-background-5 px-3 py-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="space-y-2">
                    <SkeletonBlock className="h-4 w-24" />
                    <SkeletonBlock className="h-3 w-28" />
                  </div>
                  <SkeletonBlock className="h-8 w-20" />
                </div>
                {index === 0 ? (
                  <div className="mt-3 space-y-3">
                    <SkeletonBlock className="h-11 w-full" />
                    <SkeletonBlock className="h-11 w-full" />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-4 space-y-3">
          <SkeletonBlock className="h-4 w-44" />
          <SkeletonBlock className="h-3 w-80 max-w-full" />
          <div className="grid gap-3 md:grid-cols-3">
            <SkeletonBlock className="h-11 w-full" />
            <SkeletonBlock className="h-11 w-full" />
            <SkeletonBlock className="h-11 w-full" />
          </div>
          <SkeletonBlock className="h-9 w-44" />
        </div>

        <div className="rounded-xs border border-border-5 bg-surface p-4">
          <SkeletonBlock className="h-4 w-32" />
          <SkeletonBlock className="mt-2 h-3 w-96 max-w-full" />
        </div>
      </div>
    </div>
  );
}

export function ClientNewAgentSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />

      <div className="rounded-xs border border-border-5 bg-surface p-4">
        <SkeletonBlock className="h-5 w-36" />
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="rounded-xs border border-border-5 bg-background-5 px-3 py-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-2">
                  <SkeletonBlock className="h-4 w-28" />
                  <SkeletonBlock className="h-3 w-full" />
                </div>
                <SkeletonBlock className="h-5 w-20" />
              </div>
              <SkeletonBlock className="mt-3 h-8 w-28" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ClientRequestStatusSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full space-y-4">
      <SkeletonHeader />

      <div className="rounded-xs border border-border-5 bg-surface p-4 md:p-5">
        <div className="flex items-center justify-between">
          <SkeletonBlock className="h-3 w-20" />
          <SkeletonBlock className="h-6 w-20" />
        </div>
        <SkeletonBlock className="mt-2 h-4 w-24" />

        <div className="mt-5 space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="relative flex items-start gap-3">
              <SkeletonBlock className="h-6 w-6 rounded-full" />
              <div>
                <SkeletonBlock className="h-4 w-32" />
                <SkeletonBlock className="mt-1 h-3 w-24" />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-5 rounded-xs border border-border-5 bg-background-5 p-3">
          <SkeletonBlock className="h-3 w-20" />
          <SkeletonBlock className="mt-2 h-4 w-full" />
          <SkeletonBlock className="mt-1 h-4 w-3/4" />
        </div>
      </div>
    </div>
  );
}

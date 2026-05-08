import Link from "next/link";

export default function TermsConditionsPage() {
  return (
    <main className="min-h-screen bg-background text-text-primary">
      <section className="border-b border-border-5 bg-background-blue/95">
        <div className="mx-auto w-full max-w-425 px-4 py-10 md:px-8 lg:px-12 xl:px-16">
          <p className="text-xs font-semibold uppercase tracking-wider text-blue-200">
            Legal
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-white sm:text-4xl">
            Terms & Conditions
          </h1>
          <p className="mt-4 max-w-3xl text-sm text-blue-100 sm:text-base">
            These Terms govern your access to and use of Tigeri.ai products,
            services, websites, and related applications. Please read them
            carefully before using the platform.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-blue-100">
            <span className="rounded-xs border border-white/20 px-3 py-1">
              Effective Date: 28 April 2026
            </span>
            <Link
              href="/privacy-policy"
              className="rounded-xs border border-white/20 px-3 py-1 transition hover:bg-white/10"
            >
              View Privacy Policy
            </Link>
            <Link
              href="/"
              className="rounded-xs border border-white/20 px-3 py-1 transition hover:bg-white/10"
            >
              Back to Home
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-425 px-4 py-10 md:px-8 lg:px-12 xl:px-16">
        <div className="rounded-xs border border-border-5 bg-surface p-6 sm:p-8 lg:p-10">
          <div className="space-y-8">
            <article className="space-y-3">
              <h2 className="text-xl font-semibold">1. Acceptance of Terms</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                By accessing or using Tigeri.ai, you agree to be bound by these
                Terms and all applicable laws and regulations. If you do not
                agree, you must not use the platform.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">2. Services and Scope</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Tigeri.ai provides AI-enabled automation and operational tooling
                for business workflows, including but not limited to invoicing,
                expense handling, administrative tasks, staffing coordination,
                and booking support.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                3. Account Responsibilities
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                You are responsible for maintaining account credentials,
                controlling user access, and ensuring all data submitted is
                accurate, lawful, and authorized for use within your
                organization.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">4. Acceptable Use</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                You agree not to misuse the platform, attempt unauthorized
                access, reverse engineer protected components, upload malicious
                content, or use the services in ways that violate any law or
                third-party rights.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">5. Fees and Billing</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Paid subscriptions, if applicable, are billed according to your
                selected plan terms. You authorize Tigeri.ai to process payments
                for subscribed services and applicable taxes.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                6. Intellectual Property
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                All software, brand assets, documentation, and service
                components are owned by Tigeri.ai or its licensors. Except where
                expressly permitted, no rights are granted to copy, distribute,
                or create derivative works.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                7. Data and Confidentiality
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We process data according to our Privacy Policy and maintain
                reasonable safeguards for confidentiality and security. You
                retain responsibility for your organization’s compliance
                obligations and data governance controls.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">8. Warranty Disclaimer</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Services are provided on an &quot;as is&quot; and &quot;as
                available&quot; basis. To the fullest extent permitted by law,
                Tigeri.ai disclaims implied warranties including
                merchantability, fitness for a particular purpose, and
                non-infringement.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                9. Limitation of Liability
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Tigeri.ai will not be liable for indirect, incidental, special,
                consequential, or punitive damages, or for loss of profits,
                revenue, data, or goodwill arising from your use of the
                services.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">10. Changes and Contact</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We may update these Terms from time to time. Continued use of
                the services after updates become effective constitutes
                acceptance of the revised Terms. For legal inquiries, contact us
                at legal@tigeri.ai.
              </p>
            </article>
          </div>
        </div>
      </section>
    </main>
  );
}

import Link from "next/link";

export default function PrivacyPolicyPage() {
  return (
    <main className="min-h-screen bg-background text-text-primary">
      <section className="border-b border-border-5 bg-background-blue/95">
        <div className="mx-auto w-full max-w-425 px-4 py-10 md:px-8 lg:px-12 xl:px-16">
          <p className="text-xs font-semibold uppercase tracking-wider text-blue-200">
            Legal
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-white sm:text-4xl">
            Privacy Policy
          </h1>
          <p className="mt-4 max-w-3xl text-sm text-blue-100 sm:text-base">
            This Privacy Policy explains how Tigeri.ai collects, uses,
            discloses, and protects personal and organizational data when you
            use our website and services.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3 text-xs text-blue-100">
            <span className="rounded-xs border border-white/20 px-3 py-1">
              Effective Date: 28 April 2026
            </span>
            <Link
              href="/terms-conditions"
              className="rounded-xs border border-white/20 px-3 py-1 transition hover:bg-white/10"
            >
              View Terms & Conditions
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
              <h2 className="text-xl font-semibold">
                1. Information We Collect
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We may collect account details, business contact information,
                service usage data, operational inputs, and technical metadata
                such as IP address, browser type, and interaction logs.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                2. How We Use Information
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We use collected information to provide and improve services,
                process onboarding requests, secure the platform, communicate
                service updates, and comply with legal obligations.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                3. Legal Basis for Processing
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Depending on your region, we process personal data under
                contractual necessity, legitimate interests, consent, or legal
                compliance requirements as applicable.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                4. Data Sharing and Disclosure
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We do not sell personal data. We may share data with vetted
                service providers, infrastructure partners, and authorities when
                required by law or to protect rights, security, and platform
                integrity.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">5. Data Retention</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We retain information only as long as needed for legitimate
                business purposes, contractual obligations, legal requirements,
                and dispute resolution.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">6. Security Measures</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Tigeri.ai uses administrative, technical, and organizational
                controls designed to safeguard data. No system is completely
                secure, but we continuously improve controls and incident
                response readiness.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                7. International Transfers
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Where data is transferred across jurisdictions, we apply
                appropriate legal safeguards and contractual protections
                required by applicable data protection laws.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">8. Your Rights</h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                Subject to local law, you may have rights to access, correct,
                delete, restrict, or port your data, and to object to certain
                processing activities.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                9. Cookies and Analytics
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We may use cookies and similar technologies to maintain session
                integrity, understand product usage, and improve user
                experience. You can manage cookie preferences through browser
                settings.
              </p>
            </article>

            <article className="space-y-3">
              <h2 className="text-xl font-semibold">
                10. Policy Updates and Contact
              </h2>
              <p className="text-sm leading-7 text-text-secondary sm:text-base">
                We may revise this Privacy Policy periodically. Material updates
                will be reflected by the effective date above. For privacy
                requests, contact privacy@tigeri.ai.
              </p>
            </article>
          </div>
        </div>
      </section>
    </main>
  );
}

import CustomSelect from "../../ui/custom-select";

const frameworkOptions = [
  "GDPR (EU/UK)",
  "HIPAA (US Healthcare)",
  "SOX (Public Companies)",
  "PCI-DSS (Payments)",
  "FCA / PRA (UK Finance)",
  "DORA (EU Digital Operations)",
  "CCPA (California Privacy)",
  "ISO 27001",
  "NIST CSF",
  "EU AI Act",
  "NERC CIP (Energy)",
  "BASEL III (Banking)",
];

export default function RegulatoryFrameworkSubForm() {
  return (
    <form className="space-y-8 py-6 md:py-8">
      <section className="space-y-5">
        <p className="text-base font-medium text-text-primary">
          Compliance Standards Applicable
        </p>
        <div className="mt-4 flex flex-wrap gap-3 border-t border-border-10 pt-5">
          {frameworkOptions.map((item) => (
            <label
              key={item}
              className="inline-flex cursor-pointer items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-4 py-2.5 text-base text-text-primary"
            >
              <input
                data-optional="true"
                type="checkbox"
                className="h-4 w-4 accent-background-blue"
              />
              <span>{item}</span>
            </label>
          ))}
        </div>
      </section>

      <div className="grid gap-5 border-t border-border-10 pt-6 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          Primary Regulatory Region
          <CustomSelect
            data-optional="true"
            className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue"
          >
            <option>European Union</option>
            <option>United Kingdom</option>
            <option>United States</option>
            <option>Multi-jurisdiction</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Next Regulatory Audit
          <input
            data-optional="true"
            type="date"
            className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue"
          />
        </label>
      </div>

      <label className="block text-sm text-text-secondary">
        Specific Compliance Constraints or Recent Findings
        <textarea
          data-optional="true"
          rows={3}
          placeholder="e.g. We received an ICO advisory in Q3 2024 regarding data minimisation in our analytics pipeline. Our SOX auditor flagged manual evidence collection as a control weakness..."
          className="mt-2 w-full rounded-xs border border-border-5 bg-background-5 px-4 py-3 text-base text-text-primary placeholder:text-text-secondary outline-none focus:border-background-blue"
        />
      </label>
    </form>
  );
}

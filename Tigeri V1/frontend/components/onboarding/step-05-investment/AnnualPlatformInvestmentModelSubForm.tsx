"use client";

import { useState } from "react";
import CustomSelect from "../../ui/custom-select";

const tiers = [
  {
    title: "Tier 1 - Starter",
    subtitle: "3-5 Use Cases",
    value: "$150K / yr",
    active: true,
  },
  {
    title: "Tier 2 - Growth",
    subtitle: "Unlimited Use Cases",
    value: "$350K / yr",
  },
  {
    title: "Tier 3 - Enterprise",
    subtitle: "On-prem + Fine-tuning",
    value: "$900K / yr",
  },
  {
    title: "Tier 4 - Strategic",
    subtitle: "Multi-subsidiary",
    value: "$2M+ / yr",
  },
];

export default function AnnualPlatformInvestmentModelSubForm() {
  const defaultTier =
    tiers.find((tier) => tier.active)?.title ?? tiers[0].title;
  const [selectedTier, setSelectedTier] = useState(defaultTier);
  const selectClassName =
    "mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue";

  return (
    <form className="space-y-8 py-6 md:py-8">
      <div className="grid overflow-hidden rounded-xs border border-border-5 md:grid-cols-4">
        {tiers.map((tier) => (
          <button
            key={tier.title}
            type="button"
            onClick={() => setSelectedTier(tier.title)}
            aria-pressed={selectedTier === tier.title}
            className={`border-r border-border-5 px-5 py-4 text-left transition-colors last:border-r-0 ${selectedTier === tier.title ? "bg-background-blue text-white" : "bg-background-5 text-text-primary hover:bg-background-10"}`}
          >
            <p
              className={`text-base ${selectedTier === tier.title ? "text-white/80" : "text-text-secondary"}`}
            >
              {tier.title}
            </p>
            <p
              className={`mt-2 text-lg ${selectedTier === tier.title ? "text-white" : "text-text-primary"}`}
            >
              {tier.subtitle}
            </p>
            <p
              className={`mt-2 text-2xl font-semibold ${selectedTier === tier.title ? "text-white" : "text-text-primary"}`}
            >
              {tier.value}
            </p>
          </button>
        ))}
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          * Annual Platform Budget (Indicative)
          <CustomSelect className={selectClassName}>
            <option>Under $100K</option>
            <option>$100K - $250K</option>
            <option>$250K - $500K</option>
            <option>$500K+</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Target Contract Start Date
          <input data-optional="true" type="date" className={selectClassName} />
        </label>

        <label className="block text-sm text-text-secondary">
          * Economic Buyer
          <CustomSelect className={selectClassName}>
            <option>CIO / CTO</option>
            <option>COO</option>
            <option>CFO</option>
            <option>Business Unit Head</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Expected ROI Horizon
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Under 6 months</option>
            <option>6 - 12 months</option>
            <option>12 - 24 months</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Annual Internal Tooling Spend (Current)
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Under $500K</option>
            <option>$500K - $1M</option>
            <option>$1M - $5M</option>
            <option>$5M+</option>
          </CustomSelect>
        </label>
      </div>
    </form>
  );
}

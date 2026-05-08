"use client";

import { useState } from "react";
import CustomSelect from "../../ui/custom-select";

const tokenOptions = [
  "32K tokens",
  "128K tokens",
  "200K tokens",
  "Unlimited / Chunked",
];

export default function L3AIReasoningLayerForm() {
  const [selectedTokenOption, setSelectedTokenOption] = useState(
    tokenOptions[1],
  );
  const selectClassName =
    "mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue";

  return (
    <form className="space-y-8 py-6 md:py-8">
      <div className="grid gap-5 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          Preferred Foundation Model
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Anthropic Claude (recommended)</option>
            <option>OpenAI GPT</option>
            <option>Azure OpenAI</option>
            <option>Hybrid model routing</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Human-in-the-loop Threshold
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Review every output before sending</option>
            <option>Review only high-risk outputs</option>
            <option>Review a random sample of outputs</option>
            <option>Fully automated (no manual review)</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Reasoning Complexity Budget
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Standard (fast, cost-efficient)</option>
            <option>High reasoning quality</option>
            <option>Balanced adaptive</option>
          </CustomSelect>
        </label>
      </div>

      <section className="border-t border-border-10 pt-6">
        <p className="text-base font-medium text-text-primary">
          Context Window Requirements
        </p>

        <div className="mt-5">
          <p className="mb-3 text-sm text-text-secondary">
            Maximum context length needed per generation task
          </p>
          <div className="grid overflow-hidden rounded-xs border border-border-5 md:grid-cols-4">
            {tokenOptions.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setSelectedTokenOption(option)}
                aria-pressed={selectedTokenOption === option}
                className={`px-4 py-3 text-base ${
                  selectedTokenOption === option
                    ? "bg-background-blue text-white"
                    : "border-r border-border-5 bg-background-5 text-text-primary last:border-r-0"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      </section>
    </form>
  );
}

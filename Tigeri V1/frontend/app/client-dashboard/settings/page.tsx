"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  addEmployee,
  getFinancialConfig,
  removeEmployee,
  updateFinancialConfig,
} from "@/lib/api";
import { sanitizeBusinessText } from "@/lib/input-validation";
import type { FinancialConfig, FinancialConfigEmployee } from "@/lib/type";
import { PageErrorState } from "@/components/ui/page-states";
import CustomSelect from "@/components/ui/custom-select";

// ── tiny inline skeleton ──────────────────────────────────────────────
function SettingsSkeleton() {
  return (
    <div className="mx-auto w-full max-w-full animate-pulse space-y-4">
      <div className="h-8 w-48 rounded-xs bg-background-5" />
      <div className="h-4 w-80 rounded-xs bg-background-5" />
      <div className="h-40 rounded-xs bg-background-5" />
      <div className="h-56 rounded-xs bg-background-5" />
    </div>
  );
}

const CURRENCY_OPTIONS = [
  "USD",
  "SGD",
  "EUR",
  "GBP",
  "AUD",
  "CAD",
  "JPY",
  "INR",
  "MYR",
  "HKD",
];

export default function SettingsPage() {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── financial config form state ──
  const [baseCurrency, setBaseCurrency] = useState("USD");
  const [taxRate, setTaxRate] = useState("0");
  const [taxName, setTaxName] = useState("TAX");
  const [taxInclusive, setTaxInclusive] = useState(false);
  const [fxEnabled, setFxEnabled] = useState(false);
  const [autoApprove, setAutoApprove] = useState(true);
  const [country, setCountry] = useState("");
  const [timezone, setTimezone] = useState("");
  const [expenseCategories, setExpenseCategories] = useState<string[]>([]);
  const [newCategory, setNewCategory] = useState("");
  const [categoryCodeMap, setCategoryCodeMap] = useState<
    Record<string, string>
  >({});
  const [newCodeKey, setNewCodeKey] = useState("");
  const [newCodeVal, setNewCodeVal] = useState("");

  // track initial values for dirty check
  const [initConfig, setInitConfig] = useState<Omit<
    FinancialConfig,
    "employees"
  > | null>(null);

  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [configSuccess, setConfigSuccess] = useState<string | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  // ── employee form state ──
  const [employees, setEmployees] = useState<FinancialConfigEmployee[]>([]);
  const [empChannel, setEmpChannel] = useState("telegram");
  const [empSender, setEmpSender] = useState("");
  const [empName, setEmpName] = useState("");
  const [empId, setEmpId] = useState("");
  const [empDept, setEmpDept] = useState("");
  const [isAddingEmp, setIsAddingEmp] = useState(false);
  const [empError, setEmpError] = useState<string | null>(null);
  const [empSuccess, setEmpSuccess] = useState<string | null>(null);
  const [removingKey, setRemovingKey] = useState<string | null>(null);

  // ── load ──────────────────────────────────────────────────────────
  useEffect(() => {
    async function load() {
      try {
        const data = await getFinancialConfig();
        applyConfig(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load settings",
        );
      } finally {
        setIsLoading(false);
      }
    }
    void load();
  }, []);

  function applyConfig(data: FinancialConfig) {
    setBaseCurrency(data.base_currency);
    setTaxRate(String(data.tax_rate));
    setTaxName(data.tax_name);
    setTaxInclusive(data.tax_inclusive);
    setFxEnabled(data.fx_enabled);
    setAutoApprove(data.auto_approve_expenses);
    setCountry(data.country ?? "");
    setTimezone(data.timezone ?? "");
    setExpenseCategories(data.expense_categories);
    setCategoryCodeMap(data.category_code_map);
    setEmployees(data.employees);
    setInitConfig({
      base_currency: data.base_currency,
      tax_rate: data.tax_rate,
      tax_name: data.tax_name,
      tax_inclusive: data.tax_inclusive,
      fx_enabled: data.fx_enabled,
      auto_approve_expenses: data.auto_approve_expenses,
      country: data.country ?? "",
      timezone: data.timezone ?? "",
      expense_categories: data.expense_categories,
      category_code_map: data.category_code_map,
    });
  }

  // ── dirty check ───────────────────────────────────────────────────
  const hasConfigChanges = (() => {
    if (!initConfig) return false;
    return (
      baseCurrency !== initConfig.base_currency ||
      parseFloat(taxRate) !== initConfig.tax_rate ||
      taxName !== initConfig.tax_name ||
      taxInclusive !== initConfig.tax_inclusive ||
      fxEnabled !== initConfig.fx_enabled ||
      autoApprove !== initConfig.auto_approve_expenses ||
      country !== initConfig.country ||
      timezone !== initConfig.timezone ||
      JSON.stringify(expenseCategories) !==
        JSON.stringify(initConfig.expense_categories) ||
      JSON.stringify(categoryCodeMap) !==
        JSON.stringify(initConfig.category_code_map)
    );
  })();

  // ── save financial config ─────────────────────────────────────────
  const onSaveConfig = async () => {
    setConfigError(null);
    setConfigSuccess(null);
    const parsedTax = parseFloat(taxRate);
    if (isNaN(parsedTax) || parsedTax < 0 || parsedTax > 1) {
      setConfigError("Tax rate must be between 0 and 1 (e.g. 0.09 for 9%).");
      return;
    }
    setIsSavingConfig(true);
    try {
      await updateFinancialConfig({
        base_currency: baseCurrency,
        tax_rate: parsedTax,
        tax_name: taxName,
        tax_inclusive: taxInclusive,
        fx_enabled: fxEnabled,
        auto_approve_expenses: autoApprove,
        country: country || undefined,
        timezone: timezone || undefined,
        expense_categories: expenseCategories,
        category_code_map: categoryCodeMap,
      });
      setConfigSuccess("Financial settings saved.");
      setInitConfig({
        base_currency: baseCurrency,
        tax_rate: parsedTax,
        tax_name: taxName,
        tax_inclusive: taxInclusive,
        fx_enabled: fxEnabled,
        auto_approve_expenses: autoApprove,
        country,
        timezone,
        expense_categories: expenseCategories,
        category_code_map: categoryCodeMap,
      });
    } catch (err) {
      setConfigError(
        err instanceof Error ? err.message : "Failed to save settings.",
      );
    } finally {
      setIsSavingConfig(false);
    }
  };

  // ── expense categories helpers ────────────────────────────────────
  const onAddCategory = () => {
    const trimmed = newCategory.trim().toLowerCase();
    if (!trimmed || expenseCategories.includes(trimmed)) return;
    setExpenseCategories((prev) => [...prev, trimmed]);
    setNewCategory("");
  };

  const onRemoveCategory = (cat: string) => {
    setExpenseCategories((prev) => prev.filter((c) => c !== cat));
  };

  // ── category code map helpers ─────────────────────────────────────
  const onAddCodeMapping = () => {
    const key = newCodeKey.trim();
    const val = newCodeVal.trim().toLowerCase();
    if (!key || !val) return;
    setCategoryCodeMap((prev) => ({ ...prev, [key]: val }));
    setNewCodeKey("");
    setNewCodeVal("");
  };

  const onRemoveCodeMapping = (key: string) => {
    setCategoryCodeMap((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  // ── add employee ──────────────────────────────────────────────────
  const onAddEmployee = async () => {
    setEmpError(null);
    setEmpSuccess(null);
    if (!empSender.trim() || !empName.trim()) {
      setEmpError("Sender ID and name are required.");
      return;
    }
    setIsAddingEmp(true);
    try {
      const res = await addEmployee({
        channel: empChannel,
        sender: empSender.trim(),
        name: empName.trim(),
        employee_id: empId.trim(),
        dept: empDept.trim(),
      });
      setEmployees((prev) => [
        ...prev,
        {
          key: res.key,
          channel: empChannel,
          sender: empSender.trim(),
          name: res.name,
          employee_id: empId.trim(),
          dept: empDept.trim(),
        },
      ]);
      setEmpSender("");
      setEmpName("");
      setEmpId("");
      setEmpDept("");
      setEmpSuccess(`${res.name} registered.`);
    } catch (err) {
      setEmpError(
        err instanceof Error ? err.message : "Failed to add employee.",
      );
    } finally {
      setIsAddingEmp(false);
    }
  };

  // ── remove employee ───────────────────────────────────────────────
  const onRemoveEmployee = async (emp: FinancialConfigEmployee) => {
    setRemovingKey(emp.key);
    try {
      await removeEmployee(emp.channel, emp.sender);
      setEmployees((prev) => prev.filter((e) => e.key !== emp.key));
    } catch (err) {
      setEmpError(
        err instanceof Error ? err.message : "Failed to remove employee.",
      );
    } finally {
      setRemovingKey(null);
    }
  };

  // ── render ────────────────────────────────────────────────────────
  if (isLoading) return <SettingsSkeleton />;

  return (
    <div className="mx-auto w-full max-w-full">
      <h1 className="text-2xl font-semibold text-text-primary">Settings</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Manage financial configuration and staff members for your agents.
      </p>

      {error ? (
        <div className="mt-4">
          <PageErrorState message={error} />
        </div>
      ) : null}

      {/* ── Financial Config ── */}
      <div className="mt-5 rounded-xs border border-border-5 bg-surface p-4 space-y-4">
        <div>
          <p className="text-sm font-medium text-text-primary">
            Financial Configuration
          </p>
          <p className="mt-0.5 text-xs text-text-secondary">
            Currency, tax, FX and expense approval rules used by your agents.
          </p>
        </div>

        {configError ? (
          <p className="text-sm text-red-500">{configError}</p>
        ) : null}
        {configSuccess ? (
          <p className="text-sm text-emerald-600">{configSuccess}</p>
        ) : null}

        {/* Row 1 — currency / tax */}
        <div className="grid gap-3 md:grid-cols-3">
          <label className="block">
            <span className="mb-1 block text-xs text-text-muted">
              Base Currency
            </span>
            <CustomSelect
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary outline-none focus:border-background-blue"
            >
              {CURRENCY_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </CustomSelect>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-text-muted">
              Tax Rate (e.g. 0.09 = 9%)
            </span>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={taxRate}
              onChange={(e) => setTaxRate(e.target.value)}
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              placeholder="0.09"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-text-muted">Tax Name</span>
            <input
              value={taxName}
              maxLength={20}
              onChange={(e) =>
                setTaxName(sanitizeBusinessText(e.target.value, 20))
              }
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              placeholder="GST, VAT, ..."
            />
          </label>
        </div>

        {/* Row 2 — toggles */}
        <div className="grid gap-3 md:grid-cols-3">
          <ToggleField
            label="Amounts include tax"
            description="Are receipt amounts tax-inclusive?"
            checked={taxInclusive}
            onChange={setTaxInclusive}
          />
          <ToggleField
            label="Enable FX conversion"
            description="Convert foreign currency to base"
            checked={fxEnabled}
            onChange={setFxEnabled}
          />
          <ToggleField
            label="Auto-approve expenses"
            description="Skip approval step for expenses"
            checked={autoApprove}
            onChange={setAutoApprove}
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs text-text-muted">Country</span>
            <input
              value={country}
              maxLength={60}
              onChange={(e) =>
                setCountry(sanitizeBusinessText(e.target.value, 60))
              }
              placeholder="e.g. Singapore, India"
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-text-muted">Timezone</span>
            <input
              value={timezone}
              maxLength={60}
              onChange={(e) => setTimezone(e.target.value.trim())}
              placeholder="e.g. Asia/Singapore, Asia/Kolkata"
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
            />
          </label>
        </div>

        {/* Expense categories */}
        <div>
          <p className="text-xs font-medium text-text-muted mb-2">
            Expense Categories
          </p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {expenseCategories.map((cat) => (
              <span
                key={cat}
                className="inline-flex items-center gap-1 rounded-full border border-border-5 bg-background-5 px-2.5 py-0.5 text-xs text-text-secondary"
              >
                {cat}
                <button
                  type="button"
                  onClick={() => onRemoveCategory(cat)}
                  className="ml-0.5 text-text-muted hover:text-text-danger"
                  aria-label={`Remove category ${cat}`}
                >
                  ×
                </button>
              </span>
            ))}
            {expenseCategories.length === 0 ? (
              <span className="text-xs text-text-muted">
                No categories yet.
              </span>
            ) : null}
          </div>
          <div className="flex gap-2">
            <input
              value={newCategory}
              maxLength={40}
              onChange={(e) =>
                setNewCategory(sanitizeBusinessText(e.target.value, 40))
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onAddCategory();
                }
              }}
              placeholder="e.g. logistics"
              className="h-9 flex-1 rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
            />
            <button
              type="button"
              onClick={onAddCategory}
              disabled={!newCategory.trim()}
              className="rounded-xs bg-background-blue px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>

        {/* Category code map */}
        <div>
          <p className="text-xs font-medium text-text-muted mb-2">
            HR Claim Code → Category Map
          </p>
          {Object.keys(categoryCodeMap).length > 0 ? (
            <div className="mb-2 space-y-1 rounded-xs border border-border-5 bg-background-5 p-2">
              {Object.entries(categoryCodeMap).map(([k, v]) => (
                <div
                  key={k}
                  className="flex items-center justify-between gap-2 text-xs text-text-secondary"
                >
                  <span>
                    <span className="font-medium text-text-primary">{k}</span>
                    {" → "}
                    {v}
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveCodeMapping(k)}
                    className="text-text-muted hover:text-text-danger"
                    aria-label={`Remove mapping ${k}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mb-2 text-xs text-text-muted">No mappings yet.</p>
          )}
          <div className="flex gap-2">
            <input
              value={newCodeKey}
              maxLength={40}
              onChange={(e) =>
                setNewCodeKey(sanitizeBusinessText(e.target.value, 40))
              }
              placeholder="HR code e.g. Wst-gc00"
              className="h-9 flex-1 rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
            />
            <input
              value={newCodeVal}
              maxLength={40}
              onChange={(e) =>
                setNewCodeVal(sanitizeBusinessText(e.target.value, 40))
              }
              placeholder="Category name"
              className="h-9 flex-1 rounded-xs border border-border-5 bg-background-5 px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
            />
            <button
              type="button"
              onClick={onAddCodeMapping}
              disabled={!newCodeKey.trim() || !newCodeVal.trim()}
              className="rounded-xs bg-background-blue px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>

        <button
          type="button"
          onClick={() => void onSaveConfig()}
          disabled={!hasConfigChanges || isSavingConfig}
          className="rounded-lg bg-background-blue px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSavingConfig ? "Saving..." : "Save Financial Settings"}
        </button>
      </div>

      {/* ── Employee Management ── */}
      <div className="mt-4 rounded-xs border border-border-5 bg-surface p-4 space-y-4">
        <div>
          <p className="text-sm font-medium text-text-primary">
            Staff / Employee Mapping
          </p>
          <p className="mt-0.5 text-xs text-text-secondary">
            Map Telegram chat IDs or WhatsApp numbers to named employees for
            expense tracking.
          </p>
        </div>

        {empError ? <p className="text-sm text-red-500">{empError}</p> : null}
        {empSuccess ? (
          <p className="text-sm text-emerald-600">{empSuccess}</p>
        ) : null}

        {/* Employee table */}
        {employees.length > 0 ? (
          <div className="overflow-x-auto rounded-xs border border-border-5">
            <table className="w-full text-xs text-text-secondary">
              <thead>
                <tr className="border-b border-border-5 bg-background-5 text-left text-text-muted">
                  <th className="px-3 py-2 font-medium">Channel</th>
                  <th className="px-3 py-2 font-medium">Sender ID</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Employee ID</th>
                  <th className="px-3 py-2 font-medium">Dept</th>
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => (
                  <tr
                    key={emp.key}
                    className="border-b border-border-5 last:border-0"
                  >
                    <td className="px-3 py-2 capitalize">{emp.channel}</td>
                    <td className="px-3 py-2 font-mono">{emp.sender}</td>
                    <td className="px-3 py-2 text-text-primary font-medium">
                      {emp.name}
                    </td>
                    <td className="px-3 py-2">{emp.employee_id || "—"}</td>
                    <td className="px-3 py-2">{emp.dept || "—"}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void onRemoveEmployee(emp)}
                        disabled={removingKey === emp.key}
                        className="inline-flex items-center gap-1 rounded border border-border-5 px-2 py-1 text-text-muted hover:border-red-400 hover:text-text-danger disabled:opacity-50"
                        aria-label={`Remove ${emp.name}`}
                      >
                        <Trash2 size={12} />
                        {removingKey === emp.key ? "Removing..." : "Remove"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-text-muted">
            No staff members registered yet.
          </p>
        )}

        {/* Add employee form */}
        <div className="rounded-xs border border-border-5 bg-background-5 p-3 space-y-3">
          <p className="text-xs font-medium text-text-primary">
            Add Staff Member
          </p>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Channel
              </span>
              <CustomSelect
                value={empChannel}
                onChange={(e) => setEmpChannel(e.target.value)}
                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary outline-none focus:border-background-blue"
              >
                <option value="telegram">Telegram</option>
                <option value="whatsapp">360dialog</option>
                <option value="twilio_whatsapp">Twilio</option>
              </CustomSelect>
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Sender ID / Phone
              </span>
              <input
                value={empSender}
                maxLength={80}
                onChange={(e) =>
                  setEmpSender(sanitizeBusinessText(e.target.value, 80))
                }
                placeholder="Chat ID or +1234567890"
                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Full Name
              </span>
              <input
                value={empName}
                maxLength={80}
                onChange={(e) =>
                  setEmpName(sanitizeBusinessText(e.target.value, 80))
                }
                placeholder="e.g. Aaron Low"
                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Employee ID (optional)
              </span>
              <input
                value={empId}
                maxLength={40}
                onChange={(e) =>
                  setEmpId(sanitizeBusinessText(e.target.value, 40))
                }
                placeholder="e.g. E024"
                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-text-muted">
                Department (optional)
              </span>
              <input
                value={empDept}
                maxLength={60}
                onChange={(e) =>
                  setEmpDept(sanitizeBusinessText(e.target.value, 60))
                }
                placeholder="e.g. Operations"
                className="h-11 w-full rounded-xs border border-border-5 bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-background-blue"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => void onAddEmployee()}
            disabled={isAddingEmp || !empSender.trim() || !empName.trim()}
            className="rounded-lg bg-background-blue px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isAddingEmp ? "Adding..." : "Add Staff Member"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Toggle field component ────────────────────────────────────────────
function ToggleField({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xs border border-border-5 bg-background-5 px-3 py-2.5">
      <div>
        <p className="text-xs font-medium text-text-primary">{label}</p>
        <p className="mt-0.5 text-xs text-text-muted">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-background-blue" : "bg-border-5"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-0" : "-translate-x-3.5"
          }`}
        />
      </button>
    </div>
  );
}

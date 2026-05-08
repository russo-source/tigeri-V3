import CustomSelect from "../../ui/custom-select";
import {
  isValidEmailFormat,
  sanitizeBusinessText,
  sanitizeEmailInput,
  sanitizePersonName,
} from "@/lib/input-validation";

const countryCodeOptions = [
  { label: "United States (+1)", value: "+1" },
  { label: "Canada (+1)", value: "+1" },
  { label: "United Kingdom (+44)", value: "+44" },
  { label: "India (+91)", value: "+91" },
  { label: "Australia (+61)", value: "+61" },
  { label: "Germany (+49)", value: "+49" },
  { label: "France (+33)", value: "+33" },
  { label: "Spain (+34)", value: "+34" },
  { label: "Italy (+39)", value: "+39" },
  { label: "Netherlands (+31)", value: "+31" },
  { label: "Switzerland (+41)", value: "+41" },
  { label: "Sweden (+46)", value: "+46" },
  { label: "Norway (+47)", value: "+47" },
  { label: "Denmark (+45)", value: "+45" },
  { label: "United Arab Emirates (+971)", value: "+971" },
  { label: "Saudi Arabia (+966)", value: "+966" },
  { label: "Singapore (+65)", value: "+65" },
  { label: "Japan (+81)", value: "+81" },
  { label: "South Korea (+82)", value: "+82" },
  { label: "China (+86)", value: "+86" },
  { label: "Brazil (+55)", value: "+55" },
  { label: "Mexico (+52)", value: "+52" },
  { label: "South Africa (+27)", value: "+27" },
  { label: "Nigeria (+234)", value: "+234" },
  { label: "New Zealand (+64)", value: "+64" },
];

export default function OrganizationSubStepAForm() {
  const inputClassName =
    "mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary placeholder:text-text-secondary outline-none focus:border-background-blue";
  const selectClassName =
    "mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue";

  return (
    <form className="space-y-8 py-6 md:py-8">
      <div className="grid gap-5 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          * Company Name
          <input
            type="text"
            maxLength={120}
            onInput={(event) => {
              event.currentTarget.value = sanitizeBusinessText(
                event.currentTarget.value,
                120,
              );
            }}
            placeholder="e.g. Acme Financial Group"
            className={inputClassName}
          />
        </label>

        <label className="block text-sm text-text-secondary">
          * Legal Entity Type
          <CustomSelect className={selectClassName}>
            <option>Select entity type</option>
            <option>Private Limited Company</option>
            <option>Public Company</option>
            <option>Partnership</option>
            <option>Non-Profit</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          * Primary Industry
          <CustomSelect className={selectClassName}>
            <option>Select industry</option>
            <option>Banking & Financial Services</option>
            <option>Healthcare</option>
            <option>Retail</option>
            <option>Technology</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          * Headquarters Region
          <CustomSelect className={selectClassName}>
            <option>Select region</option>
            <option>North America</option>
            <option>Europe</option>
            <option>Middle East</option>
            <option>Asia Pacific</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          * Annual Revenue (USD)
          <CustomSelect className={selectClassName}>
            <option>Select range</option>
            <option>$0 - $1M</option>
            <option>$1M - $10M</option>
            <option>$10M - $100M</option>
            <option>$100M+</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          * Total Headcount
          <CustomSelect className={selectClassName}>
            <option>Select range</option>
            <option>1 - 10</option>
            <option>11 - 50</option>
            <option>51 - 200</option>
            <option>200+</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Website Link
          <input
            data-optional="true"
            type="text"
            maxLength={120}
            onInput={(event) => {
              event.currentTarget.value = sanitizeBusinessText(
                event.currentTarget.value,
                120,
              );
            }}
            placeholder="e.g. https://www.example.com"
            className={inputClassName}
          />
        </label>

        <label className="block text-sm text-text-secondary">
          Prior AI Investment (Last 3 years)
          <CustomSelect data-optional="true" className={selectClassName}>
            <option>Select</option>
            <option>None</option>
            <option>Under $50k</option>
            <option>$50k - $250k</option>
            <option>$250k+</option>
          </CustomSelect>
        </label>
      </div>

      <div className="pt-2">
        <p className="text-base font-medium text-text-primary">
          Primary Contact
        </p>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          * Full Name
          <input
            type="text"
            maxLength={80}
            onInput={(event) => {
              event.currentTarget.value = sanitizePersonName(
                event.currentTarget.value,
                80,
              );
            }}
            placeholder="Name"
            className={inputClassName}
          />
        </label>

        <label className="block text-sm text-text-secondary">
          * Title / Role
          <input
            type="text"
            maxLength={80}
            onInput={(event) => {
              event.currentTarget.value = sanitizeBusinessText(
                event.currentTarget.value,
                80,
              );
            }}
            placeholder="e.g. Chief Digital Officer"
            className={inputClassName}
          />
        </label>

        <label className="block text-sm text-text-secondary">
          * Email
          <input
            type="email"
            maxLength={254}
            onInput={(event) => {
              event.currentTarget.value = sanitizeEmailInput(
                event.currentTarget.value,
              );
            }}
            onBlur={(event) => {
              const value = event.currentTarget.value;
              if (value && !isValidEmailFormat(value)) {
                window.alert("Please enter a valid email address.");
              }
            }}
            placeholder="name@company.com"
            className={inputClassName}
          />
        </label>

        <label className="block text-sm text-text-secondary">
          * Telephone
          <div className="mt-2 grid grid-cols-[170px_1fr] gap-2">
            <CustomSelect
              defaultValue=""
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-base text-text-primary outline-none focus:border-background-blue"
            >
              <option value="">Country code</option>
              {countryCodeOptions.map((country) => (
                <option
                  key={`${country.label}-${country.value}`}
                  value={country.value}
                >
                  {country.label}
                </option>
              ))}
            </CustomSelect>

            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={15}
              onInput={(event) => {
                event.currentTarget.value = event.currentTarget.value
                  .replace(/\D/g, "")
                  .slice(0, 15);
              }}
              placeholder="Phone number"
              className="h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary placeholder:text-text-secondary outline-none focus:border-background-blue"
            />
          </div>
        </label>
      </div>
    </form>
  );
}

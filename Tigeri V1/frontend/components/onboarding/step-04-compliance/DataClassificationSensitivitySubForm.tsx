import CustomSelect from "../../ui/custom-select";

const dataRows = [
  {
    id: "pii",
    type: "Personally Identifiable Information (PII)",
    present: "Yes",
    tier: "Restricted",
    encryption: "Yes - at rest and in transit",
  },
  {
    id: "financial",
    type: "Financial / Payment Data",
    present: "Yes",
    tier: "Restricted",
    encryption: "Yes - at rest and in transit",
  },
  {
    id: "phi",
    type: "Protected Health Information (PHI)",
    present: "No",
    tier: "Restricted",
    encryption: "Yes - at rest and in transit",
  },
  {
    id: "ip",
    type: "Intellectual Property / Trade Secrets",
    present: "Yes",
    tier: "Restricted",
    encryption: "Yes - at rest and in transit",
  },
  {
    id: "employee",
    type: "Employee / HR Data",
    present: "Yes",
    tier: "Confidential",
    encryption: "Yes - at rest and in transit",
  },
];

export default function DataClassificationSensitivitySubForm() {
  const selectClassName =
    "h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-base text-text-primary outline-none focus:border-background-blue";

  return (
    <form className="py-6 md:py-8">
      <div className="overflow-x-auto rounded-xs border border-border-5">
        <table className="w-full min-w-230 border-collapse">
          <thead>
            <tr className="bg-background-5 text-left text-xs uppercase tracking-[0.2em] text-text-muted">
              <th className="border border-border-5 px-4 py-3">Data Type</th>
              <th className="border border-border-5 px-4 py-3">
                Present in Environment?
              </th>
              <th className="border border-border-5 px-4 py-3">
                Classification Tier
              </th>
              <th className="border border-border-5 px-4 py-3">
                Encryption Required?
              </th>
            </tr>
          </thead>
          <tbody>
            {dataRows.map((row) => (
              <tr key={row.id}>
                <td className="border border-border-5 px-4 py-3 text-base font-medium text-text-primary">
                  {row.type}
                </td>
                <td className="border border-border-5 px-4 py-3">
                  <CustomSelect
                    defaultValue={row.present}
                    className={selectClassName}
                  >
                    <option>Yes</option>
                    <option>No</option>
                  </CustomSelect>
                </td>
                <td className="border border-border-5 px-4 py-3">
                  <CustomSelect
                    defaultValue={row.tier}
                    className={selectClassName}
                  >
                    <option>Public</option>
                    <option>Internal</option>
                    <option>Confidential</option>
                    <option>Restricted</option>
                  </CustomSelect>
                </td>
                <td className="border border-border-5 px-4 py-3">
                  <CustomSelect
                    defaultValue={row.encryption}
                    className={selectClassName}
                  >
                    <option>Yes - at rest and in transit</option>
                    <option>Yes - at rest only</option>
                    <option>Not required</option>
                  </CustomSelect>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </form>
  );
}

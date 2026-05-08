import CustomSelect from "../../ui/custom-select";
import { sanitizeBusinessText } from "@/lib/input-validation";

const sourceRows = [
  {
    name: "ERP System",
    systems: [
      "SAP S/4HANA",
      "SAP ECC",
      "Oracle Fusion",
      "Oracle EBS",
      "Microsoft Dynamics 365",
      "NetSuite",
    ],
    records: "e.g. 2M records",
  },
  {
    name: "CRM",
    systems: [
      "Salesforce",
      "HubSpot",
      "Microsoft Dynamics CRM",
      "Zendesk",
      "Intercom",
    ],
    records: "e.g. 500K records",
  },
  {
    name: "HRIS / HR System",
    systems: ["Workday", "BambooHR", "SuccessFactors", "Rippling"],
    records: "e.g. 10K employees",
  },
  {
    name: "Document Store",
    systems: ["SharePoint", "Confluence", "Google Drive", "Notion"],
    records: "e.g. 50K documents",
  },
  {
    name: "Code Repository",
    systems: ["GitHub", "GitLab", "Azure DevOps", "Bitbucket"],
    records: "e.g. 300 repos",
  },
  {
    name: "Project / Ticketing",
    systems: ["Jira", "ServiceNow", "Linear", "Asana"],
    records: "e.g. 20K tickets/yr",
  },
];

export default function L1EnterpriseContextIngestionForm() {
  const selectClassName =
    "h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-base text-text-primary outline-none focus:border-background-blue";
  const inputClassName =
    "h-11 w-full rounded-xs border border-border-5 bg-background-5 px-3 text-base text-text-primary placeholder:text-text-secondary outline-none focus:border-background-blue";

  return (
    <form className="space-y-8 py-6 md:py-8">
      <section>
        <p className="text-base font-medium text-text-primary">
          Data Source Inventory
        </p>
      </section>

      <div className="overflow-x-auto rounded-xs border border-border-5">
        <table className="w-full min-w-full border-collapse">
          <thead>
            <tr className="bg-background-5 text-left text-xs uppercase tracking-[0.2em] text-text-muted">
              <th className="border border-border-5 px-4 py-3">Data Source</th>
              <th className="border border-border-5 px-4 py-3">
                System / Tool
              </th>
              <th className="border border-border-5 px-4 py-3">
                Approximate Records
              </th>
              <th className="border border-border-5 px-4 py-3">Include?</th>
            </tr>
          </thead>
          <tbody>
            {sourceRows.map((row) => (
              <tr key={row.name} className="text-base text-text-primary">
                <td className="border border-border-5 px-4 py-3">{row.name}</td>
                <td className="border border-border-5 px-4 py-3">
                  <CustomSelect
                    data-optional="true"
                    className={selectClassName}
                  >
                    <option>Select system / tool</option>
                    {row.systems.map((system) => (
                      <option key={system}>{system}</option>
                    ))}
                    <option>Other</option>
                    <option>None</option>
                  </CustomSelect>
                </td>
                <td className="border border-border-5 px-4 py-3">
                  <input
                    data-optional="true"
                    type="text"
                    maxLength={50}
                    onInput={(event) => {
                      event.currentTarget.value = sanitizeBusinessText(
                        event.currentTarget.value,
                        50,
                      );
                    }}
                    placeholder={row.records}
                    className={inputClassName}
                  />
                </td>
                <td className="border border-border-5 px-4 py-3">
                  <CustomSelect
                    data-optional="true"
                    className={selectClassName}
                  >
                    <option>Yes</option>
                    <option>No</option>
                  </CustomSelect>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-5 border-t border-border-10 pt-6 md:grid-cols-2">
        <label className="block text-sm text-text-secondary">
          Ingestion Sync Frequency
          <CustomSelect
            data-optional="true"
            className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue"
          >
            <option>Real-time (event-driven)</option>
            <option>Every 15 minutes</option>
            <option>Hourly batch</option>
            <option>Daily batch</option>
          </CustomSelect>
        </label>

        <label className="block text-sm text-text-secondary">
          Estimated Total Data Volume
          <CustomSelect
            data-optional="true"
            className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary outline-none focus:border-background-blue"
          >
            <option>Under 1TB</option>
            <option>1TB - 10TB</option>
            <option>10TB - 50TB</option>
            <option>50TB+</option>
          </CustomSelect>
        </label>
      </div>
    </form>
  );
}

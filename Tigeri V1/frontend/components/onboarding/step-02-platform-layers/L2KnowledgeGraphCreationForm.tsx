import { sanitizeBusinessText } from "@/lib/input-validation";

const scopeOptions = [
  { label: "Business process relationships" },
  { label: "Data schema mapping" },
  { label: "Org chart & reporting lines" },
  { label: "System dependency mapping" },
  { label: "Regulatory context overlay" },
  { label: "Supplier / vendor graph" },
];

export default function L2KnowledgeGraphCreationForm() {
  return (
    <form className="space-y-8 py-6 md:py-8">
      <label className="block text-sm text-text-secondary">
        Primary Business Entities to Model
        <span className="mt-1 block text-xs text-text-muted">
          List the core business objects your teams work with day to day. These
          become the main nodes in your knowledge graph and help us design
          relationships, reasoning paths, and automation workflows around your
          real operations.
        </span>
        <input
          data-optional="true"
          type="text"
          maxLength={200}
          onInput={(event) => {
            event.currentTarget.value = sanitizeBusinessText(
              event.currentTarget.value,
              200,
            );
          }}
          placeholder="e.g. Customer, Invoice, Product, Supplier, Employee, Cost Centre, Asset — list the entities that matter most to your operations"
          className="mt-2 h-11 w-full rounded-xs border border-border-5 bg-background-5 px-4 text-base text-text-primary placeholder:text-text-secondary outline-none focus:border-background-blue"
        />
      </label>

      <section className="border-t border-border-10 pt-6">
        <p className="text-base font-medium text-text-primary">
          Knowledge Graph Scope
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          {scopeOptions.map((item) => (
            <label
              key={item.label}
              className={
                "inline-flex cursor-pointer items-center gap-3 rounded-xs border border-border-5 bg-background-5 px-4 py-2.5 text-base text-text-primary"
              }
            >
              <input
                type="checkbox"
                className="h-4 w-4 accent-background-blue"
              />
              <span>{item.label}</span>
            </label>
          ))}
        </div>
      </section>
    </form>
  );
}

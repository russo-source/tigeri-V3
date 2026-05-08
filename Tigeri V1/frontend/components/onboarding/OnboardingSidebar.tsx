
type OnboardingSidebarStep = {
  id: number;
  label: string;
};

type OnboardingSidebarProps = {
  steps: OnboardingSidebarStep[];
  activeStep: number;
};

export default function OnboardingSidebar({
}: OnboardingSidebarProps) {
  return (
    <aside className="relative min-h-full overflow-hidden">
      <div className="mt-44 flex h-full flex-col p-6 md:p-8">

        <div className="max-w-md space-y-6 text-white">
          <h2 className="text-4xl">
            Continue with
            <br />
            your profile
          </h2>
          <p className="text-xl max-w-xs font-light">
            Build, deploy, and scale AI workflows without the chaos.
          </p>
          <p className="text-sm mt-20">
            From setup to scale, Tigeri gives your team clarity and control over
            AI workflows.
          </p>
        </div>
      </div>
    </aside>
  );
}

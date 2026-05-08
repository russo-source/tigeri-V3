"""Workflow templates baked in for slice 2. Real templates land per-tenant later."""

from dataclasses import dataclass


@dataclass
class WorkflowTemplate:
    template_id: str
    description: str
    steps: list[str]
    documents: list[str]
    communications: list[tuple[str, str, str]]  # (channel, role, message_template)


TEMPLATES: dict[str, WorkflowTemplate] = {
    "employee_onboarding_v1": WorkflowTemplate(
        template_id="employee_onboarding_v1",
        description="Onboard a new employee.",
        steps=["intake", "identity_provisioning", "training_assignment", "completed"],
        documents=["offer_letter.pdf", "policy_pack.pdf"],
        communications=[
            ("EMAIL", "subject", "Welcome to the team"),
            ("EMAIL", "manager", "Your new hire has started"),
        ],
    ),
    "employee_offboarding_v1": WorkflowTemplate(
        template_id="employee_offboarding_v1",
        description="Offboard a departing employee.",
        steps=["initiate", "access_revocation", "exit_interview", "completed"],
        documents=["exit_letter.pdf"],
        communications=[("EMAIL", "subject", "Offboarding next steps")],
    ),
    "client_kyc_v1": WorkflowTemplate(
        template_id="client_kyc_v1",
        description="Run KYC checks for a client.",
        steps=["intake", "verification", "approval", "completed"],
        documents=["kyc_report.pdf"],
        communications=[("EMAIL", "subject", "KYC has been completed")],
    ),
}

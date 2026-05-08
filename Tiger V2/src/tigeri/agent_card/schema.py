from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Phase(str, Enum):
    PHASE_1 = "Phase 1 — Core MVP"
    PHASE_2 = "Phase 2 — Next Build"
    PHASE_3 = "Phase 3 — Enterprise"


class Status(str, Enum):
    IN_DEVELOPMENT = "In Development"
    PLANNED = "Planned"
    ACTIVE = "Active"


class TrustTier(str, Enum):
    OBSERVER = "OBSERVER"
    RECOMMENDER = "RECOMMENDER"
    ACTOR_GATED = "ACTOR_GATED"
    ACTOR_ELEVATED = "ACTOR_ELEVATED"


class Capability(BaseModel):
    id: str
    description: str
    input_ref: str
    output_ref: str


class RequiredIntegration(BaseModel):
    category: str
    access_pattern: Literal["API", "MCP"]


class SLA(BaseModel):
    p50: int
    p95: int
    p99: int


class AgentCard(BaseModel):
    agent_id: str
    name: str
    version: str
    priority: int = Field(ge=1, le=20)
    phase: Phase
    status: Status
    function: str
    capabilities: list[Capability]
    input_schema_ref: str
    output_schema_ref: str
    default_trust_tier: TrustTier
    required_integrations: list[RequiredIntegration]
    delivery_surfaces: list[Literal["web", "mobile"]]
    sla_ms: SLA
    roi_baseline: str

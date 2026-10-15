"""Data types for the Campus Customs agent team."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

AgentName = Literal["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
AGENT_NAMES: tuple[AgentName, ...] = get_args(AgentName)

EventKind = Literal[
    "run_start",       # an agent picked up work (the task it was given)
    "model_response",  # one turn of an agent's loop: what it said and which tools it asked for
    "tool_result",     # what an MCP tool returned
    "delegation",      # one agent handed work to another
    "retry",           # a tool or output was rejected and the agent was asked to fix it
    "final",           # the agent's finished report / decision
    "error",           # the run stopped on an error or a budget limit
    "run_end",         # the ticket run finished (totals)
]


class SpecialistReport(BaseModel):
    """What a specialist hands back to whoever delegated work to them."""

    summary: str = Field(
        description="2-4 plain sentences: what you checked, what you found, and what you did. Use exact numbers from tools."
    )
    facts: list[str] = Field(
        default_factory=list,
        description="Key facts you confirmed, each ending with the tool it came from, "
        "e.g. '8 size M hoodies on hand (check_stock_and_price)'.",
    )
    actions: list[str] = Field(
        default_factory=list,
        description="Anything you created, with its id, e.g. 'Approval request 2: rent $2,400.00, pending'. "
        "Empty if you only looked things up.",
    )
    approval_request_ids: list[int] = Field(
        default_factory=list, description="Ids of payment or purchase requests you created that now need a human."
    )
    draft_ids: list[int] = Field(default_factory=list, description="Ids of message drafts you saved.")
    recommendation: str = Field(description="One or two sentences on what should happen next and who should do it.")


class BossDecision(BaseModel):
    """The Boss's final call on a ticket. The backend records it on the ticket with close_ticket."""

    outcome: str = Field(
        description="3-6 sentences a manager can read on the board: the decision, why, and what happens next "
        "(which approvals are waiting on a human, expected dates). Facts only from tools and reports."
    )
    agents_consulted: list[AgentName] = Field(default_factory=list, description="Teammates you delegated to.")
    approval_request_ids: list[int] = Field(
        default_factory=list, description="Payment or purchase requests waiting on a human for this ticket."
    )
    draft_ids: list[int] = Field(default_factory=list, description="Message drafts saved for this ticket.")
    follow_ups: list[str] = Field(
        default_factory=list, description="Anything still open after this ticket, e.g. a restock that waits on cash."
    )


class AuditEvent(BaseModel):
    """One line of output/audit_trail.json: a single step of one agent's loop."""

    timestamp: str
    run_id: str
    ticket_id: int
    agent: str  # one of AGENT_NAMES, or "Desk" for the orchestrator around the agents
    chain: list[str] = Field(description="Who handed work to whom to get here, e.g. ['Boss', 'Accounting'].")
    step: int | None = None
    event: EventKind
    model: str | None = None
    text: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: Any = None
    ok: bool | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class TicketRunResult(BaseModel):
    run_id: str
    ticket_id: int
    status: str | None = Field(None, description="Ticket status after the run: resolved or awaiting_approval.")
    decision: BossDecision | None = None
    error: str | None = None
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    delegations: int = 0
    duration_ms: int = 0


@dataclass
class RunState:
    """Shared by every agent working the same ticket run."""

    run_id: str
    ticket_id: int
    on_event: Callable[[AuditEvent], None] | None = None
    delegations: int = 0
    agents_used: list[AgentName] = field(default_factory=list)


@dataclass
class TicketDeps:
    """One agent's view of the run. Delegating copies it with the next agent added to the chain."""

    agent: AgentName
    chain: tuple[AgentName, ...]
    state: RunState

    @property
    def ticket_id(self) -> int:
        return self.state.ticket_id

    @property
    def caller(self) -> AgentName | None:
        return self.chain[-2] if len(self.chain) > 1 else None

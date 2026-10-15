"""Campus Customs agent team: Boss, Inventory, Accounting, Facilities and Customer Service on PydanticAI.

Every agent uses gpt-6-luna through Portkey, reads shop data only through the MCP server, and can
delegate to any other agent (full connectivity). Each step of each agent's loop is appended to
output/audit_trail.json.

Run one ticket from the command line (from backend/):  python agents.py 101
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # keep the CLI and server logs clean

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimitExceeded, UsageLimits
from pydantic_core import to_jsonable_python

from audit import append_audit_event, now_iso
from mcp_tools import shop_toolset, toolset_for
from models import AGENT_NAMES, AgentName, AuditEvent, BossDecision, RunState, SpecialistReport, TicketDeps, TicketRunResult

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"

# HW5/.env first, then the course-root .env; real environment variables always win.
load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(PROJECT_ROOT.parents[1] / ".env", override=False)

log = logging.getLogger("campus_customs.agents")

# The only model this project uses, for every agent.
MODEL_NAME = "gpt-6-luna"
PORTKEY_GATEWAY_URL = "https://api.portkey.ai/v1"
REQUEST_TIMEOUT_S = 60
MAX_TRANSIENT_RETRIES = 2

# Token guardrails. Delegated runs share the ticket's usage, so these cap the whole ticket, not each agent.
TICKET_USAGE_LIMITS = UsageLimits(request_limit=40, tool_calls_limit=60, total_tokens_limit=250_000)
# gpt-6-luna only accepts tools plus reasoning on the Responses API; "low" effort keeps reasoning cheap.
MODEL_SETTINGS = OpenAIResponsesModelSettings(max_tokens=4_000, openai_reasoning_effort="low")
MAX_DELEGATION_DEPTH = 3  # e.g. Boss -> Inventory -> Accounting, and no further
MAX_DELEGATIONS_PER_TICKET = 8
RESULT_CHARS = 4_000  # tool results longer than this are cut in the audit trail

PROMPT_FILES: dict[AgentName, str] = {
    "Boss": "boss.md",
    "Inventory": "inventory.md",
    "Accounting": "accounting.md",
    "Facilities": "facilities.md",
    "Customer Service": "customer_service.md",
}
OUTPUT_TOOL = "final_result"  # PydanticAI's structured-output tool; logged as the "final" event


def emit(deps: TicketDeps | None, state: RunState, event: str, agent: str | None = None, **fields: Any) -> None:
    """Record one step: append it to the audit trail and pass it to any live listener (the dashboard)."""
    entry = AuditEvent(
        timestamp=now_iso(),
        run_id=state.run_id,
        ticket_id=state.ticket_id,
        agent=agent or (deps.agent if deps else "Desk"),
        chain=list(deps.chain) if deps else [],
        event=event,
        model=MODEL_NAME if event == "model_response" else None,
        **fields,
    )
    append_audit_event(entry)
    if state.on_event:
        try:
            state.on_event(entry)
        except Exception:
            log.exception("Event listener failed")


def _compact(content: Any) -> tuple[Any, bool]:
    """A tool result as JSON-able data (cut if huge), plus whether it succeeded."""
    data = to_jsonable_python(content)
    ok = not (isinstance(data, dict) and (data.get("ok") is False or data.get("found") is False))
    text = json.dumps(data, ensure_ascii=False)
    return (data if len(text) <= RESULT_CHARS else text[: RESULT_CHARS - 1] + "…"), ok


# ---------------------------------------------------------------------------
# Delegation: any agent can hand work to any other agent
# ---------------------------------------------------------------------------


async def delegate(ctx: RunContext[TicketDeps], to: AgentName, task: str) -> dict[str, Any]:
    """Hand one focused piece of work to a teammate and get their report back.

    Who does what:
    - Boss: routes tickets and makes the final call.
    - Inventory: stock by SKU and size, shortfalls, which vendor can restock and how fast.
    - Accounting: cash, vendor invoices, margins and discount quotes; prepares payments and
      purchase orders for human approval.
    - Facilities: the shop space, leases and rent.
    - Customer Service: drafts the message to the ticket's requester (saved on the board, never sent).

    Args:
        to: The teammate to hand the work to.
        task: One specific job. Include the facts they need (ticket id, SKU, size, qty, ids, amounts and
            dates you already confirmed) and say exactly what you want back.
    """
    d = ctx.deps
    if to == d.agent:
        return {"delegated": False, "reason": "You can't delegate to yourself. Do the work with your own tools."}
    if to == d.caller:
        return {"delegated": False, "reason": f"{to} handed you this work. Answer them in your report instead of "
                                              "delegating back."}
    if len(d.chain) >= MAX_DELEGATION_DEPTH:
        return {"delegated": False, "reason": f"Delegation chain is at its limit ({' -> '.join(d.chain)}). "
                                              "Finish with what you have and say what's missing in your report."}
    if d.state.delegations >= MAX_DELEGATIONS_PER_TICKET:
        return {"delegated": False, "reason": f"This ticket has used all {MAX_DELEGATIONS_PER_TICKET} delegations. "
                                              "Finish with what you have."}

    d.state.delegations += 1
    emit(d, d.state, "delegation", args={"to": to}, text=task)
    report = await run_agent(to, task, replace(d, agent=to, chain=(*d.chain, to)), ctx.usage)
    return {"delegated": True, "from": to, "report": report.model_dump()}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_model() -> OpenAIResponsesModel:
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY is not set. Add it to HW5/.env or export it in your shell.")
    client = AsyncOpenAI(
        base_url=PORTKEY_GATEWAY_URL, api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=MAX_TRANSIENT_RETRIES
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def _build_agent(name: AgentName) -> Agent[TicketDeps, Any]:
    agent = Agent(
        get_model(),
        name=name,
        deps_type=TicketDeps,
        output_type=BossDecision if name == "Boss" else SpecialistReport,
        instructions=(PROMPTS_DIR / PROMPT_FILES[name]).read_text(encoding="utf-8"),
        toolsets=[toolset_for(name)],
        tools=[delegate],
        model_settings=MODEL_SETTINGS,
        retries=2,
    )

    @agent.instructions
    def run_context(ctx: RunContext[TicketDeps]) -> str:
        d = ctx.deps
        left = MAX_DELEGATIONS_PER_TICKET - d.state.delegations
        lines = [
            "## This run",
            f"You are {d.agent}, working ticket {d.ticket_id}.",
            f"Work handed to you by: {d.caller or 'the desk (a new ticket)'}.",
            f"Delegation chain so far: {' -> '.join(d.chain)}.",
        ]
        if len(d.chain) >= MAX_DELEGATION_DEPTH or left <= 0:
            lines.append("You can't delegate any further on this ticket. Finish with your own tools.")
        else:
            lines.append(f"Delegations left for this ticket: {left}.")
        return "\n".join(lines)

    return agent


@lru_cache(maxsize=1)
def get_agents() -> dict[AgentName, Agent[TicketDeps, Any]]:
    return {name: _build_agent(name) for name in AGENT_NAMES}


async def run_agent(name: AgentName, task: str, deps: TicketDeps, usage: RunUsage) -> SpecialistReport | BossDecision:
    """Run one agent's loop step by step, logging every model turn and tool result."""
    state = deps.state
    if name not in state.agents_used:
        state.agents_used.append(name)
    emit(deps, state, "run_start", text=task)
    step = 0
    try:
        async with get_agents()[name].iter(task, deps=deps, usage=usage, usage_limits=TICKET_USAGE_LIMITS) as run:
            async for node in run:
                if Agent.is_call_tools_node(node):
                    step += 1
                    response = node.model_response
                    text = "\n".join(p.content for p in response.parts if isinstance(p, TextPart) and p.content.strip())
                    calls = [
                        {"tool": p.tool_name, "args": p.args_as_dict()}
                        for p in response.parts
                        if isinstance(p, ToolCallPart) and p.tool_name != OUTPUT_TOOL
                    ]
                    emit(deps, state, "model_response", step=step, text=text or None, tool_calls=calls or None,
                         input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
                elif Agent.is_model_request_node(node):
                    for part in node.request.parts:
                        if isinstance(part, ToolReturnPart) and part.tool_name not in (OUTPUT_TOOL, "delegate"):
                            result, ok = _compact(part.content)
                            emit(deps, state, "tool_result", step=step, tool=part.tool_name, result=result, ok=ok)
                        elif isinstance(part, RetryPromptPart):
                            reason = part.content if isinstance(part.content, str) else json.dumps(to_jsonable_python(part.content))
                            emit(deps, state, "retry", step=step, tool=part.tool_name, text=reason[:1000], ok=False)
        output = run.result.output
    except Exception as e:
        emit(deps, state, "error", step=step, text=f"{type(e).__name__}: {e}"[:1000], ok=False)
        raise
    emit(deps, state, "final", step=step, result=output.model_dump(), ok=True)
    return output


# ---------------------------------------------------------------------------
# One ticket, start to finish
# ---------------------------------------------------------------------------


def _boss_task(ticket: dict[str, Any]) -> str:
    return (
        f"Ticket {ticket['ticket']['id']} is on the desk. Here it is exactly as stored (from get_ticket):\n\n"
        f"{json.dumps(ticket, indent=2)}\n\n"
        "Work it the way your instructions describe and finish with your final call."
    )


async def run_ticket(ticket_id: int, on_event=None) -> TicketRunResult:
    """Have the team work one open ticket; the Boss's final call is recorded on the ticket via MCP."""
    state = RunState(run_id=str(uuid.uuid4()), ticket_id=ticket_id, on_event=on_event)
    deps = TicketDeps(agent="Boss", chain=("Boss",), state=state)
    usage = RunUsage()
    started = time.time()
    decision, error, status = None, None, None

    toolset = shop_toolset()
    async with toolset:  # one MCP server process for the whole run
        ticket = await toolset.direct_call_tool("get_ticket", {"ticket_id": ticket_id})
        if not ticket.get("found"):
            error = ticket.get("message", f"No ticket with id {ticket_id}.")
        elif ticket["ticket"]["status"] != "open":
            # Guardrail: a ticket the team already closed is never worked twice (no double payment requests).
            status = ticket["ticket"]["status"]
            error = f"Ticket {ticket_id} is {status}; only open tickets can be run. Reset the database for a fresh run."
        else:
            emit(None, state, "run_start", text=f"Ticket {ticket_id}: {ticket['ticket']['subject']}",
                 result=ticket["ticket"])
            try:
                decision = await run_agent("Boss", _boss_task(ticket), deps, usage)
                closed = await toolset.direct_call_tool(
                    "close_ticket", {"ticket_id": ticket_id, "outcome": decision.outcome, "decided_by": "Boss"}
                )
                status = closed.get("status")
            except UsageLimitExceeded as e:
                error = f"Stopped by the token/request budget: {e}"
            except Exception as e:
                log.exception("Ticket %s run failed", ticket_id)
                error = f"{type(e).__name__}: {e}"

    result = TicketRunResult(
        run_id=state.run_id,
        ticket_id=ticket_id,
        status=status,
        decision=decision,
        error=error,
        model_requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        delegations=state.delegations,
        duration_ms=int((time.time() - started) * 1000),
    )
    emit(None, state, "run_end", text=error or f"Ticket {ticket_id} {status}.", ok=error is None,
         result=result.model_dump(exclude={"decision"}),
         input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
    return result


def _print_event(e: AuditEvent) -> None:
    indent = "  " * max(len(e.chain) - 1, 0)
    if e.event == "model_response":
        tools = ", ".join(c["tool"] for c in e.tool_calls or [])
        said = f' says: "{e.text[:140]}"' if e.text else ""
        print(f"{indent}[{e.agent}] step {e.step}{said}{' -> calls ' + tools if tools else ''}")
    elif e.event == "tool_result":
        print(f"{indent}[{e.agent}]   {e.tool} -> {'ok' if e.ok else 'REFUSED/NOT FOUND'}")
    elif e.event == "delegation":
        print(f"{indent}[{e.agent}] delegates to {e.args['to']}: {e.text[:140]}")
    elif e.event in ("final", "error", "retry"):
        print(f"{indent}[{e.agent}] {e.event}: {json.dumps(e.result)[:200] if e.result else e.text}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    if len(sys.argv) != 2:
        sys.exit("usage: python agents.py <ticket_id>")
    outcome = asyncio.run(run_ticket(int(sys.argv[1]), on_event=_print_event))
    print(json.dumps(outcome.model_dump(), indent=2))

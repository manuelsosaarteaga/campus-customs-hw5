import type { AgentEvent, AgentName, BossDecision, SpecialistReport } from "./api";

export const AGENTS: { name: AgentName; role: string }[] = [
  { name: "Boss", role: "Routes the ticket, makes the final call" },
  { name: "Inventory", role: "Stock, shortfalls, vendors, lead times" },
  { name: "Accounting", role: "Cash, invoices, margins, payment requests" },
  { name: "Facilities", role: "The shop space, leases and rent" },
  { name: "Customer Service", role: "Drafts the reply to the requester" },
];

const AGENT_NAMES = new Set<string>(AGENTS.map((a) => a.name));

export interface AgentCard {
  name: AgentName;
  role: string;
  status: "idle" | "working" | "reported";
  steps: number;
  tools: number;
  chain?: string[];
  report?: SpecialistReport;
  decision?: BossDecision;
}

/** A human's approve/reject is recorded against the ticket, but it isn't an agent run. */
const isAgentRun = (event: AgentEvent) => !event.run_id.startsWith("human-");

/** Every step of the most recent agent run on this ticket, in order. */
export function eventsForLatestRun(events: AgentEvent[], ticketId: number | null): AgentEvent[] {
  if (ticketId === null) return [];
  const mine = events.filter((e) => e.ticket_id === ticketId);
  const lastRun = mine.filter(isAgentRun).at(-1)?.run_id;
  return lastRun ? mine.filter((e) => e.run_id === lastRun) : [];
}

/** Everything shown in the activity stream for this ticket: the latest run, plus any human decision after it. */
export function streamFor(events: AgentEvent[], ticketId: number | null): AgentEvent[] {
  if (ticketId === null) return [];
  const run = eventsForLatestRun(events, ticketId);
  const firstSeq = run[0]?.seq ?? 0;
  const humanAfter = events.filter((e) => e.ticket_id === ticketId && !isAgentRun(e) && e.seq > firstSeq);
  return [...run, ...humanAfter].sort((a, b) => a.seq - b.seq);
}

/** Who did what in this run, for the summary cards. */
export function buildAgentCards(runEvents: AgentEvent[]): AgentCard[] {
  const cards = new Map<string, AgentCard>(
    AGENTS.map((a) => [a.name, { ...a, status: "idle", steps: 0, tools: 0 }]),
  );
  let runFinished = false;

  for (const event of runEvents) {
    if (event.event === "run_end") {
      runFinished = true;
      continue;
    }
    const card = cards.get(event.agent); // "Desk" and "Human" are not agents
    if (!card) continue;
    switch (event.event) {
      case "run_start":
        card.status = card.status === "reported" ? "reported" : "working";
        card.chain = event.chain;
        break;
      case "model_response":
        card.steps += 1;
        break;
      case "tool_result":
        card.tools += 1;
        break;
      case "final":
        card.status = "reported";
        if (event.agent === "Boss") card.decision = event.result as BossDecision;
        else card.report = event.result as SpecialistReport;
        break;
    }
  }

  if (runFinished) {
    for (const card of cards.values()) if (card.status === "working") card.status = "idle";
  }
  return [...cards.values()];
}

export const isAgent = (name: string) => AGENT_NAMES.has(name);

/** Totals for the run footer, taken from the run_end step the backend emits. */
export function runTotals(runEvents: AgentEvent[]) {
  const end = runEvents.find((e) => e.event === "run_end");
  if (!end) return null;
  return end.result as {
    status: string | null;
    error: string | null;
    model_requests: number;
    input_tokens: number;
    output_tokens: number;
    delegations: number;
    duration_ms: number;
  };
}

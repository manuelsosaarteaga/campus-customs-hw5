import type React from "react";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import type { AgentEvent, BossDecision, SpecialistReport } from "../api";
import { runTotals } from "../runView";

const agentClass = (agent: string) => `agent-${agent.toLowerCase().replace(/\s+/g, "-")}`;

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

interface Props {
  events: AgentEvent[];
  ticketId: number | null;
  running: boolean;
}

/** The centre of the desk: every step of the team's loop, as it happens. */
export function ActivityStream({ events, ticketId, running }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastTop = useRef(0);

  // Follow the newest step, unless the reader has scrolled up to look at something.
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [events]);

  // Unpin on an actual upward scroll, not on distance from the bottom: steps arrive in
  // bursts, so a handler that measured the gap would see its own catch-up scroll lagging
  // behind a grown stream and conclude the reader had wandered off.
  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const scrolledUp = el.scrollTop < lastTop.current - 2;
    lastTop.current = el.scrollTop;
    if (scrolledUp) pinned.current = false;
    else if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) pinned.current = true;
  };

  const totals = runTotals(events);

  return (
    <section className="panel stream">
      <div className="panel-head">
        <h2>Agent activity</h2>
        {ticketId !== null && <span className="count">Ticket #{ticketId}</span>}
        {running && (
          <span className="pill pill-running">
            <span className="pulse pulse-live" /> Live
          </span>
        )}
      </div>

      <div
        className="stream-body"
        ref={scroller}
        onScroll={onScroll}
      >
        {events.length === 0 ? (
          <Placeholder ticketId={ticketId} />
        ) : (
          events.map((event) => <Row key={event.seq} event={event} />)
        )}

        {running && <Working />}
        {totals && !running && <Totals totals={totals} />}
      </div>
    </section>
  );
}

function Placeholder({ ticketId }: { ticketId: number | null }) {
  return (
    <div className="stream-empty">
      <p className="stream-empty-title">Nothing on the wire</p>
      <p>
        {ticketId === null
          ? "Pick a ticket on the left to see its last run."
          : "Run the team on this ticket and every model turn, tool call and hand-off shows up here."}
      </p>
    </div>
  );
}

function Working() {
  return (
    <div className="stream-working">
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
      <span className="muted">thinking</span>
    </div>
  );
}

function Row({ event }: { event: AgentEvent }) {
  const depth = Math.max(event.chain.length - 1, 0);
  return (
    <article className="row" style={{ "--depth": depth } as CSSProperties}>
      <time className="row-time">{clock(event.timestamp)}</time>
      <span className={`chip ${agentClass(event.agent)}`}>{event.agent}</span>
      <div className="row-body">
        <Body event={event} />
      </div>
    </article>
  );
}

function Body({ event }: { event: AgentEvent }) {
  switch (event.event) {
    case "run_start":
      return event.agent === "Desk" ? (
        <p className="row-headline">{event.text}</p>
      ) : (
        <Collapsed label="picked up the work" body={event.text} />
      );

    case "delegation":
      return (
        <div>
          <p className="row-headline">
            hands off to <strong>{String(event.args?.to ?? "a teammate")}</strong>
          </p>
          <Collapsed label="the task" body={event.text} />
        </div>
      );

    case "model_response":
      return (
        <div>
          {event.text && <p className="row-text">{event.text}</p>}
          {event.tool_calls?.length ? (
            <div className="tool-row">
              {event.tool_calls.map((call, i) => (
                <span className="tool-chip" key={i}>
                  {call.tool}
                </span>
              ))}
            </div>
          ) : null}
          {!event.text && !event.tool_calls?.length && <p className="muted">(no visible output this turn)</p>}
        </div>
      );

    case "tool_result":
      return (
        <div className="tool-result">
          <span className={`tool-chip ${event.ok ? "" : "tool-chip-bad"}`}>{event.tool}</span>
          <span className={event.ok ? "badge badge-ok" : "badge badge-bad"}>{event.ok ? "ok" : "refused"}</span>
          <Collapsed label="what came back" json={event.result} />
        </div>
      );

    case "retry":
      return (
        <p className="row-warn">
          <strong>retry</strong> on {event.tool}: {event.text}
        </p>
      );

    case "final":
      return <Report result={event.result} isBoss={event.agent === "Boss"} />;

    case "error":
      return <p className="row-error">{event.text}</p>;

    case "run_end":
      return null; // shown as the run footer instead

    default:
      return <p className="row-text">{event.text}</p>;
  }
}

function Report({ result, isBoss }: { result: unknown; isBoss: boolean }) {
  if (!result || typeof result !== "object") return null;
  if (isBoss) {
    const decision = result as BossDecision;
    return (
      <div className="report report-boss">
        <p className="report-label">Final call</p>
        <p>{decision.outcome}</p>
        {decision.follow_ups?.length > 0 && (
          <ul className="report-list">
            {decision.follow_ups.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  const report = result as SpecialistReport;
  return (
    <div className="report">
      <p className="report-label">Report</p>
      <p>{report.summary}</p>
      {report.facts?.length > 0 && (
        <ul className="report-list">
          {report.facts.map((fact, i) => (
            <li key={i}>{fact}</li>
          ))}
        </ul>
      )}
      {report.recommendation && <p className="report-rec">{report.recommendation}</p>}
    </div>
  );
}

/** Long text and tool payloads start folded so the stream stays readable. */
function Collapsed({ label, body, json }: { label: string; body?: string | null; json?: unknown }) {
  const [open, setOpen] = useState(false);
  const text = json !== undefined ? JSON.stringify(json, null, 2) : (body ?? "");
  if (!text) return null;
  return (
    <div className="collapsed">
      <button className="link" onClick={() => setOpen(!open)}>
        {open ? "hide" : label}
      </button>
      {open && <pre>{text}</pre>}
    </div>
  );
}

function Totals({ totals }: { totals: NonNullable<ReturnType<typeof runTotals>> }) {
  return (
    <footer className={`run-totals ${totals.error ? "run-totals-bad" : ""}`}>
      {totals.error ? (
        <span>{totals.error}</span>
      ) : (
        <>
          <span>
            Ticket <strong>{totals.status?.replace("_", " ")}</strong>
          </span>
          <span className="divider" />
          <span>{totals.model_requests} model requests</span>
          <span className="divider" />
          <span>{totals.delegations} hand-offs</span>
          <span className="divider" />
          <span>{(totals.input_tokens + totals.output_tokens).toLocaleString()} tokens</span>
          <span className="divider" />
          <span>{(totals.duration_ms / 1000).toFixed(1)}s</span>
        </>
      )}
    </footer>
  );
}

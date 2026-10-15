import { money, type Ticket, type TicketDetail, type TicketStatus } from "../api";

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price override",
};

const STATUS_LABEL: Record<TicketStatus, string> = {
  open: "Open",
  awaiting_approval: "Awaiting approval",
  resolved: "Resolved",
};

interface Props {
  tickets: Ticket[];
  detail: TicketDetail | null;
  selectedId: number | null;
  busyWith: string | null;
  onSelect: (id: number) => void;
  onRun: (id: number) => void;
}

export function TicketRail({ tickets, detail, selectedId, busyWith, onSelect, onRun }: Props) {
  return (
    <aside className="panel rail">
      <div className="panel-head">
        <h2>Desk tickets</h2>
        <span className="count">{tickets.length}</span>
      </div>

      <ul className="ticket-list">
        {tickets.map((ticket) => {
          const selected = ticket.id === selectedId;
          const running = busyWith === `ticket ${ticket.id}`;
          return (
            <li key={ticket.id} className={selected ? "ticket-slot ticket-slot-selected" : "ticket-slot"}>
              {/* The card selects; the run button lives beside it, never inside it. */}
              <button
                className="ticket"
                onClick={() => onSelect(ticket.id)}
                aria-current={selected ? "true" : undefined}
              >
                <div className="ticket-top">
                  <span className="ticket-id">#{ticket.id}</span>
                  <StatusPill status={ticket.status} running={running} />
                </div>
                <h3>{ticket.subject}</h3>
                <p className="ticket-type">{TYPE_LABEL[ticket.type] ?? ticket.type}</p>
                <p className="ticket-requester">{ticket.requester}</p>
              </button>

              {selected && detail?.ticket.id === ticket.id && <Detail detail={detail} />}

              {selected && (
                <div className="ticket-actions">
                  <button
                    className="btn btn-primary"
                    disabled={busyWith !== null || ticket.status !== "open"}
                    onClick={() => onRun(ticket.id)}
                  >
                    {running ? "Team is working…" : "Run the team"}
                  </button>
                  {ticket.status !== "open" && !running && (
                    <p className="hint">Already worked. Reset the board to run it again.</p>
                  )}
                  {busyWith !== null && !running && <p className="hint">The board is busy with {busyWith}.</p>}
                </div>
              )}
            </li>
          );
        })}
        {tickets.length === 0 && <li className="empty">No tickets on the board.</li>}
      </ul>
    </aside>
  );
}

/** The ask in the requester's own words, plus whatever the team has attached to it. */
function Detail({ detail }: { detail: TicketDetail }) {
  const { ticket, approval_requests, message_drafts, outcome } = detail;
  return (
    <div className="ticket-detail">
      <p className="ticket-notes">{ticket.notes}</p>

      <dl className="ticket-facts">
        {ticket.sku && (
          <>
            <dt>Item</dt>
            <dd>
              {ticket.qty ?? 1} &times; {ticket.sku} <span className="muted">({ticket.size})</span>
            </dd>
          </>
        )}
        {ticket.invoice_id !== null && (
          <>
            <dt>Invoice</dt>
            <dd>#{ticket.invoice_id}</dd>
          </>
        )}
        {ticket.lease_id !== null && (
          <>
            <dt>Lease</dt>
            <dd>#{ticket.lease_id}</dd>
          </>
        )}
      </dl>

      {approval_requests.length > 0 && (
        <ul className="ticket-attached">
          {approval_requests.map((r) => (
            <li key={r.id}>
              <span className={`badge ${r.status === "pending" ? "badge-wait" : r.status === "paid" ? "badge-ok" : "badge-bad"}`}>
                {r.status}
              </span>
              {money(r.amount)} to {r.payee}
            </li>
          ))}
        </ul>
      )}

      {message_drafts.length > 0 && (
        <p className="ticket-draft">
          Draft saved: &ldquo;{message_drafts[0].subject}&rdquo;
          {message_drafts.length > 1 ? ` +${message_drafts.length - 1} more` : ""}
        </p>
      )}

      {outcome && <p className="ticket-outcome">{outcome.outcome}</p>}
    </div>
  );
}

function StatusPill({ status, running }: { status: TicketStatus; running: boolean }) {
  if (running) {
    return (
      <span className="pill pill-running">
        <span className="pulse pulse-live" /> Working
      </span>
    );
  }
  return <span className={`pill pill-${status}`}>{STATUS_LABEL[status]}</span>;
}

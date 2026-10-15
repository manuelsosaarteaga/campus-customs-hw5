import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type AgentEvent,
  ApiError,
  approvePayment,
  getTicketDetail,
  rejectPayment,
  resetBoard,
  runTicket,
  type TicketDetail,
} from "./api";
import { ActivityStream } from "./components/ActivityStream";
import { AgentCards } from "./components/AgentCards";
import { ApprovalsPanel } from "./components/ApprovalsPanel";
import { TicketRail } from "./components/TicketRail";
import { TopBar } from "./components/TopBar";
import { buildAgentCards, eventsForLatestRun, streamFor } from "./runView";
import { useBoard, useEventStream } from "./useBoard";

const APPROVER_KEY = "campus-customs.approver";
const PREPARES_PAYMENT = /^request_/;

export default function App() {
  const { tickets, cash, approvals, offline, refresh } = useBoard();
  const [pickedId, setPickedId] = useState<number | null>(null);
  const [approver, setApprover] = useState(() => localStorage.getItem(APPROVER_KEY) ?? "");
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  // The board only changes at two moments: when an agent prepares a payment, and when a
  // run ends. Refreshing on those two steps keeps the balance and the approval queue honest
  // without polling the backend on a timer.
  const onAgentStep = useCallback(
    (event: AgentEvent) => {
      if (event.event === "run_end" || (event.tool && PREPARES_PAYMENT.test(event.tool))) void refresh();
    },
    [refresh],
  );

  const { events, live, busyWith, clear } = useEventStream(onAgentStep);

  // Until someone picks a ticket, the desk shows the first one still open.
  const selectedId = pickedId ?? (tickets.find((t) => t.status === "open") ?? tickets[0])?.id ?? null;

  useEffect(() => {
    localStorage.setItem(APPROVER_KEY, approver);
  }, [approver]);

  // The selected ticket's own words, re-read whenever the board moves.
  useEffect(() => {
    if (selectedId === null) return;
    let dropped = false;
    getTicketDetail(selectedId)
      .then((d) => {
        if (!dropped) setDetail(d);
      })
      .catch(() => undefined);
    return () => {
      dropped = true;
    };
  }, [selectedId, tickets]);

  const runEvents = useMemo(() => eventsForLatestRun(events, selectedId), [events, selectedId]);
  const streamEvents = useMemo(() => streamFor(events, selectedId), [events, selectedId]);
  const cards = useMemo(() => buildAgentCards(runEvents), [runEvents]);
  const running = busyWith !== null;

  const handleRun = async (ticketId: number) => {
    setRunError(null);
    try {
      await runTicket(ticketId);
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : String(e));
    } finally {
      void refresh();
    }
  };

  const handleApprove = async (requestId: number) => {
    setApprovalError(null);
    try {
      await approvePayment(requestId, approver.trim());
    } catch (e) {
      setApprovalError(e instanceof ApiError ? e.message : String(e));
    } finally {
      void refresh();
    }
  };

  const handleReject = async (requestId: number) => {
    setApprovalError(null);
    try {
      await rejectPayment(requestId, approver.trim(), "Declined at the desk.");
    } catch (e) {
      setApprovalError(e instanceof ApiError ? e.message : String(e));
    } finally {
      void refresh();
    }
  };

  const handleReset = async () => {
    setRunError(null);
    setApprovalError(null);
    try {
      await resetBoard();
      clear();
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : String(e));
    } finally {
      void refresh();
    }
  };

  return (
    <div className="app">
      <TopBar cash={cash} live={live} busy={running} onReset={() => void handleReset()} />

      {offline && <p className="banner banner-bad">{offline}</p>}
      {runError && <p className="banner banner-bad">{runError}</p>}

      <main className="grid">
        <TicketRail
          tickets={tickets}
          detail={detail}
          selectedId={selectedId}
          busyWith={busyWith}
          onSelect={setPickedId}
          onRun={(id) => void handleRun(id)}
        />

        <ActivityStream
          events={streamEvents}
          ticketId={selectedId}
          running={busyWith === `ticket ${selectedId}`}
        />

        <div className="side">
          <AgentCards cards={cards} />
          <ApprovalsPanel
            approvals={approvals}
            approver={approver}
            busy={running}
            onApproverChange={setApprover}
            onApprove={handleApprove}
            onReject={handleReject}
            error={approvalError}
          />
        </div>
      </main>
    </div>
  );
}

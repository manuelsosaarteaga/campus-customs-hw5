import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AgentEvent,
  API_BASE,
  type ApprovalRequest,
  type Cash,
  type EventKind,
  getApprovals,
  getCash,
  getEvents,
  getTickets,
  type Ticket,
} from "./api";

/** The board: tickets, cash and approvals. Refreshed on demand, never on a timer. */
export function useBoard() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [offline, setOffline] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [t, c, a] = await Promise.all([getTickets(), getCash(), getApprovals("all")]);
      setTickets(t);
      setCash(c);
      setApprovals(a);
      setOffline(null);
    } catch (e) {
      setOffline(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { tickets, cash, approvals, offline, refresh };
}

const KINDS: EventKind[] = [
  "run_start",
  "model_response",
  "tool_result",
  "delegation",
  "retry",
  "final",
  "error",
  "run_end",
];

/** The live feed of agent steps: seeded from /events, then kept current over SSE. */
export function useEventStream(onEvent?: (event: AgentEvent) => void) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [live, setLive] = useState(false);
  // What the board is working on, straight from the backend's own steps, so a page
  // reload in the middle of a run still shows that run as running.
  const [busyWith, setBusyWith] = useState<string | null>(null);
  const seen = useRef(new Set<number>());

  // Kept in a ref so a new callback identity never tears down the SSE connection.
  const listener = useRef(onEvent);
  useEffect(() => {
    listener.current = onEvent;
  }, [onEvent]);

  const add = useCallback((event: AgentEvent) => {
    if (seen.current.has(event.seq)) return; // the seed and the stream overlap by design
    seen.current.add(event.seq);
    setEvents((previous) => [...previous, event]);
    if (event.agent === "Desk") setBusyWith(event.event === "run_end" ? null : `ticket ${event.ticket_id}`);
    listener.current?.(event);
  }, []);

  const clear = useCallback(() => {
    seen.current.clear();
    setEvents([]);
  }, []);

  useEffect(() => {
    let dropped = false;
    getEvents(0, 400)
      .then(({ events: seeded, busy_with }) => {
        if (dropped) return;
        seeded.forEach(add);
        setBusyWith(busy_with);
      })
      .catch(() => undefined); // the stream will fill in once the backend is up

    const source = new EventSource(`${API_BASE}/events/stream`);
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false); // EventSource reconnects on its own
    for (const kind of KINDS) {
      source.addEventListener(kind, (message) => add(JSON.parse((message as MessageEvent<string>).data)));
    }
    return () => {
      dropped = true;
      source.close();
    };
  }, [add]);

  return { events, live, busyWith, clear };
}

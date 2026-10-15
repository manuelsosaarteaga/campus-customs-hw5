# Design notes: the Campus Customs operations desk

`frontend/` is a React + Vite + TypeScript app that talks to the FastAPI backend on port 8000.
This file explains why it looks and behaves the way it does.

## The one job the screen has

A manager sits down and needs to answer four questions, in this order:

1. What is on the desk today?
2. What did the team actually do about it?
3. Who did what, and what did they conclude?
4. What do *I* have to decide, and what does it cost?

The layout is that list, left to right. Nothing else competes for the space.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Campus Customs · operations desk      Live · shop date        CHECKING $3,400│
├──────────────┬────────────────────────────────────┬──────────────────────────┤
│ DESK TICKETS │ AGENT ACTIVITY                     │ THE TEAM                 │
│              │                                    │  Boss        reported    │
│ #101 open    │ 20:26:31 Boss      → delegate      │  Inventory   working     │
│ #102 open ◀  │ 20:26:32   Facilities  get_lease   │  Accounting  idle        │
│   the ask    │ 20:26:32   Facilities  → hands off │  Facilities  idle        │
│   the facts  │ 20:26:32     Accounting  ok        │  Customer S. idle        │
│   [Run]      │ 20:26:33     Accounting  REPORT    ├──────────────────────────┤
│ #103 open    │ ───────────────────────────────    │ NEEDS A HUMAN            │
│              │ resolved · 9 requests · 22k tokens │  $2,400.00               │
│              │                                    │  [Approve]  [Decline]    │
└──────────────┴────────────────────────────────────┴──────────────────────────┘
   318px                   flexible                          372px
```

The two side columns are fixed and the middle one takes whatever is left, because the stream is
the only part whose content is unbounded. Each column scrolls inside itself on a wide screen, so
the header, the money and the approve button never scroll away while you are reading a long run.

## Why it is dark

This is a monitoring screen, not a document. The data is small, bright and constantly changing —
chips, amounts, status words — and a dark ground lets those carry all the contrast. On a light
ground every tool chip would need a heavy border to separate it from the page; here a 12% white
hairline is enough, so the stream stays quiet at a hundred rows.

Three greys do the structural work: the page (`#090d13`), the panels (`#121a26` fading to
`#0d131c`), and the cards inside them (`#17202e`). Each step up is small on purpose, so depth reads
as depth rather than as decoration. One soft Yale-blue glow sits behind the top-left corner to keep
the page from looking like a terminal.

## Colour means something or it isn't used

- **Yale blue** is the brand note. The real Yale blue (`#00356B`) is too dark to be legible as an
  accent on a dark ground, so it lives in the logo gradient, and a lifted version (`#6AA5FF`) does
  the interactive work: the primary button, links, the ticket type, tool chips.
- **Each agent gets one hue** and keeps it everywhere — in the stream chip, in the team card, and
  in the delegation chain. Boss amber, Inventory green, Accounting blue, Facilities violet,
  Customer Service rose. After a few seconds of watching a run you stop reading the names and start
  reading the colours, which is the point: you can see at a glance that a chain went
  Boss → Facilities → Accounting.
- **Status has three colours and no more.** Amber is "a human is the blocker" (awaiting approval,
  pending requests, money promised but not spent). Green is "done and safe" (resolved, paid, ok,
  live). Red is "refused or failed". A refused tool call and a declined payment use the same red,
  because they are the same event from the shop's point of view: a rule said no.
- Everything else is grey. Idle agent cards drop to 55% opacity rather than changing colour, so the
  team panel reads as "two of five have spoken" without a legend.

## Typography: prose is prose, data is data

Two families, used as a rule rather than a flourish. The system sans carries anything a person
wrote or an agent said. The monospace carries anything that came out of the database — amounts,
ticket ids, SKUs, timestamps, tool names, token counts. If it is monospaced on this screen, you can
go look it up in SQLite and find the same value.

Money is always monospaced with `tabular-nums`, so the balance does not jitter as it changes from
`$3,400.00` to `$1,000.00`, and the column of pending amounts lines up on the decimal. Section
headings are 11px uppercase with wide tracking — small enough to stay out of the way, distinct
enough that you never confuse a panel title with content.

## The stream is the centre of gravity

Each row is `time · agent · what happened`, indented by how deep the delegation chain is. The
indent is the only indication of hierarchy, and it is enough: a hand-off is literally a step to the
right.

Three decisions keep it readable during a run that produces fifty steps in forty seconds:

- **Tool payloads are folded.** A tool result shows the tool name, an `ok`/`refused` badge and a
  "what came back" link. The full JSON is one click away. The interesting thing about
  `get_cash_balance` is almost always that it succeeded, not its 80 characters of JSON.
- **Reports are not folded.** When an agent finishes, its summary, its facts and its recommendation
  are shown in full in a bordered block, and the Boss's final call gets an amber left edge. These
  are the sentences a manager actually has to read.
- **The stream follows the newest step, but yields to the reader.** It only stops following when you
  scroll *up*; it resumes when you come back to the bottom. An earlier version measured distance
  from the bottom instead, which broke during bursts — the catch-up scroll lagged behind a stream
  that had already grown, and the view read its own lag as the reader wandering off.

A run ends with a single totals strip: status, model requests, hand-offs, tokens, seconds. Token
cost is part of the product here, not a debugging detail, so it sits on the screen rather than in a
console.

## The approval panel is deliberately the heaviest thing on the page

It is the only place where a click spends real money, so it is the only place with friction:

- The amount is set in 25px monospace — bigger than anything else on the screen including the
  balance — because the amount is the decision.
- **Approve is disabled until you type your name.** The backend refuses an approver named after an
  agent, and the panel says so in the hint: *an agent can't approve its own payment*. The rule is
  enforced in the database transaction; the UI just makes it visible instead of letting you discover
  it as an error.
- **Decline is given equal prominence** — same size, same row, just a quieter fill. A panel where
  the safe option is a tiny grey link is a panel that trains people to approve.
- The reason, who prepared it and what it buys are all shown before the buttons, so you never
  approve a number without its sentence.
- Refusals come back inline in the panel, in the shop's own words ("Not enough cash: checking has
  $1,000.00, this payment is $2,400.00"), not as a toast that disappears.

The balance in the header is the counterweight: it shows the checking balance, and when something
is pending it adds an amber line with what is promised and what is actually free. Those are three
different numbers and the difference is the whole cash story of this shop.

## Motion is used for one thing: showing that something is alive

A pulsing green dot for the live connection and for a working agent, three bouncing dots while the
team is thinking, and a 260ms fade-and-rise as each new step arrives. Nothing else moves. Buttons
get a 1px press and a colour change, no scale transforms. Everything is wrapped in
`prefers-reduced-motion` so a reader who has asked the OS to stop animation gets a static page.

## Honesty rules in the UI

- The browser computes nothing. No totals, no due-date maths, no margins. Every figure on the
  screen arrived from a backend route that got it from an MCP tool that read SQLite. The frontend's
  only arithmetic is adding input and output tokens together for the run footer.
- The human's approve and reject appear in the stream as their own rows, in their own colour, the
  same way an agent's steps do. Watching the board, you can see exactly where the person stepped in.
- Statuses are never guessed from the UI's own actions. After a run or an approval the board re-reads
  `/tickets`, `/cash` and `/approvals`; a ticket shows "Resolved" because the database says so.
- Nothing polls on a timer. The board refreshes at the two moments it can actually change — when an
  agent prepares a payment, and when a run ends — which it learns from the event stream itself.

## Responsive behaviour

Three columns down to 1150px. Below that the tickets and the stream stay side by side and the team
and approvals drop to a full-width row underneath. Below 860px everything is a single column. The
viewport-height, independently-scrolling layout is a desktop idea, so below 1150px the page itself
scrolls and every panel grows to fit its content — otherwise the panels get squeezed into slivers,
which is exactly what the first version did.

## What I left out on purpose

No toasts, no modals, no confirm dialog on approve (the typed name is the confirmation), no charts,
no icon set, no CSS framework. The data on this board is three tickets and one bank balance; a
dashboard that dressed that up with sparklines would be lying about how much is going on.

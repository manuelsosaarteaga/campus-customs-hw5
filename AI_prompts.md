# AI Prompts Log

What I typed to my vibe coder (Claude Code) for each HW5 problem, in my own words.

---

## Problem 1: Vibe coder prompts

### Prompt

> first thing we need to do is set up AI_prompts.md in the root folder. make sure it has a header for Problem 1, list out what i just told you in my own words as the first prompt, and add a quick follow-up section with a brief note on what was missing. keep it clean so we can update it as we go through the rest of the homework!

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 2: Study the Campus Customs database

### Prompt

> alright next step, lets dive into the database stuff. open up data/campus_customs.db and look over all the tables and fields. duplicate data/campus_customs.db into data/campus_customs_new.db so we have a working copy to mess with later. then check out the 3 open tickets and see how they link to everything else. after that, start output/harness.md and list every single table, its fields, and a short one-liner explaining why that table is important for our agents.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 3: Build the MCP server

### Prompt

> time to build our MCP server! in the mcp_server/ directory, set up a server using FastMCP that connects directly to data/campus_customs_new.db. create 3 distinct tools that we'll need for open tickets 101, 102, and 103 (no fake data, stick strictly to what's in SQLite). then update output/harness.md listing each tool, the table it reads, which specific ticket it unlocks, and a sentence on why it fits that ticket. lastly, throw together a quick mcp_server/README.md explaining the server, the db path, and these initial 3 tools.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 4: Add the MCP server to vibe coder and test each tool

### Prompt

> now lets hook up this mcp server directly to our workspace environment so you can call the tools. save the config in .mcp.json at the project root. once connected, go ahead and run/test all 3 tools against data/campus_customs_new.db. dump the test results into output/mcp_smoke.json formatted with my prompt, the tool name, and the actual DB output returned.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 5: Build the agent team and grow the MCP tools

### Prompt

> time to build the actual agent team using PydanticAI! we need 5 agents: Boss, Inventory, Accounting, Facilities, and Customer Service. put their system prompts in backend/prompts/ (one file per agent), models in backend/models.py, and agent logic under backend/. make sure everyone uses gpt-6-luna via PORTKEY_API_KEY. wire them up so they can delegate to each other with full connectivity and log every step into output/audit_trail.json (append mode!). add any extra MCP tools they need to read data/campus_customs_new.db, then update output/harness.md with all agents/tools + a short safety section on guardrails and token limits. don't forget to update mcp_server/README.md too!

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 6: Plan the three tickets

### Prompt

> before we build the backend API, lets map out our plan for the 3 tickets. create output/desk_tickets.html as a single clickable HTML page with tabs for Ticket 101, Ticket 102, Ticket 103, Cash, and Reflection. keep Cash and Reflection blank for now. on each ticket tab, create an "Expected" section detailing: who Boss calls first and why, the full delegation flow, and which MCP tools will get called. leave space for an "Actual" section later!

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 7: Backend routes

### Prompt

> lets spin up the FastAPI backend in backend/main.py. we need endpoints to: list all 3 tickets & their status, trigger the agent team on a ticket ID, stream/fetch recent agent events & tool calls, process human approvals for payments/purchases (updating cash_accounts), check current checking balance, and reset data/campus_customs_new.db back to the original database state. make sure we can boot it with uvicorn main:app --reload --port 8000, and log a quick 1-line summary of each route in output/harness.md.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 8: Agent dashboard

### Prompt

> time to build the frontend desk dashboard using React + Vite + TypeScript in frontend/. connect it to our FastAPI backend on port 8000 (and enable CORS on port 5173). the UI should list the 3 tickets, let us pick one to run, show real-time agent thoughts/tools, mark tickets resolved when done, show agent summary cards, display the live checking balance, and provide an approval button for payments. make it look super slick and nice to use! once done, write output/design.md explaining your aesthetic choices and UI layout decisions.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 9: Resolve the tickets

### Prompt

> lets do a full live run! first hit the reset route so data/campus_customs_new.db is completely fresh, and grab the starting cash balance. run all 3 tickets (101, 102, 103) on the dashboard until they're resolved. then update output/desk_tickets.html by filling out the "Actual" section on each ticket tab, and detail the cash math (starting balance, ticket changes, ending balance) on the Cash tab. save the run summary to output/resolved_tickets.json, create output/resolved_board.html with screenshots/renderings of each resolved ticket UI, make sure output/audit_trail.json has all logs appended, and finalize output/harness.md.

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

---

## Problem 10: Reflection

### Prompt

> almost done. open up output/desk_tickets.html and fill out the "Reflection" tab with detailed, specific answers tied to our run. cover: how each agent performed on each ticket, how Actual compared to Expected, what tasks would've been easier with just a single agent + tools (and why), 3 new shop problems this team could solve with our current tools, and 3 new problems they couldn't solve (explaining what new tools/agents we'd need). keep it super specific to Campus Customs!

### Follow-up

> _None yet._

**What was missing:** _One sentence on what the first prompt didn't cover, if a follow-up was needed._

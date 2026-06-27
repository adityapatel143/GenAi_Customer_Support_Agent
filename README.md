# AI-Powered Customer Support & Returns Automation Agent
### [Check out GenAI and System Design videos](https://www.youtube.com/@CodingJist)
A production-ready, enterprise-grade multi-agent system for e-commerce customer support built with LangGraph, OpenAI, Supabase, LangSmith, and Streamlit.

---

## Architecture

```
        ┌──────────────────────────────────────────────────────────────────────┐
        │                        STREAMLIT UI (app.py)                         │
        │                                                                      │
        │   Tab 1: 🤖 Customer Chat              Tab 2: 👤 Human Agent Queue   │
        │   ─────────────────────────────        ──────────────────────────── │
        │   Chat interface                       Escalated ticket queue        │
        │   Sidebar: Customer + Ticket history   Stats bar (escalated/open)    │
        │   Tool calls expander                  Refund processing             │
        │   Escalation banner                    Return approval/rejection      │
        │   Close Ticket button                  Status & priority controls    │
        │   LangSmith trace URL                  Agent notes                   │
        └──────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────────────────┐
        │                 LANGGRAPH STATEGRAPH (graph.py)                      │
        │                                                                      │
        │  START ──► router_node (pre-filter + LLM classification)             │
        │                  │                                                   │
        │    ┌─────────────┼───────────────┬───────────┬─────────┐            │
        │    ▼             ▼               ▼           ▼         ▼            │
        │  wismo       returns_node   refunds_node  escalation  off_topic      │
        │    │             │               │           │         │             │
        │    └─────────────┴───────────────┘           │         └──► END      │
        │                  │                           ▼                      │
        │                  ▼                          END                     │
        │           responder_node                                            │
        │           (+ response guardrails)                                   │
        │                  │                                                  │
        │                  ▼                                                  │
        │                 END                                                 │
        └──────────────────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼──────────────────────────┐
         ▼                         ▼                          ▼
┌─────────────────┐   ┌─────────────────────┐   ┌────────────────────┐
│  TOOLS (src/)   │   │  SUPABASE (Postgres) │   │  LANGSMITH         │
│                 │   │                      │   │  Observability     │
│ order_tools.py  │   │  customers           │   │                    │
│ return_tools.py │◄─►│  orders              │   │  Traces / Runs     │
│ refund_tools.py │   │  return_requests     │   │  Tool call events  │
│ customer_tools  │   │  rma_records         │   │  Guardrail events  │
│ ticket_tools.py │   │  tickets             │   │  Scores/Feedback   │
└─────────────────┘   └─────────────────────┘   └────────────────────┘
         │
         ▼
┌─────────────────────────┐
│  GUARDRAILS (validators)│
│  - PII Redaction        │
│  - Toxic Language Check │
│  - Factual Consistency  │
└─────────────────────────┘
```

---

## Tech Stack

| Component       | Technology                                     |
|-----------------|------------------------------------------------|
| Language        | Python 3.12+                                   |
| Package Manager | uv (pyproject.toml)                            |
| Agent Framework | LangGraph (StateGraph)                         |
| LLM (cloud)     | OpenAI — per-role models (gpt-4o-mini / gpt-4o)|
| LLM (local)     | Ollama — optional, swappable via `.env`        |
| Database        | Supabase (PostgreSQL)                          |
| Observability   | LangSmith                                      |
| Guardrails      | Custom validators (regex + logic)              |
| UI              | Streamlit                                      |
| Config          | pydantic-settings + python-dotenv              |

---

## Project Structure

```
customer_support_agent/
├── pyproject.toml              # uv dependencies
├── .env.example                # environment variable template
├── README.md                   # this file
├── setup_database.sql          # Supabase tables + seed data
├── app.py                      # Streamlit entry point
├── src/
│   ├── config.py               # Pydantic settings
│   ├── database/
│   │   └── supabase_client.py  # Singleton Supabase client
│   ├── agents/
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── graph.py            # LangGraph StateGraph
│   │   └── nodes/
│   │       ├── router.py       # Intent classification (pre-filter + LLM)
│   │       ├── wismo.py        # Order tracking
│   │       ├── returns.py      # Return eligibility + RMA
│   │       ├── refunds.py      # Refund status + initiation
│   │       ├── escalation.py   # Human escalation
│   │       ├── responder.py    # Final response + guardrails
│   │       └── off_topic.py    # Polite refusal for off-topic/harmful
│   ├── tools/
│   │   ├── order_tools.py      # Ownership-enforced order queries
│   │   ├── return_tools.py     # Ownership-enforced return queries
│   │   ├── refund_tools.py     # Ownership-enforced refund queries
│   │   ├── customer_tools.py
│   │   └── ticket_tools.py
│   ├── guardrails/
│   │   └── validators.py       # PII, toxicity, factual checks
│   ├── human_dashboard/
│   │   ├── __init__.py
│   │   └── queue.py            # Human Agent Queue dashboard
│   └── observability/
│       ├── langsmith_client.py # LangSmith tracing (primary)
│       └── langfuse_client.py  # Backward-compat shim → re-exports langsmith_client
└── tests/
    ├── test_tools.py
    ├── test_graph.py
    └── test_guardrails.py
```

---

## Setup

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install dependencies

```bash
cd customer_support_agent
uv sync
```

### 3. Get your API keys

#### OpenAI API Key
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Click **Create new secret key**
3. Copy the key — you'll only see it once

#### Supabase URL + Service Role Key
1. Go to [supabase.com](https://supabase.com) and open your project
2. In the left sidebar click **Project Settings** (gear icon) → **API**
3. Copy two values:
   - **Project URL** → `SUPABASE_URL`
   - **service_role** key (under "Project API keys") → `SUPABASE_SERVICE_ROLE_KEY`

> **Why service role?** The agent runs server-side and needs full read/write access
> across all 5 tables (orders, customers, RMAs, tickets). The service role key
> bypasses Row Level Security so no per-table RLS policies are needed.
> **Never expose this key in frontend code or commit it to git.**

#### LangSmith API Key (optional — for observability)
1. Go to [smith.langchain.com](https://smith.langchain.com) and sign in
2. Click your avatar → **Settings** → **API Keys** → **Create API Key**
3. Copy the key (starts with `ls__`)
4. Create a project (e.g. `customer-support-agent`) — note the project name

### 4. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```dotenv
OPENAI_API_KEY=sk-...

SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...

# Optional — remove if not using LangSmith
LANGSMITH_API_KEY=ls__...
LANGSMITH_PROJECT=customer-support-agent
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=customer-support-agent
```

### 5. Load the database (one-time)

Run `setup_database.sql` in Supabase **once** before starting the app.
It creates all 5 tables and inserts seed data (12 customers, 13 orders, etc.).

**Option A — Supabase SQL Editor (easiest)**
1. Open your Supabase project → **SQL Editor** → **New query**
2. Copy-paste the entire contents of `setup_database.sql`
3. Click **Run**

**Option B — psql**
```bash
# Connection string from Supabase: Project Settings → Database → Connection string
psql "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres" \
  -f setup_database.sql
```

**Option C — Supabase CLI**
```bash
supabase db push --db-url "postgresql://postgres:<password>@<host>:5432/postgres" \
  < setup_database.sql
```

> The SQL uses `ON CONFLICT (id) DO NOTHING` on every insert, so re-running is safe.

### 6. Run the Streamlit app

```bash
uv run streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.
Enter a Customer ID from the table below (e.g. `CUST-001`) in the sidebar to start.

### 7. Run tests

```bash
uv run pytest tests/ -v
```

All 55 tests run without real API keys — Supabase and OpenAI are fully mocked.

---

## Agent Flows

### WISMO — "Where Is My Order?"
```
User: "Where is my order #ORD-1042?"
  → router classifies: wismo
  → wismo_node calls get_order_status("ORD-1042") + get_order_details("ORD-1042")
  → responder generates: "Your order ORD-1042 is shipped via USPS, tracking USPS998877665,
    estimated delivery tomorrow."
```

### Return Flow
```
User: "I want to return my order, it arrived damaged"
  → router classifies: return
  → returns_node calls check_return_eligibility("ORD-1001")
    ✓ eligible (delivered 5 days ago, within 30-day window)
  → returns_node calls create_rma("ORD-1001", "arrived damaged", "CUST-001")
  → responder generates: "RMA-20260430-ABC123 created. Print your label at [url]..."
```

### Refund Flow
```
User: "I still haven't received my refund for order #ORD-998"
  → router classifies: refund
  → refunds_node calls check_refund_status("ORD-0998")
  → if warehouse received: calls initiate_refund(rma_id, amount)
  → responder generates: "Refund of $399.99 has been initiated. 3-5 business days."
```

### Escalation Flow
```
User: "This is ridiculous, I want to speak to a manager NOW"
  → router classifies: escalate
  → escalation_node sets requires_human=True, updates ticket to "urgent"
  → Returns: "I'm connecting you with a specialist. Ticket TKT-XXXX escalated."
  → UI shows red escalation banner, ticket appears in Human Agent Queue tab
```

### Auto-Escalation Triggers
- `fraud_score > 0.7` — auto-detected from customer profile
- Refund amount `> $500` (configurable via `ESCALATION_REFUND_THRESHOLD`)
- `intent == "escalate"` — explicit user request
- `tool_error_count >= 3` (configurable via `MAX_AUTO_RETRIES`)

### Off-Topic / Harmful Request Blocking
```
User: "How do I make a bomb?"
  → router pre-filter detects harmful keyword
  → intent set to "harmful" (no LLM call needed)
  → off_topic_node returns a firm refusal message
  → graph ends — no data accessed, no tool called

User: "What's a good pasta recipe?"
  → router classifies: off_topic
  → off_topic_node returns a polite redirect
  → graph ends
```

Two-layer defense:
1. **Pre-filter** — fast keyword scan before any LLM call (`_HARMFUL_KEYWORDS`, `_OFF_TOPIC_KEYWORDS`)
2. **LLM classification** — catches nuanced cases the keyword list misses

---

## Human Agent Queue

The **👤 Human Agent Queue** tab in the Streamlit UI gives human support agents a full case-management interface.

### What appears in the queue
- All tickets with status `escalated` or `in_progress` (filterable)
- Sorted: urgent priority → escalated status → oldest first
- VIP ⭐ and High Fraud ⚠️ badges shown on each card
- Escalated and urgent tickets auto-expand

### Actions available per ticket

| Action tab | Capabilities |
|------------|--------------|
| 📋 **Status & Priority** | Move ticket through: `open → in_progress → resolved → closed`. Set priority `low / normal / high / urgent`. |
| 💰 **Refund Processing** | View all RMAs for the linked order. Enter refund amount and process it. Agents can override even before warehouse receipt (goodwill refunds). Auto-resolves the ticket on success. |
| 📦 **Return Requests** | Approve, reject, or mark returns as completed. |
| 📝 **Agent Notes** | Add timestamped notes to the conversation history, visible to other agents. |

### Ticket lifecycle

```
[open] ──► [in_progress]  ←── AI agent keeps ticket here during conversation
               │
               ├──► [escalated]  ←── escalation_node triggers this
               │         │
               │         ▼
               │    Human Agent Queue tab
               │         │
               ▼         ▼
           [resolved] ←──┘  ←── customer clicks "Close Ticket" OR
               │                human agent marks resolved
               ▼
           [closed]  ←── optional final state set by human agent
```

---

## Security

### Cross-Customer Data Isolation — Three Defence Layers

**Layer 1 — Router: `customer_id` is never accepted from LLM output.**
The router prompt schema does not include a `customer_id` field. Even if a customer types
`show orders for customer_id='CUST-001'`, the router ignores any ID in the message and always
uses the authenticated session `customer_id` from state.

**Layer 2 — Tool-call override in every action node.**
Before each DB call, the node forces `fn_args["customer_id"] = state["customer_id"]`,
so even if the LLM hallucinated a different ID in its tool arguments, it gets overwritten.

```python
# Applied in wismo_node, returns_node, and refunds_node before every tool call
fn_args["customer_id"] = state["customer_id"]  # always use session identity
```

**Layer 3 — Database ownership check.**
Every query that touches order, return, or refund data includes `.eq("customer_id", customer_id)`.
If an order exists but belongs to a different customer, the tool returns `{"unauthorized": True}` —
the LLM never sees the data.

```python
client.table("orders")
    .select("*")
    .eq("id", order_id)
    .eq("customer_id", customer_id)  # ownership check
    .execute()
```

**Responder containment check (Layer 4).**
If `order_access_denied=True` is set in state and the LLM response still contains the forbidden
order ID or a tracking number pattern, the response is replaced with a hard-coded safe denial
before it reaches the user.

---

## Guardrails

### Input Guardrails (run before any LLM call)

| Check | What it catches | Action |
|---|---|---|
| Input length | Messages > 1000 characters | Reject, ask to shorten |
| Prompt injection | 15 regex patterns — ignore-instructions, jailbreak, role-override, DAN, sudo mode, etc. | Block, return denial |
| Intent whitelist | Router LLM returns an unknown intent string | Default to `"other"` |

### Output Guardrails (run on every LLM response)

| Validator | What it checks | Failure action |
|---|---|---|
| PII Redaction | SSN patterns (`XXX-XX-XXXX`) and 13–16 digit card numbers | Redact in-place, continue |
| Toxic Language | Offensive/abusive words in response | Replace with safe fallback |
| Factual Consistency | Order ID, carrier name, dollar amounts match `order_data` (single-order context only) | Log warning, keep response |
| Access-denied containment | Response contains forbidden order ID or tracking pattern when `order_access_denied=True` | Replace with hard denial |

---

## Multi-LLM Design

Every node uses a single `get_llm(role)` factory — never instantiate `ChatOpenAI` directly.
All roles are independently configurable via `.env`.

| Role | Default model | Temp | Purpose |
|---|---|---|---|
| `router` | `gpt-4o-mini` | 0.0 | Fast intent classification (low cost, low latency) |
| `wismo` | `gpt-4o` | 0.0 | Reliable tool calling + structured order data |
| `returns` | `gpt-4o` | 0.0 | Eligibility reasoning + tool calling |
| `refunds` | `gpt-4o` | 0.0 | Refund-state reasoning + tool calling |
| `responder` | `gpt-4o` | 0.2 | Highest-quality customer-facing reply |
| `escalation` | `gpt-4o-mini` | 0.3 | Warm, personalised human-handoff message |
| `off_topic` | `gpt-4o-mini` | 0.3 | Contextual out-of-scope refusal |

Override any role in `.env` (e.g. `WISMO_MODEL=gpt-4o-mini` to reduce cost).

---

## Local Ollama Support

Set `USE_OLLAMA=true` in `.env` to route **all LLM calls** to a local Ollama server instead of OpenAI.
The per-role `{ROLE}_MODEL` variables control which Ollama model each node loads.

```bash
# Pull a model first
ollama pull llama3.2
```

```dotenv
# .env
USE_OLLAMA=true
OLLAMA_BASE_URL=http://localhost:11434   # default — change only if Ollama runs elsewhere

ROUTER_MODEL=llama3.2
WISMO_MODEL=llama3.2
RETURNS_MODEL=llama3.2
REFUNDS_MODEL=llama3.2
RESPONDER_MODEL=llama3.2
ESCALATION_MODEL=llama3.2
OFF_TOPIC_MODEL=llama3.2
```

You can mix models — e.g. use a smaller model for cheap roles and a larger one for `responder`.
When `USE_OLLAMA=false` (default), OpenAI is used and `OLLAMA_BASE_URL` is ignored.

---

## Observability (LangSmith)

LangSmith is optional — the app works without it. When configured:

- Every support session creates a **Run (trace)** tagged with `customer_id`, `ticket_id`, `intent`
- **Child runs** logged for: tool calls, guardrail failures, escalations, resolutions
- **Feedback scores** logged: `resolution_success` (0 or 1), `response_time_ms`
- LangGraph nodes are **auto-traced** via `LANGCHAIN_TRACING_V2=true` — no extra code needed
- Trace URL shown in the Streamlit sidebar for support supervisors
- `langfuse_client.py` is a backward-compatibility shim — any code importing from it continues to work, all calls are forwarded to `langsmith_client.py`

View traces at [smith.langchain.com](https://smith.langchain.com) → your project → **Runs**.

---

## Example Test Customers

| Customer ID | Name          | VIP  | Fraud Score | Notes                        |
|-------------|---------------|------|-------------|------------------------------|
| CUST-001    | Alice Johnson | ✅   | 0.0         | Normal VIP, has shipped order|
| CUST-004    | Dave Brown    | ❌   | 0.85        | High fraud — auto-escalates  |
| CUST-005    | Eve Davis     | ✅   | 0.0         | VIP with shipped phone order |

### Example Order IDs

| Order ID  | Status    | Customer  | Amount   |
|-----------|-----------|-----------|----------|
| ORD-1042  | Shipped   | CUST-001  | $87.99   |
| ORD-1001  | Delivered | CUST-001  | $89.99   |
| ORD-0998  | Delivered | CUST-003  | $399.99  |
| ORD-1008  | Delivered | CUST-008  | $549.99  |

---

## Configuration Reference

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | From platform.openai.com/api-keys |
| `SUPABASE_URL` | ✅ | — | Project Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | — | Project Settings → API → service_role key |

### Per-Role LLM Configuration (OpenAI)

Each node has its own model, temperature, and max_tokens. Unset = use the default below.

| Variable | Default | Purpose |
|---|---|---|
| `ROUTER_MODEL` | `gpt-4o-mini` | Intent classification |
| `ROUTER_TEMPERATURE` | `0.0` | |
| `ROUTER_MAX_TOKENS` | `256` | |
| `WISMO_MODEL` | `gpt-4o` | Order tracking tool calling |
| `WISMO_TEMPERATURE` | `0.0` | |
| `WISMO_MAX_TOKENS` | `1024` | |
| `RETURNS_MODEL` | `gpt-4o` | Return eligibility + RMA |
| `RETURNS_TEMPERATURE` | `0.0` | |
| `RETURNS_MAX_TOKENS` | `1024` | |
| `REFUNDS_MODEL` | `gpt-4o` | Refund status + initiation |
| `REFUNDS_TEMPERATURE` | `0.0` | |
| `REFUNDS_MAX_TOKENS` | `1024` | |
| `RESPONDER_MODEL` | `gpt-4o` | Final customer-facing reply |
| `RESPONDER_TEMPERATURE` | `0.2` | |
| `RESPONDER_MAX_TOKENS` | `1024` | |
| `ESCALATION_MODEL` | `gpt-4o-mini` | Human-handoff message |
| `ESCALATION_TEMPERATURE` | `0.3` | |
| `ESCALATION_MAX_TOKENS` | `512` | |
| `OFF_TOPIC_MODEL` | `gpt-4o-mini` | Out-of-scope refusal |
| `OFF_TOPIC_TEMPERATURE` | `0.3` | |
| `OFF_TOPIC_MAX_TOKENS` | `256` | |

### Local Ollama

| Variable | Default | Description |
|---|---|---|
| `USE_OLLAMA` | `false` | Set `true` to use Ollama instead of OpenAI for all nodes |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |

### Observability (LangSmith)

| Variable | Default | Description |
|---|---|---|
| `OBSERVABILITY_ENABLED` | `true` | Set `false` to disable all tracing |
| `LANGSMITH_API_KEY` | — | From smith.langchain.com → Settings → API Keys |
| `LANGSMITH_PROJECT` | `customer-support-agent` | LangSmith project name |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com` | LangSmith API endpoint |
| `LANGCHAIN_TRACING_V2` | — | Set `true` to enable auto LangGraph tracing |
| `LANGCHAIN_API_KEY` | — | Same as `LANGSMITH_API_KEY` (used by LangChain) |
| `LANGCHAIN_PROJECT` | — | Same as `LANGSMITH_PROJECT` (used by LangChain) |

### Business Rules

| Variable | Default | Description |
|---|---|---|
| `RETURN_WINDOW_DAYS` | `30` | Days after delivery within which returns are valid |
| `ESCALATION_REFUND_THRESHOLD` | `500` | Refund amount (USD) that triggers auto-escalation |
| `MAX_AUTO_RETRIES` | `3` | Consecutive tool errors before auto-escalation |
| `FRAUD_SCORE_THRESHOLD` | `0.7` | Customer fraud score that triggers escalation |

### App

| Variable | Default | Description |
|---|---|---|
| `APP_TITLE` | `Customer Support Agent` | Streamlit page title |
| `APP_DEBUG` | `false` | Enable debug logging |
| `LOG_LEVEL` | `INFO` | Python logging level |

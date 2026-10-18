# AI-Powered Fraud Investigation Service

A runnable Python backend that screens fictional payments with rules, collects evidence through **Model Context Protocol (MCP)**, and returns a structured investigation. Built for a clear, repeatable video demo.

- **FastAPI REST API** with interactive Swagger docs.
- **Four explainable rules:** large amount, unusual spending, rapid activity, and a new foreign country.
- **Three real MCP tools**, available over stdio and Streamable HTTP.
- **Two explicit investigation modes:** deterministic `demo` (no key needed) and model-driven `groq`.
- **SQLite persistence** for fictional accounts, transactions, and completed reports.
- **Auditable output:** rule matches, contextual assessment, evidence IDs, recommendations, and actual MCP calls with inputs, results, and timings.

## Run locally

Requires Python 3.11+. Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
uvicorn fraud_service.app:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/docs**. The service seeds its fictional data automatically. No database server, Node setup, API key, or public tunnel is needed for demo mode.

In a second terminal:

```bash
source .venv/bin/activate
fraud-demo
# Or show a single case / full JSON:
fraud-demo --case txn_spike
fraud-demo --case txn_spike --json
```

The terminal walkthrough calls the running API and displays the actual completed MCP trace. It does not simulate streaming or add artificial delays. See [the recording script](docs/DEMO.md) for a five-minute video outline.

## Try the API

```bash
curl -s http://127.0.0.1:8000/demo/cases | python -m json.tool
curl -s -X POST http://127.0.0.1:8000/investigate/txn_spike | python -m json.tool
curl -s 'http://127.0.0.1:8000/transactions?flagged_only=true' | python -m json.tool
```

The investigation requires no request body. Every successful call creates a new report; repeat requests can be compared. Retrieve a saved report using the returned `investigation_id`:

```bash
curl -s http://127.0.0.1:8000/investigations/INVESTIGATION_ID | python -m json.tool
```

| Transaction | Story | Rule score | Demo assessment |
| --- | --- | --- | --- |
| `txn_normal` | EUR 42 purchase matching prior spending | 0 / low | Low |
| `txn_spike` | EUR 9,200 purchase, new country, rapid activity | 100 / high | High |
| `txn_velocity` | Fifth purchase in a ten-minute window | 30 / medium | Medium |
| `txn_business` | EUR 8,250 payment on an account averaging EUR 7,840 | 30 / medium | Low, with business context |

The fixed dataset contains 4 accounts and 32 transactions. All timestamps are UTC; detection windows are anchored to the target transaction, so the demo continues to work on later dates.

### Response structure

The response includes:

```text
investigation_id, transaction_id, mode, model, generated_at, duration_ms
detection
  flagged, risk_score, risk_level
  matched_rules[] → rule_id, title, points, explanation, transaction_ids
  prior_transaction_count, recent_transaction_count, baseline_average_cents
assessment
  risk_level, summary
  evidence[] → observation, transaction_ids
  recommended_actions[], limitations[]
tool_trace[]
  sequence, tool, arguments, result, duration_ms
```

`detection` always comes from deterministic code. `assessment` is contextual and may disagree with screening; the business example demonstrates why. A score of 100 means all configured rule weights fired, **not** a 100% probability of fraud. Actions are recommendations; this service never blocks payments or changes accounts.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Mode, configured model, key presence (never the key) |
| GET | `/demo/cases` | Four named examples and their rule results |
| GET | `/transactions` | Screened transactions; `flagged_only`, `limit`, `offset` |
| GET | `/transactions/{transaction_id}` | Raw transaction |
| GET | `/accounts/{account_id}/history` | Account and transaction history |
| GET | `/fraud-rules` | Rule thresholds and semantics |
| POST | `/investigate/{transaction_id}` | Execute and persist an investigation |
| GET | `/investigations/{investigation_id}` | Retrieve a completed report |
| POST | `/mcp` | MCP Streamable HTTP protocol endpoint |
| GET | `/docs` | Interactive API documentation |

Unknown resources return `404`. Live mode without a key returns `503`; model/MCP failures return `502`; the overall investigation deadline returns `504`. Provider failures never silently switch to demo output.

## Enable the free-tier LLM investigator (Groq)

Create a free-plan API key in [Groq Console](https://console.groq.com/keys), copy `.env.example` to `.env` if needed, and update `.env` locally:

```dotenv
INVESTIGATION_MODE=groq
GROQ_API_KEY=your-key-here
GROQ_MODEL=openai/gpt-oss-20b
```

Restart the server after configuration changes, including when using `--reload`. The default is **GPT-OSS 20B hosted by Groq**, available on Groq's [free plan](https://console.groq.com/docs/rate-limits). An OpenAI account or paid OpenAI key is not needed. The `openai` Python package is used only as a compatible SDK; requests go to `https://api.groq.com/openai/v1` with your Groq key.

Free usage is rate-limited, not unlimited. As checked on October 18, 2026, Groq lists 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute, and 200,000 tokens/day for this model on the free plan. Check your console for your actual limits. A typical investigation makes four model requests and resends gathered evidence, so token limits can be reached before request limits. For a recording, start with `fraud-demo --case txn_spike`; use demo mode for repeated rehearsals. A quota/rate-limit response returns HTTP `429`, never a fabricated assessment.

In `groq` mode the application:

1. Opens an actual MCP client session and discovers tool schemas.
2. Sends those schemas to the model as function tools.
3. Lets the model choose calls and executes them using MCP `tools/call`.
4. Supplies tool results and a deterministic screening result to the model.
5. Requests the structured assessment in a separate call without tools, checks cited transaction IDs, and stores the result and trace.

The model must retrieve all three kinds of evidence. Calls are restricted to the target transaction and account. Tool calls, model rounds, and total runtime are bounded. Merchant text is treated as untrusted evidence. These checks improve predictability; they do not prove that a model's explanation is correct.

Only `groq` mode sends fictional evidence to Groq. `demo` mode uses templated assessments, clearly identified in the response, while still executing real MCP calls. The integration follows Groq's [Responses API](https://console.groq.com/docs/responses-api) and [structured output](https://console.groq.com/docs/structured-outputs) documentation. Tool gathering and structured output are separate requests because Groq does not currently support them together. Responses use `store=False`. Groq's Responses API is currently beta; live access requires your key and has not been verified against a real account by the automated tests.

## MCP tools

| Tool | Input | Output |
| --- | --- | --- |
| `get_transaction_details` | `transaction_id: str` | Amount in cents, merchant, country, UTC time, account |
| `get_account_history` | `account_id: str` | Account profile and available history |
| `get_fraud_rules` | none | Thresholds, weights, scoring semantics, limitations |

The MCP server uses the official [Python SDK](https://github.com/modelcontextprotocol/python-sdk). Dependencies constrain it to v1; the v2 API is different.

**HTTP:** start the REST service and connect an MCP client to `http://127.0.0.1:8000/mcp` using Streamable HTTP. This is a protocol endpoint, not a web page. It exposes exactly the three tools above.

**Stdio:** configure an MCP client to launch the following, using absolute paths appropriate to your checkout:

```json
{
  "mcpServers": {
    "fraud-investigation": {
      "command": "/absolute/path/to/Fraud-Detection-Service/.venv/bin/python",
      "args": ["-m", "fraud_service.mcp_server"],
      "env": {
        "DATABASE_PATH": "/absolute/path/to/Fraud-Detection-Service/data/fraud.db"
      }
    }
  }
}
```

The investigator uses a private stdio MCP subprocess per request. This keeps setup to one web process, avoids self-HTTP routing and public tunnels, and isolates each run. For higher throughput, a managed pool or dedicated MCP service would be more appropriate. The HTTP and stdio servers share the same repository and tool definitions.

## Rules

| Rule | Condition | Points |
| --- | --- | --- |
| Large amount | Amount **greater than** EUR 5,000 | 30 |
| Unusual spending | Amount **greater than** 5× prior mean; at least 3 prior transactions | 25 |
| Rapid activity | At least 5 transactions in the inclusive 10-minute window, including target | 30 |
| New foreign country | Outside home country and absent from strictly earlier activity | 15 |

Scores are capped at 100: low `<30`, medium `30–59`, high `>=60`. Medium and high are flagged. The target is excluded from its baseline; future transactions never influence screening. All demo payments use EUR and integer cents. Rule definitions live in `fraud_service/rules.py` and are also exposed through MCP.

## Docker

```bash
docker compose up --build
```

The service is available on localhost:8000 and the SQLite database persists in a named volume. Compose reads mode/key/model from `.env`; recreate the container after changing them:

```bash
docker compose up -d --force-recreate
```

## Development and verification

```bash
pytest -q
ruff check .
ruff format --check .
```

Tests cover rule boundaries and temporal filtering, seeded scenarios, persistence, REST error handling, actual stdio MCP investigations, HTTP MCP tool discovery/calls, and model-selected tool execution with only the hosted provider mocked. They do not require a Groq key. `requirements.lock` pins the tested dependency set and is used as a constraints file.

```text
fraud_service/
  app.py            REST API, lifespan, report persistence
  config.py         Environment configuration
  models.py         Validated request/evidence/report types
  repository.py     Parameterized SQLite access
  seed.py           Repeatable fictional scenarios
  rules.py          Deterministic screening
  mcp_server.py     Three tools over HTTP and stdio
  investigator.py   MCP client, demo investigator, model tool loop
  demo.py           Terminal recording walkthrough
tests/              Rules, API, MCP, and agent tests
docs/DEMO.md        Video outline and troubleshooting
```

This is a local, fictional-data demo with no authentication or real payment integration. The stored reports include evidence payloads. Before using real customer data or exposing the service publicly, add appropriate authentication, account authorization, retention controls, request limits, and operational monitoring. The current rules and assessments are demonstration heuristics, not a validated fraud model.

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import RateLimitError

from fraud_service.config import Settings
from fraud_service.investigator import investigate
from fraud_service.mcp_server import create_mcp
from fraud_service.models import AccountHistory, Investigation, Transaction, TransactionSummary
from fraud_service.repository import NotFoundError, Repository
from fraud_service.rules import FraudRules, detect
from fraud_service.seed import DEMO_CASES

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def is_rate_limit(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return any(is_rate_limit(child) for child in error.exceptions)
    return isinstance(error, RateLimitError)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    repository = Repository(settings.database_path)
    mcp = create_mcp(repository)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        repository.initialize()
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Fraud Investigation Service",
        version="0.1.0",
        description=(
            "Rule-based screening + evidence gathered through **real MCP tools**. "
            "Start with `GET /demo/cases`, then `POST /investigate/{transaction_id}`. "
            "Demo mode is deterministic and uses no LLM. Groq mode lets the model select "
            "MCP tools and write a structured assessment. All data is fictional."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Demo", "description": "Start here for a recording."},
            {"name": "Investigations"},
            {"name": "Evidence"},
        ],
        swagger_ui_parameters={"defaultModelsExpandDepth": -1, "docExpansion": "list"},
    )
    app.state.repository = repository
    app.state.settings = settings

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/health", tags=["Demo"])
    def health():
        return {
            "status": "ok",
            "mode": settings.investigation_mode,
            "model": settings.groq_model if settings.investigation_mode == "groq" else None,
            "live_configured": bool(settings.groq_api_key.get_secret_value()),
            "dataset": "fictional-demo-v1",
        }

    def summary(tx: Transaction) -> TransactionSummary:
        return TransactionSummary(
            transaction=tx,
            detection=detect(tx, repository.history(tx.account_id)),
            demo_label=DEMO_CASES.get(tx.transaction_id),
        )

    @app.get("/demo/cases", tags=["Demo"], response_model=list[TransactionSummary])
    def demo_cases():
        return [summary(repository.transaction(tx_id)) for tx_id in DEMO_CASES]

    @app.get("/transactions", tags=["Evidence"], response_model=list[TransactionSummary])
    def transactions(
        flagged_only: bool = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        rows = [summary(tx) for tx in repository.transactions()]
        if flagged_only:
            rows = [row for row in rows if row.detection.flagged]
        return rows[offset : offset + limit]

    @app.get("/transactions/{transaction_id}", tags=["Evidence"], response_model=Transaction)
    def transaction_details(transaction_id: str):
        return repository.transaction(transaction_id)

    @app.get("/accounts/{account_id}/history", tags=["Evidence"], response_model=AccountHistory)
    def account_history(account_id: str):
        return repository.history(account_id)

    @app.get("/fraud-rules", tags=["Evidence"])
    def fraud_rules():
        return FraudRules().tool_payload()

    @app.post(
        "/investigate/{transaction_id}",
        tags=["Investigations"],
        response_model=Investigation,
        responses={
            404: {"description": "Unknown transaction"},
            429: {"description": "Groq usage limit reached"},
            502: {"description": "Model or MCP investigation failed"},
            503: {"description": "Live mode requires GROQ_API_KEY"},
            504: {"description": "Investigation deadline exceeded"},
        },
        description=(
            "Try **txn_spike**, **txn_normal**, **txn_velocity**, or **txn_business**. "
            "Returns a rule score, contextual assessment, and actual MCP call trace. "
            "Every successful run is saved. No payments or accounts are modified."
        ),
    )
    async def investigate_transaction(transaction_id: str):
        tx = repository.transaction(transaction_id)
        if settings.investigation_mode == "groq" and not settings.groq_api_key.get_secret_value():
            raise HTTPException(
                503, "Set GROQ_API_KEY for groq mode, or use INVESTIGATION_MODE=demo"
            )
        started = perf_counter()
        try:
            async with asyncio.timeout(settings.investigation_timeout_seconds):
                detection, assessment, trace = await investigate(settings, tx)
        except TimeoutError as exc:
            raise HTTPException(504, "Investigation timed out; retry or use demo mode") from exc
        except Exception as exc:
            if is_rate_limit(exc):
                raise HTTPException(
                    429, "Groq usage limit reached; wait before retrying or use demo mode"
                ) from exc
            logger.exception("Investigation failed for transaction %s", transaction_id)
            raise HTTPException(
                502, "Investigation failed; check server logs and model configuration"
            ) from exc
        result = Investigation(
            investigation_id=f"inv_{uuid4().hex}",
            transaction_id=transaction_id,
            mode=settings.investigation_mode,
            model=settings.groq_model if settings.investigation_mode == "groq" else None,
            generated_at=datetime.now(UTC),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            detection=detection,
            assessment=assessment,
            tool_trace=trace,
        )
        repository.save_investigation(result)
        return result

    @app.get(
        "/investigations/{investigation_id}", tags=["Investigations"], response_model=Investigation
    )
    def saved_investigation(investigation_id: str):
        return repository.investigation(investigation_id)

    # Mount last so REST routes take precedence; the MCP app owns /mcp internally.
    app.mount("/", mcp_app)
    return app


app = create_app()

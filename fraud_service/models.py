from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transaction(StrictModel):
    transaction_id: str
    account_id: str
    amount_cents: int = Field(gt=0)
    currency: Literal["EUR"] = "EUR"
    merchant: str
    country: str
    timestamp: AwareDatetime
    channel: Literal["online", "in_store", "transfer"]


class Account(StrictModel):
    account_id: str
    name: str
    home_country: str
    account_type: Literal["personal", "business"]


class AccountHistory(StrictModel):
    account: Account
    transactions: list[Transaction]


class RuleMatch(StrictModel):
    rule_id: str
    title: str
    points: int
    explanation: str
    transaction_ids: list[str]


class Detection(StrictModel):
    flagged: bool
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    matched_rules: list[RuleMatch]
    prior_transaction_count: int
    recent_transaction_count: int
    baseline_average_cents: float | None


class Evidence(StrictModel):
    observation: str = Field(min_length=1)
    transaction_ids: list[str] = Field(min_length=1)


class Assessment(StrictModel):
    risk_level: RiskLevel
    summary: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    recommended_actions: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class ToolTrace(StrictModel):
    sequence: int
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    duration_ms: float


class Investigation(StrictModel):
    investigation_id: str
    transaction_id: str
    mode: Literal["demo", "groq"]
    model: str | None
    generated_at: datetime
    duration_ms: float
    detection: Detection
    assessment: Assessment
    tool_trace: list[ToolTrace]


class TransactionSummary(StrictModel):
    transaction: Transaction
    detection: Detection
    demo_label: str | None

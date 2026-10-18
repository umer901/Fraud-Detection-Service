from datetime import timedelta

from pydantic import Field

from fraud_service.models import AccountHistory, Detection, RuleMatch, StrictModel, Transaction


class FraudRules(StrictModel):
    version: str = "1.0"
    high_amount_cents: int = Field(default=500000, gt=0)
    unusual_amount_multiplier: float = Field(default=5, gt=1)
    minimum_baseline_transactions: int = Field(default=3, ge=1)
    velocity_window_minutes: int = Field(default=10, ge=1)
    velocity_count: int = Field(default=5, ge=2)
    high_amount_points: int = Field(default=30, ge=0, le=100)
    unusual_amount_points: int = Field(default=25, ge=0, le=100)
    velocity_points: int = Field(default=30, ge=0, le=100)
    new_country_points: int = Field(default=15, ge=0, le=100)
    medium_risk_threshold: int = 30
    high_risk_threshold: int = 60

    def tool_payload(self) -> dict:
        return {
            **self.model_dump(),
            "currency": "EUR",
            "rules": [
                {"id": "high_amount", "description": "Amount strictly above high_amount_cents."},
                {
                    "id": "unusual_amount",
                    "description": (
                        "Amount strictly above multiplier times mean of same-currency transactions "
                        "strictly before target; requires minimum_baseline_transactions."
                    ),
                },
                {
                    "id": "high_velocity",
                    "description": (
                        "At least velocity_count transactions in the inclusive window ending at "
                        "target time, including the target exactly once."
                    ),
                },
                {
                    "id": "new_country",
                    "description": (
                        "Country differs from home and has never appeared before target time."
                    ),
                },
            ],
            "scoring": "Add matched rule points, cap at 100. Medium >=30; high >=60.",
            "limitations": "Heuristic screening score, not a calibrated fraud probability.",
        }


def detect(tx: Transaction, history: AccountHistory, rules: FraudRules | None = None) -> Detection:
    rules = rules or FraudRules()
    if history.account.account_id != tx.account_id:
        raise ValueError("History does not belong to target account")
    # Never let the target or later transactions contaminate its spending baseline.
    peers = {
        t.transaction_id: t
        for t in history.transactions
        if t.account_id == tx.account_id and t.transaction_id != tx.transaction_id
    }
    prior = [t for t in peers.values() if t.timestamp < tx.timestamp]
    baseline = [t for t in prior if t.currency == tx.currency]
    average = sum(t.amount_cents for t in baseline) / len(baseline) if baseline else None
    window_start = tx.timestamp - timedelta(minutes=rules.velocity_window_minutes)
    recent = [t for t in peers.values() if window_start <= t.timestamp <= tx.timestamp] + [tx]
    matches = []

    def match(rule_id, title, points, explanation, transactions):
        matches.append(
            RuleMatch(
                rule_id=rule_id,
                title=title,
                points=points,
                explanation=explanation,
                transaction_ids=[t.transaction_id for t in transactions],
            )
        )

    if tx.amount_cents > rules.high_amount_cents:
        match(
            "high_amount",
            "Large amount",
            rules.high_amount_points,
            f"EUR {tx.amount_cents / 100:,.2f} exceeds the EUR "
            f"{rules.high_amount_cents / 100:,.2f} screening threshold.",
            [tx],
        )
    if (
        len(baseline) >= rules.minimum_baseline_transactions
        and average is not None
        and tx.amount_cents > average * rules.unusual_amount_multiplier
    ):
        match(
            "unusual_amount",
            "Unusual spending",
            rules.unusual_amount_points,
            f"Amount is {tx.amount_cents / average:.1f}x the prior mean of EUR "
            f"{average / 100:,.2f}, above {rules.unusual_amount_multiplier:g}x.",
            [tx, *baseline],
        )
    if len(recent) >= rules.velocity_count:
        match(
            "high_velocity",
            "Rapid activity",
            rules.velocity_points,
            f"{len(recent)} transactions within {rules.velocity_window_minutes} minutes "
            "ending at this transaction (target included).",
            recent,
        )
    if tx.country != history.account.home_country and tx.country not in {t.country for t in prior}:
        match(
            "new_country",
            "New foreign country",
            rules.new_country_points,
            f"{tx.country} is outside the home country {history.account.home_country} "
            "and absent from earlier account activity.",
            [tx],
        )
    score = min(100, sum(m.points for m in matches))
    level = (
        "high"
        if score >= rules.high_risk_threshold
        else ("medium" if score >= rules.medium_risk_threshold else "low")
    )
    return Detection(
        flagged=score >= rules.medium_risk_threshold,
        risk_score=score,
        risk_level=level,
        matched_rules=matches,
        prior_transaction_count=len(prior),
        recent_transaction_count=len(recent),
        baseline_average_cents=average,
    )

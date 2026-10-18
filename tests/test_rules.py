from datetime import timedelta

import pytest

from fraud_service.models import AccountHistory
from fraud_service.rules import detect


@pytest.mark.parametrize(
    "tx_id,score,level,rule_ids",
    [
        ("txn_normal", 0, "low", set()),
        (
            "txn_spike",
            100,
            "high",
            {"high_amount", "unusual_amount", "high_velocity", "new_country"},
        ),
        ("txn_velocity", 30, "medium", {"high_velocity"}),
        ("txn_business", 30, "medium", {"high_amount"}),
    ],
)
def test_seeded_case_scores(repository, tx_id, score, level, rule_ids):
    tx = repository.transaction(tx_id)
    result = detect(tx, repository.history(tx.account_id))
    assert (result.risk_score, result.risk_level) == (score, level)
    assert {rule.rule_id for rule in result.matched_rules} == rule_ids
    assert result.flagged == (score >= 30)


def test_future_activity_never_changes_historical_score(repository):
    tx = repository.transaction("txn_spike")
    history = repository.history(tx.account_id)
    expected = detect(tx, history)
    history.transactions.append(
        tx.model_copy(
            update={
                "transaction_id": "future",
                "amount_cents": 100000000,
                "timestamp": tx.timestamp + timedelta(seconds=1),
            }
        )
    )
    assert detect(tx, history) == expected


def test_target_is_excluded_from_baseline_and_counted_once(repository):
    tx = repository.transaction("txn_normal")
    history = repository.history(tx.account_id)
    history.transactions += [tx, tx]
    result = detect(tx, history)
    assert result.prior_transaction_count == 5
    assert result.recent_transaction_count == 1
    assert result.baseline_average_cents == 4800


def test_velocity_window_boundary_and_simultaneous_transactions(repository):
    tx = repository.transaction("txn_normal")
    history = repository.history(tx.account_id)
    history.transactions = [
        tx.model_copy(
            update={
                "transaction_id": f"edge_{i}",
                "timestamp": tx.timestamp - timedelta(minutes=offset),
            }
        )
        for i, offset in enumerate([10, 5, 2, 0, 10.01])
    ]
    result = detect(tx, history)
    assert result.recent_transaction_count == 5
    assert "high_velocity" in {r.rule_id for r in result.matched_rules}


def test_exact_amount_threshold_is_not_large(repository):
    tx = repository.transaction("txn_normal").model_copy(update={"amount_cents": 500000})
    result = detect(tx, repository.history(tx.account_id))
    assert "high_amount" not in {r.rule_id for r in result.matched_rules}
    assert "unusual_amount" in {r.rule_id for r in result.matched_rules}


def test_sparse_history_does_not_invent_baseline_anomaly(repository):
    tx = repository.transaction("txn_normal").model_copy(update={"amount_cents": 10000})
    history = repository.history(tx.account_id)
    history.transactions = [history.transactions[0]]
    result = detect(tx, history)
    assert "unusual_amount" not in {r.rule_id for r in result.matched_rules}
    history.transactions = []
    assert detect(tx, history).baseline_average_cents is None


def test_known_foreign_country_is_not_new(repository):
    tx = repository.transaction("txn_spike")
    history = repository.history(tx.account_id)
    history.transactions[0] = history.transactions[0].model_copy(update={"country": "US"})
    assert "new_country" not in {r.rule_id for r in detect(tx, history).matched_rules}


def test_wrong_account_history_is_rejected(repository):
    tx = repository.transaction("txn_normal")
    with pytest.raises(ValueError, match="target account"):
        detect(tx, repository.history("acc_sam"))


def test_unrelated_history_entries_are_ignored(repository):
    tx = repository.transaction("txn_normal")
    history = repository.history(tx.account_id)
    contaminated = AccountHistory(
        account=history.account,
        transactions=[
            *history.transactions,
            repository.transaction("txn_spike"),
        ],
    )
    assert detect(tx, history) == detect(tx, contaminated)

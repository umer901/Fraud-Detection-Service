"""Fixed, fictional fixtures: replaying the demo never depends on the wall clock."""

from datetime import UTC, datetime, timedelta

from fraud_service.models import Account, Transaction

DEMO_CASES = {
    "txn_normal": "Everyday purchase",
    "txn_spike": "Large purchase, new country, rapid activity",
    "txn_velocity": "Rapid transaction burst",
    "txn_business": "Large but typical business payment",
}


def demo_data() -> tuple[list[Account], list[Transaction]]:
    accounts = [
        Account(
            account_id="acc_alex",
            name="Alex Morgan (fictional)",
            home_country="BE",
            account_type="personal",
        ),
        Account(
            account_id="acc_sam",
            name="Sam Rivera (fictional)",
            home_country="BE",
            account_type="personal",
        ),
        Account(
            account_id="acc_jules",
            name="Jules Chen (fictional)",
            home_country="BE",
            account_type="personal",
        ),
        Account(
            account_id="acc_studio",
            name="North Studio (fictional)",
            home_country="BE",
            account_type="business",
        ),
    ]
    anchor = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    transactions = []

    def add(tx_id, account_id, cents, when, merchant, country="BE", channel="online"):
        transactions.append(
            Transaction(
                transaction_id=tx_id,
                account_id=account_id,
                amount_cents=cents,
                timestamp=when,
                merchant=merchant,
                country=country,
                channel=channel,
            )
        )

    for account in accounts:
        amounts = (
            [720000, 810000, 790000, 840000, 760000]
            if (account.account_type == "business")
            else [3500, 6200, 4800, 5100, 4400]
        )
        for i, amount in enumerate(amounts):
            add(
                f"hist_{account.account_id}_{i + 1}",
                account.account_id,
                amount,
                anchor - timedelta(days=7 - i),
                "Office supplier" if account.account_type == "business" else "Local shop",
            )

    add("txn_normal", "acc_alex", 4200, anchor, "Corner Market", channel="in_store")
    for i in range(4):
        add(
            f"burst_sam_{i + 1}",
            "acc_sam",
            1500 + i * 500,
            anchor - timedelta(minutes=8 - i * 2),
            "Digital goods",
        )
        add(
            f"burst_jules_{i + 1}",
            "acc_jules",
            3000 + i * 200,
            anchor - timedelta(minutes=8 - i * 2),
            "Online marketplace",
        )
    add("txn_spike", "acc_sam", 920000, anchor, "Electronics outlet", country="US")
    add("txn_velocity", "acc_jules", 3900, anchor, "Online marketplace")
    add("txn_business", "acc_studio", 825000, anchor, "Office supplier", channel="transfer")
    return accounts, transactions

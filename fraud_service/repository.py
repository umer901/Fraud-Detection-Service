import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fraud_service.models import Account, AccountHistory, Investigation, Transaction
from fraud_service.seed import demo_data


class NotFoundError(ValueError):
    pass


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS transactions_account ON transactions(account_id);
                CREATE TABLE IF NOT EXISTS investigations (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
            """)
            accounts, transactions = demo_data()
            db.executemany(
                "INSERT OR IGNORE INTO accounts VALUES (?, ?)",
                [(a.account_id, a.model_dump_json()) for a in accounts],
            )
            db.executemany(
                "INSERT OR IGNORE INTO transactions VALUES (?, ?, ?)",
                [(t.transaction_id, t.account_id, t.model_dump_json()) for t in transactions],
            )

    def transaction(self, transaction_id: str) -> Transaction:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
        if not row:
            raise NotFoundError(f"Transaction '{transaction_id}' was not found")
        return Transaction.model_validate_json(row[0])

    def history(self, account_id: str) -> AccountHistory:
        with self.connection() as db:
            account = db.execute(
                "SELECT payload FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            rows = db.execute(
                "SELECT payload FROM transactions WHERE account_id = ?", (account_id,)
            ).fetchall()
        if not account:
            raise NotFoundError(f"Account '{account_id}' was not found")
        transactions = sorted(
            (Transaction.model_validate_json(row[0]) for row in rows),
            key=lambda tx: (tx.timestamp, tx.transaction_id),
        )
        return AccountHistory(
            account=Account.model_validate_json(account[0]), transactions=transactions
        )

    def transactions(self) -> list[Transaction]:
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM transactions").fetchall()
        return sorted(
            (Transaction.model_validate_json(row[0]) for row in rows),
            key=lambda tx: (tx.timestamp, tx.transaction_id),
            reverse=True,
        )

    def save_investigation(self, investigation: Investigation):
        with self.connection() as db:
            db.execute(
                "INSERT INTO investigations VALUES (?, ?)",
                (investigation.investigation_id, investigation.model_dump_json()),
            )

    def investigation(self, investigation_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM investigations WHERE id = ?", (investigation_id,)
            ).fetchone()
        if not row:
            raise NotFoundError(f"Investigation '{investigation_id}' was not found")
        return json.loads(row[0])

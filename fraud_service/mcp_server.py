"""The same three read-only tools are available over stdio and Streamable HTTP."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from fraud_service.config import Settings
from fraud_service.models import AccountHistory, Transaction
from fraud_service.repository import Repository
from fraud_service.rules import FraudRules


def create_mcp(repository: Repository) -> FastMCP:
    server = FastMCP("Fraud Investigation Tools", stateless_http=True, json_response=True)
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

    @server.tool(annotations=annotations)
    def get_transaction_details(transaction_id: str) -> Transaction:
        """Retrieve a fictional transaction's amount in cents, merchant, country, and UTC time."""
        return repository.transaction(transaction_id)

    @server.tool(annotations=annotations)
    def get_account_history(account_id: str) -> AccountHistory:
        """Retrieve account profile and history. Exclude future activity when assessing a target."""
        return repository.history(account_id)

    @server.tool(annotations=annotations)
    def get_fraud_rules() -> dict[str, Any]:
        """Retrieve screening thresholds, rule weights, scoring semantics, and limitations."""
        return FraudRules().tool_payload()

    return server


def main():
    settings = Settings()
    repository = Repository(settings.database_path)
    repository.initialize()
    create_mcp(repository).run(transport="stdio")


if __name__ == "__main__":
    main()

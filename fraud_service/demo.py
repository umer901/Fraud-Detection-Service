"""A readable terminal walkthrough using the running REST API."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fraud_service.seed import DEMO_CASES


def request(base_url: str, path: str, method: str = "GET"):
    with urlopen(Request(base_url.rstrip("/") + path, method=method), timeout=310) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(
        description="Walk through the fictional fraud investigation cases"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", choices=list(DEMO_CASES), default=None)
    parser.add_argument(
        "--json", action="store_true", help="Print complete results, including tool data"
    )
    args = parser.parse_args()
    try:
        health = request(args.base_url, "/health")
        if not args.json:
            print(f"\nFRAUD INVESTIGATION / {health['mode'].upper()} MODE", flush=True)
            print("Fictional data · read-only evidence · no payment actions\n", flush=True)
        reports = []
        for tx_id in [args.case] if args.case else DEMO_CASES:
            if not args.json:
                print(f"── {DEMO_CASES[tx_id]} ({tx_id})", flush=True)
                print("   Gathering evidence through MCP…", flush=True)
            report = request(args.base_url, f"/investigate/{tx_id}", "POST")
            reports.append(report)
            if args.json:
                continue
            detection = report["detection"]
            assessment = report["assessment"]
            for trace in report["tool_trace"]:
                print(
                    f"   {trace['sequence']}. MCP {trace['tool']}"
                    f"({json.dumps(trace['arguments'])}) [{trace['duration_ms']:.0f}ms]"
                )
            print(f"   Rule score: {detection['risk_score']}/100 ({detection['risk_level']})")
            print(f"   Investigator: {assessment['risk_level'].upper()}")
            print(f"   {assessment['summary']}")
            for item in assessment["evidence"]:
                print(f"   • {item['observation']}")
            for action in assessment["recommended_actions"]:
                print(f"   → {action}")
            print(f"   Saved: {report['investigation_id']}\n", flush=True)
        if args.json:
            print(json.dumps(reports, indent=2))
    except HTTPError as exc:
        print(f"API error {exc.code}: {exc.read().decode()}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (URLError, TimeoutError) as exc:
        print(
            f"Cannot reach the service at {args.base_url}. Start uvicorn first. {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

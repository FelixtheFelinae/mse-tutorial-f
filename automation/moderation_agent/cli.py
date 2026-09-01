from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List

from .content_check import (
    CheckerConfig,
    changed_markdown_files,
    check_file,
    check_paths,
)
from .mail_ingest import ingest_eml
from .models import Action, CheckReport, strictest_action
from .provider import OpenAICompatibleProvider, review_with_model
from .queue import ModerationQueue


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "automation" / "config.json"
DEFAULT_DATABASE = REPO_ROOT / ".moderation" / "queue.sqlite3"
DEFAULT_POLICY = REPO_ROOT / "docs" / "policies" / "content-policy.md"


def _add_model_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MSE_MODEL_BASE_URL", "http://127.0.0.1:8000/v1"),
    )
    parser.add_argument(
        "--model", default=os.environ.get("MSE_MODEL_NAME", "local-model")
    )
    parser.add_argument("--api-key-env")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--thinking",
        choices=["default", "disabled", "low", "high", "max"],
        default="default",
        help="Optional DeepSeek-compatible thinking mode control.",
    )


def _model_extra_body(thinking: str) -> dict[str, object]:
    if thinking == "default":
        return {}
    if thinking == "disabled":
        return {"thinking": {"type": "disabled"}}
    return {
        "thinking": {"type": "enabled"},
        "reasoning_effort": thinking,
    }


def _relative_path(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    return candidate.as_posix()


def _print_reports(reports: Iterable[CheckReport], output_format: str) -> None:
    reports_list = list(reports)
    overall = strictest_action([report.action for report in reports_list])
    if output_format == "json":
        print(
            json.dumps(
                {
                    "action": overall.value,
                    "reports": [report.to_dict() for report in reports_list],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print("Overall action: " + overall.value)
    if not reports_list:
        print("No changed Markdown files found.")
    for report in reports_list:
        print("\n%s: %s" % (report.path, report.action.value))
        for finding in report.findings:
            location = ":%d" % finding.line if finding.line else ""
            evidence = " [%s]" % finding.evidence if finding.evidence else ""
            print(
                "  - %s%s %s: %s%s"
                % (
                    report.path,
                    location,
                    finding.rule_id,
                    finding.message,
                    evidence,
                )
            )


def _report_exit_code(reports: List[CheckReport]) -> int:
    action = strictest_action([report.action for report in reports])
    return 2 if action in {Action.RETURN_FOR_REVISION, Action.QUARANTINE} else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mse-moderation",
        description="Offline-first intake and content checks for HUST MSE Tutorial.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the public checker configuration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_file_parser = subparsers.add_parser("check-file")
    check_file_parser.add_argument("--file", required=True)
    check_file_parser.add_argument("--format", choices=["text", "json"], default="text")

    check_diff_parser = subparsers.add_parser("check-diff")
    check_diff_parser.add_argument("--base", default="upstream/main")
    check_diff_parser.add_argument("--format", choices=["text", "json"], default="text")

    ingest_parser = subparsers.add_parser("ingest-eml")
    ingest_parser.add_argument(
        "--file", required=True, help="RFC 5322 .eml file, or - for standard input."
    )
    ingest_parser.add_argument("--database", default=str(DEFAULT_DATABASE))

    queue_parser = subparsers.add_parser("queue")
    queue_parser.add_argument("--database", default=str(DEFAULT_DATABASE))
    queue_parser.add_argument("--limit", type=int, default=50)

    probe_parser = subparsers.add_parser(
        "model-probe",
        help="Send a synthetic marker prompt to verify an OpenAI-compatible endpoint.",
    )
    _add_model_connection_arguments(probe_parser)

    model_parser = subparsers.add_parser("llm-review")
    model_parser.add_argument("--file", required=True)
    _add_model_connection_arguments(model_parser)
    model_parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    model_parser.add_argument(
        "--json-output",
        action="store_true",
        help="Request OpenAI-compatible JSON object output.",
    )

    return parser


def run(arguments: argparse.Namespace) -> int:
    config = CheckerConfig.from_path(Path(arguments.config))

    if arguments.command == "check-file":
        report = check_file(REPO_ROOT, _relative_path(arguments.file), config)
        _print_reports([report], arguments.format)
        return _report_exit_code([report])

    if arguments.command == "check-diff":
        paths = changed_markdown_files(REPO_ROOT, arguments.base)
        reports = check_paths(REPO_ROOT, paths, config)
        _print_reports(reports, arguments.format)
        return _report_exit_code(reports)

    if arguments.command == "ingest-eml":
        raw_message = (
            sys.stdin.buffer.read()
            if arguments.file == "-"
            else Path(arguments.file).read_bytes()
        )
        submission, job_id, created = ingest_eml(
            raw_message, Path(arguments.database)
        )
        print(
            json.dumps(
                {
                    "job_id": job_id,
                    "created": created,
                    "message_id": submission.message_id,
                    "content_hash": submission.content_hash,
                    "attachment_count": len(submission.attachments),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "queue":
        queue = ModerationQueue(Path(arguments.database))
        print(
            json.dumps(
                queue.list_jobs(limit=max(1, arguments.limit)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "model-probe":
        provider = OpenAICompatibleProvider(
            base_url=arguments.base_url,
            model=arguments.model,
            api_key_env=arguments.api_key_env,
            allow_remote=arguments.allow_remote,
            timeout_seconds=60,
        )
        response = provider.generate(
            [
                {
                    "role": "system",
                    "content": "This is a connectivity test. Follow the user exactly.",
                },
                {"role": "user", "content": "Reply with exactly MSE_API_OK"},
            ],
            max_tokens=16,
            extra_body=_model_extra_body(arguments.thinking),
        ).strip()
        if not response:
            raise RuntimeError("model endpoint returned empty content")
        print(
            json.dumps(
                {
                    "status": "connected",
                    "model": arguments.model,
                    "marker_matched": response == "MSE_API_OK",
                    "response": response,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if arguments.command == "llm-review":
        relative_path = _relative_path(arguments.file)
        deterministic_report = check_file(REPO_ROOT, relative_path, config)
        if deterministic_report.action in {
            Action.RETURN_FOR_REVISION,
            Action.QUARANTINE,
        }:
            _print_reports([deterministic_report], "text")
            print("\nLLM review skipped because deterministic checks did not pass.")
            return 2
        provider = OpenAICompatibleProvider(
            base_url=arguments.base_url,
            model=arguments.model,
            api_key_env=arguments.api_key_env,
            allow_remote=arguments.allow_remote,
        )
        decision = review_with_model(
            provider=provider,
            content_path=REPO_ROOT / relative_path,
            policy_path=Path(arguments.policy),
            response_format_json=arguments.json_output,
            extra_body=_model_extra_body(arguments.thinking),
        )
        print(
            json.dumps(
                {
                    "action": decision.action.value,
                    "summary": decision.summary,
                    "findings": [finding.__dict__ for finding in decision.findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return (
            2
            if decision.action in {Action.RETURN_FOR_REVISION, Action.QUARANTINE}
            else 0
        )

    raise ValueError("unknown command")


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except (OSError, ValueError, RuntimeError) as exc:
        print("mse-moderation failed: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

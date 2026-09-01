from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set

from .models import CheckReport, Finding


PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\b"
    r"\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{16,})"
)
CN_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
CN_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PLACEHOLDER_RE = re.compile(r"\[(?:待填写|TODO|TBD)[^\]]*\]", re.I)


@dataclass(frozen=True)
class CheckerConfig:
    site_contact_emails: Set[str]
    trusted_contact_paths: Set[str]
    template_prefixes: List[str]
    metadata_exempt_paths: Set[str]
    metadata_exempt_prefixes: List[str]

    @classmethod
    def from_path(cls, path: Path) -> "CheckerConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            site_contact_emails={
                str(item).lower() for item in data.get("site_contact_emails", [])
            },
            trusted_contact_paths=set(data.get("trusted_contact_paths", [])),
            template_prefixes=list(data.get("template_prefixes", [])),
            metadata_exempt_paths=set(data.get("metadata_exempt_paths", [])),
            metadata_exempt_prefixes=list(
                data.get("metadata_exempt_prefixes", [])
            ),
        )


def _redact(value: str) -> str:
    if "@" in value:
        local, domain = value.split("@", 1)
        return (local[:2] + "***@" + domain) if local else "***@" + domain
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-2:]


def _publication_metadata(text: str) -> Dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: Dict[str, object] = {}
    in_publication = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.startswith(" ") and line.strip() == "publication:":
            in_publication = True
            continue
        if not line.startswith(" "):
            in_publication = False
        if not in_publication:
            continue
        match = re.match(r"^\s{2}([a-zA-Z0-9_-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        lowered = raw_value.lower()
        if lowered in {"true", "false"}:
            metadata[key] = lowered == "true"
        else:
            metadata[key] = raw_value.strip("'\"")
    return metadata


def _requires_publication_metadata(path: str, config: CheckerConfig) -> bool:
    if not path.startswith("docs/") or not path.endswith(".md"):
        return False
    if path in config.metadata_exempt_paths:
        return False
    if any(path.startswith(prefix) for prefix in config.metadata_exempt_prefixes):
        return False
    if Path(path).name == "index.md":
        return False
    return True


def check_text(path: str, text: str, config: CheckerConfig) -> CheckReport:
    report = CheckReport(
        path=path,
        checks_run=[
            "secrets",
            "personal-identifiers",
            "placeholders",
            "publication-metadata",
        ],
    )
    metadata = _publication_metadata(text)
    contact_allowed = metadata.get("public_contact_consent") is True
    template_path = any(path.startswith(prefix) for prefix in config.template_prefixes)

    for line_number, line in enumerate(text.splitlines(), start=1):
        if PRIVATE_KEY_RE.search(line):
            report.findings.append(
                Finding(
                    "SECRET_PRIVATE_KEY",
                    "blocking",
                    "发现私钥头，内容不得进入公开仓库。",
                    line_number,
                    "-----BEGIN *** PRIVATE KEY-----",
                )
            )
        if AWS_ACCESS_KEY_RE.search(line):
            report.findings.append(
                Finding(
                    "SECRET_AWS_ACCESS_KEY",
                    "blocking",
                    "发现疑似 AWS Access Key。",
                    line_number,
                    "AKIA***",
                )
            )
        assignment = SECRET_ASSIGNMENT_RE.search(line)
        if assignment:
            report.findings.append(
                Finding(
                    "SECRET_ASSIGNMENT",
                    "blocking",
                    "发现疑似凭据赋值。",
                    line_number,
                    assignment.group(1) + "=" + _redact(assignment.group(2)),
                )
            )
        for match in CN_ID_RE.finditer(line):
            report.findings.append(
                Finding(
                    "PRIVACY_CN_ID",
                    "blocking",
                    "发现疑似身份证号码。",
                    line_number,
                    _redact(match.group(0)),
                )
            )
        for match in CN_PHONE_RE.finditer(line):
            if contact_allowed:
                continue
            report.findings.append(
                Finding(
                    "PRIVACY_PHONE",
                    "review",
                    "发现手机号，但文章未确认公开联系方式授权。",
                    line_number,
                    _redact(match.group(0)),
                )
            )
        for match in EMAIL_RE.finditer(line):
            email = match.group(0).lower()
            trusted_site_contact = (
                path in config.trusted_contact_paths
                and email in config.site_contact_emails
            )
            if trusted_site_contact or contact_allowed:
                continue
            report.findings.append(
                Finding(
                    "PRIVACY_EMAIL",
                    "review",
                    "发现邮箱地址，但未确认公开联系方式授权。",
                    line_number,
                    _redact(match.group(0)),
                )
            )
        if not template_path and PLACEHOLDER_RE.search(line):
            report.findings.append(
                Finding(
                    "EDITORIAL_PLACEHOLDER",
                    "review",
                    "公开页面仍包含待填写占位符。",
                    line_number,
                    PLACEHOLDER_RE.search(line).group(0),
                )
            )

    if _requires_publication_metadata(path, config):
        required_true = [
            "author_consent_confirmed",
            "third_party_data_checked",
            "media_rights_confirmed",
        ]
        if not metadata:
            report.findings.append(
                Finding(
                    "CONSENT_METADATA_MISSING",
                    "review",
                    "经验文章缺少 publication 授权元数据。",
                )
            )
        else:
            for key in required_true:
                if metadata.get(key) is not True:
                    report.findings.append(
                        Finding(
                            "CONSENT_" + key.upper(),
                            "review",
                            "发布前必须确认 publication.%s。" % key,
                        )
                    )
            if metadata.get("status") != "ready":
                report.findings.append(
                    Finding(
                        "PUBLICATION_NOT_READY",
                        "review",
                        "publication.status 必须为 ready 才能进入发布流程。",
                    )
                )
    return report


def check_file(repo_root: Path, relative_path: str, config: CheckerConfig) -> CheckReport:
    target = (repo_root / relative_path).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError("file must be inside the repository") from exc
    return check_text(relative_path, target.read_text(encoding="utf-8"), config)


def changed_markdown_files(repo_root: Path, base: str) -> List[str]:
    command = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        base,
        "--",
        "docs",
    ]
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    untracked_result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "docs"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    untracked = {
        line.strip() for line in untracked_result.stdout.splitlines() if line.strip()
    }
    return sorted(
        path
        for path in tracked | untracked
        if path.endswith(".md") and (repo_root / path).is_file()
    )


def check_paths(
    repo_root: Path, paths: Iterable[str], config: CheckerConfig
) -> List[CheckReport]:
    return [check_file(repo_root, path, config) for path in paths]

# Offline-first automation foundation

This directory contains the first local-only foundation for email intake and content checks. It does not connect to a real mailbox, start a model, edit articles, push branches, or merge pull requests by itself.

## Safety boundary

- Raw email, the SQLite queue, credentials, and model logs stay under `.moderation/` or another private local path and are ignored by Git.
- The prototype restricts the SQLite file to the local user, but it does not implement application-level database encryption. Keep it on a FileVault-protected Mac or another encrypted volume.
- The committed `config.json` contains public rules only. It must never contain an email authorization code, API key, cookie, or token.
- Remote model endpoints are refused unless the operator explicitly passes `--allow-remote`.
- Deterministic blocking or review findings stop the LLM call.
- Content is quoted as untrusted input and cannot give the model tool or shell access.

## State model

The current importer creates jobs in `RECEIVED`. The intended later state flow is:

```text
RECEIVED
→ CONSENT_PENDING
→ NORMALIZING
→ SAFETY_SCAN
→ MODERATING
→ EDITING
→ VERIFYING
→ READY_TO_PUBLISH
→ PR_CREATED
→ AUTO_MERGED
→ PUBLISHED
```

Exceptional outcomes remain `RETURN_TO_AUTHOR`, `QUARANTINED`, `FAILED_RETRYABLE`, `WITHDRAWN`, or `PUBLISHED_ROLLBACK`.

## Local commands

Run from the repository root:

```bash
python3 -m automation.moderation_agent check-diff --base upstream/main
python3 -m automation.moderation_agent check-file --file docs/example.md
python3 -m automation.moderation_agent ingest-eml --file message.eml
python3 -m automation.moderation_agent queue
```

Raw RFC 5322 email can also arrive on standard input:

```bash
mail-export-command | python3 -m automation.moderation_agent ingest-eml --file -
```

The left side is intentionally unspecified until the dedicated mailbox and its authentication method are chosen. A CLI such as Himalaya can provide the raw email, but its authorization code must live in macOS Keychain or another secret store.

## Model connectivity probe

The probe sends only the fixed text `Reply with exactly MSE_API_OK`; it does not
upload a page, policy, email, or queued submission. Remote endpoints still need
an explicit opt-in:

```bash
python3 -m automation.moderation_agent model-probe \
  --base-url https://api.deepseek.com \
  --model deepseek-v4-pro \
  --api-key-env DEEPSEEK_API_KEY \
  --thinking disabled \
  --allow-remote
```

The key must be supplied through the named environment variable. Never put it
in this repository, a command-line argument, or a chat message.

## Moderation model review

The optional model command only accepts loopback endpoints by default:

```bash
python3 -m automation.moderation_agent llm-review \
  --file docs/example.md \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-model
```

For an endpoint that supports OpenAI-compatible JSON output, add
`--json-output`. DeepSeek-compatible endpoints additionally accept
`--thinking disabled|low|high|max`.

This command returns a validated decision. It does not edit or publish the file. Lazy model startup, constrained editing, fact-diff verification, mailbox polling, and GitHub bot publishing are later milestones.

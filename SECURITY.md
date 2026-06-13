# Security Policy

LSR was designed with a *secure-by-construction* philosophy: rather than trusting
an AI model to behave, the architecture makes unsafe behaviour structurally
impossible.

## Threat model & mitigations

| Threat | Mitigation |
|--------|------------|
| **LLM prompt injection → command execution** | AI agents are decoupled from execution. The executor accepts only a fixed allow-list of runbook tokens (`RB_*`); there is no shell-out, no `eval`, no dynamic command synthesis anywhere in the codebase. |
| **LLM hallucination → invalid runbook** | Model output is validated *in code* against the runbook references that physically exist on disk. Unknown tokens fall back to deterministic matching. |
| **Malicious alert payloads** | Strict Pydantic contracts: `asset_id` is shape-checked (`^[A-Za-z0-9_\-\.]+$`, ≤64 chars), messages capped at 2000 chars, `severity` is an enum. Invalid input → `422`. |
| **Path traversal** | User input never touches a file path. All data paths are static constants. |
| **Unauthorized state changes** | Optional API key (`LSR_API_KEY`) guards every mutating endpoint with a constant-time comparison (`Authorization: Bearer` or `X-API-Key`). Recommended for any shared deployment. |
| **Cross-origin abuse** | CORS allows only explicitly configured origins — never `*`. |
| **Information leakage** | Error responses are generic; full details are logged server-side only. `no-store`, `nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` headers on every response. |
| **Secret exposure** | No secrets in code or git history. All credentials come from a git-ignored `.env`. The `/api/config` endpoint exposes only booleans (configured / not configured), never values. |
| **Demo abuse** | `/api/demo/trigger` accepts only a hard-coded allow-list of synthetic scenarios. |
| **Unbounded memory growth** | In-memory incident history is capped (last 200 records). |
| **Container compromise** | Docker image runs as a non-root user (`uid 10001`) with a health check. |
| **Dependency on external services** | Every external call (LLM, webhooks) is best-effort with a deterministic fallback — an outage degrades gracefully, never crashes triage. |

## Data

All bundled data is **synthetic and fictional** — no real infrastructure,
people, or business information.

## Reporting a vulnerability

If you find a security issue, please open a GitHub issue **without** exploit
details and request a private channel, or contact the maintainer directly.
Responsible disclosure is appreciated — and credited.

## Hardening checklist for production

- [ ] Set `LSR_API_KEY` to a long random secret
- [ ] Set `LSR_CORS_ORIGINS` to your real dashboard origin only
- [ ] Set `LSR_ENVIRONMENT=production`
- [ ] Terminate TLS in front of the service (reverse proxy / ingress)
- [ ] Prefer managed identity (Microsoft Entra ID) over raw keys when deploying
      to Azure / Foundry Hosted Agents
- [ ] Replace the in-memory incident store with Redis/DB for multi-replica HA

# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| v1.0.x (when released) | ✅ |
| v0.x (development) | Development only — not for production use with real funds |

## Reporting a Vulnerability

Mercury Node handles real Bitcoin. Security vulnerabilities are taken extremely seriously.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Report security issues privately to: **security@hvecorp.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact (especially: can it affect funds?)
- Your suggested fix (optional but appreciated)

We will acknowledge within 24 hours and aim to have a fix within 7 days for critical issues.

## Responsible Disclosure

We ask that you:
- Give us reasonable time to fix before public disclosure
- Do not exploit the vulnerability beyond what's needed to demonstrate it
- Do not access or modify other users' data

In return, we will:
- Acknowledge your report promptly
- Keep you informed of fix progress
- Credit you in the release notes (unless you prefer anonymity)

## Threat Model

Mercury Node's threat model prioritizes:
1. **Key safety** — your 24-word seed never leaves your hardware
2. **Fund safety** — the Mercury agent has read-only access; it cannot move funds autonomously above the configured threshold
3. **Node availability** — the Bitcoin stack must survive agent crashes
4. **Network security** — LND gRPC and BTCPay are not exposed to the internet by default

# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main (Sprint 1) | ✅ |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Open a [private security advisory](https://github.com/Jagadeesh0463/signalnoise-ai/security/advisories/new) on GitHub.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive an acknowledgement within 48 hours and a resolution timeline within 7 days.

## Scope

In scope:
- PII leakage through any pipeline stage
- Secret exposure in code or configuration
- Prompt injection via document content
- Path traversal in file upload handling
- Authentication bypass (Sprint 3+)

Out of scope:
- Vulnerabilities in third-party dependencies (report to the dependency maintainer, then open an issue here linking the CVE)
- Issues in sample data files
- Rate limiting / DoS (single-user tool in Sprint 1)

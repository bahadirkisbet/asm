# 0001. Local operation broker and OS credential storage

- Status: accepted
- Date: 2026-11-09

## Context
Agents need to complete setup without humans copying credentials into chats.
Redacting values after a tool returns is too late. Both input and output paths
must be controlled before they reach the agent.

## Decision
Use one Rust CLI/MCP executable. A trusted local configuration declares named
operations and secret metadata. Agents select operation names, never plaintext
values or arbitrary output projections. Capture adapters consume raw data inside
ASM; delivery adapters resolve references inside ASM. Public results contain only
configured identifiers, status and static error codes. Production values live in
the OS credential store. An explicit ephemeral mode exists for isolated testing.

## Options considered
- Regex redaction: insufficient for unknown/transformed values and late capture.
- New encrypted vault: unnecessary cryptography, unlock and recovery complexity.
- OS store plus broker: chosen for small local deployment and shared MCP interface.
- Isolated remote broker: stronger boundary, deferred until hostile-code isolation
  is required.

## Consequences
Configuration and metadata must contain no secrets and are trusted code. An agent
with same-user shell access can bypass or modify this configuration. External
programs and destinations can leak values; ASM does not sandbox them. Normal
browser tools must not view secret-bearing pages. No raw response/log passthrough
is available. Provider MFA and OS store unlock requirements remain in force.

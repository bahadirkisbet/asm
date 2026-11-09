# Verification

## Local evidence — 2026-11-09

- macOS ARM64; Rust/Cargo 1.94.1.
- `cargo test`: seven tests, including command failure/timeout/output cap, private
  file capture/delivery, overwrite protection, generation, validation, FIFO
  rejection and a slowly streamed incomplete WebSocket frame.
- `python3 tests/e2e.py --keyring`: real binary over MCP protocol versions
  2024-11-05 and 2025-11-25; file/environment/CLI/API/browser capture and
  file/child-environment/HTTP-header/HTTP-JSON/browser delivery. Local Chrome
  creates a token asynchronously after a click, starting with a stale value.
  The fixture verifies the exact submitted token. Generated secret and known
  sentinels are absent from all collected tool responses and stdout/stderr.
- Error cases include credential-echoing HTTP errors, redirects, missing
  operations, existing entries/files, command failure and command timeout.
- macOS Keychain roundtrip across separate CLI processes; unique test entry
  removed in cleanup. This validates the actual persistence path, not just the
  memory backend.
- `python3 tests/client_compat.py`: Claude Code 2.1.319 performs a real MCP health
  handshake using isolated temporary config. Codex CLI 0.167.0 parses the server
  configuration through per-command overrides. Global client settings unchanged.

## Review

Independent blind security review found two availability defects: FIFO inputs
could block before validation, and partial WebSocket frames could bypass an idle
timeout. Both were reproduced with failing tests and fixed. A delayed browser
issuance test additionally caught stale-token capture; capture now waits for a
changed nonempty value after a click. Independent re-review passed with no
remaining Critical or Important findings. Formatting and strict Clippy checks
also passed.

## One-command installer — 2026-11-09

- Seven installer tests cover preservation, private backups, idempotency,
  conflicting/malformed entries, missing clients, partial registration failure,
  existing operations and custom parent-directory permissions.
- Independent installer review passed after correcting parent-directory permission
  handling. Rust formatting/Clippy/tests and full MCP/browser E2E also passed.
- Live installation registered ASM in both native clients. Parsed client settings
  before/after were identical after excluding the new ASM entries. Claude's live
  MCP health check connected; Codex's native parser recognized the enabled entry.
- No model-driven production setup was run.

## Remaining limits

No production account/provider workflows were exercised. Native Codex verification
is config-level plus independent MCP wire tests, not a model-driven tool call.
Claude verification is native health/handshake, not a model-driven setup task.
Linux Keyring persistence needs an unlocked Secret Service and has not been
tested locally. Browser coverage uses a real Chrome instance and a local synthetic
provider, not arbitrary third-party sites. No independent cryptographic audit,
memory-dump resistance proof or universal leak-proof claim is made.

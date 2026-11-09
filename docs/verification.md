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

## Private Git marketplace — 2026-11-09

- Native builds for macOS arm64, macOS x86_64 and Linux x86_64 passed Rust tests
  and release-binary MCP exchange tests in [workflow 42583128196](https://github.com/bahadirkisbet/asm/actions/runs/42583128196).
  Bundled binaries identify source `fc78a8631299f2741f07c8d913bf36327a68fd28`;
  packaging verifies source, version and SHA-256 before copying any artifact.
- Nineteen Python unit tests cover both installers, configuration preservation,
  private backups, idempotency, preflight conflicts, legacy policy preservation,
  user scope, launcher integrity checks and artifact provenance.
- `python3 tests/plugin_e2e.py` passed from a relocated plugin directory containing
  spaces, using the bundled binary: both MCP protocols, all exchange adapters,
  real Chrome capture/delivery, error/no-leak checks and CLI status contracts.
- Claude's native plugin and marketplace validators passed. The optional public
  directory icon warning remains; this is a private Git marketplace.
- Independent packaging/migration review found no remaining Critical or Important
  code findings after regression-tested fixes for scoped installs and legacy
  permission/hook rules.
- Installed `asm@bahadir-plugins` version 0.1.1 in both real clients from the
  private Git URL `git@personal:bahadirkisbet/asm.git`, then reran the migration
  successfully to verify idempotency. Both managed direct-MCP definitions are
  absent. Parsed before/after settings are identical excluding ASM plugin,
  marketplace and legacy registration entries; operations config is byte-identical.
- Claude's plugin inventory contains the `secrets` skill and ASM MCP server;
  `claude mcp get plugin:asm:asm` reports Connected.
- A fresh Codex app-server session loaded exactly one ASM server with
  `asm_catalog` and `asm_execute`, plus enabled `asm:secrets`. Its native
  `mcpServer/tool/call` API successfully called `asm_catalog` and returned the
  existing one-secret/two-operation catalog. This was a read-only catalog call
  through the installed plugin, without a model turn or credential mutation.
- Independent artifact review verified all three hashes, executable permissions,
  source/version records, config/license inclusion and relocated package E2E.

## Remaining limits

No production account/provider workflows or model-driven setup tasks were
exercised. Native Codex verification includes an app-server catalog tool call;
Claude verification is native health/handshake and plugin component inventory.
Linux Keyring persistence needs an unlocked Secret Service and has not been
tested locally. Browser coverage uses a real Chrome instance and a local synthetic
provider, not arbitrary third-party sites. No independent cryptographic audit,
memory-dump resistance proof or universal leak-proof claim is made.

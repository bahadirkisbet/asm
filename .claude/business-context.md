# ASM business context

## 2026-11-09 — autonomous secret exchange
- The user wants Claude Code and Codex to complete authorized setup without asking
  a human to copy secrets between tools.
- Secret values must stay outside model-visible arguments, responses and logs.
- Rust CLI and shared MCP server are the chosen delivery surfaces.
- Local capture/delivery adapters reuse an OS credential store; building a new
  encrypted vault, hosted service or universal traffic interceptor is out of scope.
- Same-user hostile-code isolation is not a first-version guarantee.

## 2026-11-09 — secret environment visibility
- The user wants the agent to know which environment a used secret belongs to.
- Add per-secret environment metadata in catalogs and successful results; do not
  infer environments from names or change existing credential storage identity.
- Omitted labels remain explicitly unspecified for backward compatibility.
- Storage partitioning and cross-environment authorization were not requested;
  distinct credentials continue to use distinct namespaces or secret names.

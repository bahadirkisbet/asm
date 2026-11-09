# ASM plugin

Agentic Secret Manager captures, generates and delivers credentials locally,
returning references and safe status instead of secret values.

Install `asm@bahadir-plugins` from the private `bahadirkisbet/asm` Git marketplace
using Claude Code or Codex. This directory is self-contained: client manifests,
MCP definitions, a `secrets` skill, Python launcher, and native binaries.

```sh
claude plugin install asm --marketplace bahadirkisbet/asm
```

Python 3.9+ is required. Supported bundles: macOS arm64, macOS x86_64, Linux x86_64
(Ubuntu 22.04+ with libdbus and Secret Service). Rust and network downloads are
not required at startup. The launcher checks the bundled SHA-256 before execution.
The trusted Git package is the trust root; hashes are not publisher signatures.

Operations default to `~/.config/asm/operations.json`; set `ASM_CONFIG` in the
client environment to select an existing custom config. Credentials stay in the
OS store, never in this plugin folder. Updates/uninstall preserve user data.

Tools: `asm_catalog` lists definitions; `asm_execute` runs a named authorized
operation. First launch creates demo definitions if no config exists. Configure
your own operations before real provider setup. Never put values in descriptions,
operation arguments or metadata. See the source repository README for the schema.

This broker does not sandbox same-user code, intercept other tools, bypass MFA,
or prevent a receiving application from logging a value. Keep secret-bearing
steps inside ASM and select meaningful provider verification operations.

Native executable versions, SHA-256 hashes and source commits are in
`bin/manifest.json`. The repository's `plugin-binaries` CI workflow tests release
binaries before packaging. Maintainers must update plugin versions and bundle
checksums together.

---
name: secrets
description: Use ASM to capture, generate or deliver credentials during authorized setup without copying plaintext secrets into chat. Use for ASM catalog questions and secret-handling steps; not for general security advice.
---

Use the plugin's `asm_catalog` tool to discover secret references, descriptions
and named operations. `asm_execute` accepts only an operation name. It returns a
reference and status, or a safe error code; it never returns a credential value.

Before an operation, read its definition in the trusted operations configuration:
`~/.config/asm/operations.json`, unless the user configured `ASM_CONFIG`. Check
the intended provider, environment and side effects against the user's task.
An existing setup authorization applies; do not ask the user to copy a credential
merely because a step uses one.

If an operation is missing, add the smallest required definition to the user's
chosen operations config, using names, paths, selectors and references only.
The server loads configuration at startup, so reload/restart its MCP connection
after a config change. Do not replace unrelated definitions. Never place a
credential value in config, tool arguments, command arguments or descriptions.

Route secret-bearing file/CLI/API/browser steps through ASM before raw output
could enter context. Use the browser capture operation's `click` for token
issuance; do not click with another browser tool and inspect the result first.
Do not inspect source credentials through shell output, screenshots, DOM dumps,
clipboard reads or another MCP tool. ASM does not intercept those other tools.

Interpret statuses narrowly: `stored` means the OS store accepted the write;
`delivered` means a file write or form fill completed; `command_succeeded` means
exit 0; `http_succeeded` means HTTP 2xx; `browser_condition_met` means a configured
selector appeared. Use an authenticated provider check to establish acceptance.

An error after token issuance or submission may leave an external side effect.
Inspect safe provider state before retrying; do not repeatedly create tokens.
If the plugin is unavailable, report its static error and restore the connection
instead of falling back to printing secrets. OS unlock and provider MFA still
apply. Same-user hostile-code isolation is outside ASM's guarantee.

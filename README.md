# ASM — Agentic Secret Manager

Let Claude Code and Codex complete authorized setup without asking a human to
copy credentials into chat. ASM captures and delivers values locally. The agent
receives references and status, never the captured data.

**Early local release.** macOS and Linux, Rust 1.88+. This is an operation broker,
not a sandbox for hostile agents. Read [the security boundary](SECURITY.md).

## Install and try

```sh
cargo install --path . --locked
asm --config examples/demo.json check
asm --config examples/demo.json catalog
asm --config examples/demo.json execute generate-session-key
asm --config examples/demo.json execute check-session-key
asm --config examples/demo.json delete session-key
```

The demo stores a random credential in the OS store, passes it to a subprocess,
checks its length without printing it, and removes it. macOS uses Keychain;
Linux needs a running, unlocked Secret Service and `libdbus-1-dev` to build.
Store unlock/access prompts are controlled by the OS, not bypassed by ASM.
No cloud account or ASM server is needed. Windows is not yet supported.

`--ephemeral` explicitly selects an in-memory store for tests. It lasts for one
process, useful for multiple MCP calls; separate CLI invocations do not share it.
ASM never silently falls back to ephemeral storage if the OS store fails.

## Connect Claude Code and Codex

Use absolute executable and configuration paths:

```sh
claude mcp add --transport stdio asm -- /absolute/path/to/asm --config /absolute/path/to/operations.json mcp
codex mcp add asm -- /absolute/path/to/asm --config /absolute/path/to/operations.json mcp
```

Alternatively adapt [Claude's MCP JSON](examples/claude.mcp.json) or
[Codex's TOML entry](examples/codex.toml). These are ordinary stdio MCP tools;
separate client-specific plugins are unnecessary for the first release.
Client tool permissions still apply. Pre-authorize only operations appropriate
for the project using the client's settings; ASM does not disable those controls.

Agent instruction:

> Use `asm_catalog` to discover available secret references and operations.
> Use `asm_execute` with an operation name for secret capture or delivery.
> Never read source files, run token-issuing commands, or inspect secret-bearing
> browser pages through another tool. Do not paste values into tool arguments.
> Treat operation failures as failures; an upstream side effect may already have
> happened, so do not blindly repeat token creation or submission.

Only two tools are exposed:

- `asm_catalog()` returns configured descriptions, references, operation names,
  and storage mode. Configured does not mean the secret exists yet.
- `asm_execute({"operation":"generate-session-key"})` performs a named operation.

Successful example:

```json
{"operation":"generate-session-key","secret_ref":"asm://asm-demo/session-key","status":"stored"}
```

Failures are static codes, e.g. `{"error":"secret_not_found"}`, with MCP
`isError: true` or CLI exit status 1. No raw stderr, response body, browser tree,
screenshot, or library exception is forwarded. There is no plaintext `get` tool.

## Trusted operation configuration

Configuration is local executable policy, not a place for credentials. Keep it
outside untrusted repositories, restrict its permissions, and review changes.
Names, descriptions, URLs, arguments and static JSON must contain **no secrets**.
Choose one namespace per project/environment. The OS key is service
`asm/<namespace>` plus the declared secret name. Renaming either does not migrate
stored credentials. Relative file paths resolve beside the configuration file.

```json
{
  "namespace": "myapp-dev",
  "secrets": {"api-token": {"description": "Development service token"}},
  "operations": {
    "capture-issued-token": {
      "kind": "capture",
      "secret": "api-token",
      "source": {
        "kind": "command",
        "command": {
          "program": "/absolute/path/to/provider-cli",
          "cwd": "/absolute/path/to/project",
          "args": ["token", "create", "--json"]
        },
        "json_pointer": "/access_token"
      }
    },
    "check-service-auth": {
      "kind": "deliver",
      "secret": "api-token",
      "destination": {
        "kind": "http",
        "request": {"url": "https://api.example.com/account"},
        "placement": {"kind": "header", "name": "Authorization", "prefix": "Bearer "}
      }
    }
  }
}
```

Capture sources:

| `kind` | Fields | Behavior |
|---|---|---|
| `file` | `path`, optional `json_pointer` | Read UTF-8 text or a JSON string field |
| `environment` | `variable` | Read inside ASM; do not put the value in MCP config |
| `command` | `command`, optional `json_pointer` | Capture bounded stdout, discard stderr |
| `http` | `request`, `json_pointer` | Capture a string from a successful JSON response |
| `browser` | `page`, `selector`, optional `click` | Optional click, then wait for a nonempty DOM value |

Without `json_pointer`, exactly one trailing LF or CRLF is removed; other
whitespace is preserved. JSON pointers use RFC 6901 syntax (`/a~1b` for key `a/b`).
Files containing dotenv syntax are not parsed as key/value pairs in this release.
Use environment capture, JSON or a raw value file instead.

Delivery destinations:

| `kind` | Fields | Behavior |
|---|---|---|
| `file` | `path`, optional `replace` | Atomic private file, mode 0600; no overwrite by default |
| `command` | `command`, `variable` | Bind the value to a child environment variable |
| `http` | `request`, `placement` | Put it in a header or top-level JSON field |
| `browser` | `page`, `selector`, optional `submit`, `success_selector` | Fill, optionally submit and wait for a DOM condition |

`placement` is `{"kind":"header","name":"Authorization","prefix":"Bearer "}`
or `{"kind":"json_field","field":"token"}`. A `request` supports `url`,
`method` (default GET), optional static `json`, and optional
`auth: {"secret":"existing-secret-name","header":"Authorization","prefix":"Bearer "}`.
JSON delivery refuses to overwrite an existing body field. HTTP redirects and
automatic proxies are disabled. HTTPS is required; `allow_http_loopback: true`
explicitly permits HTTP on loopback for local development.

A `command` needs absolute `program` and `cwd`, optional `args`,
`timeout_seconds` (1–60, default 15), and `secret_env` mapping environment variable
names to declared secret names. It runs without inherited credentials; only
PATH, HOME, TMPDIR, LANG and SYSTEMROOT are inherited. Required credentials must
be explicitly bound. Subprocess stdout never leaves ASM, including delivery
commands. Timeouts kill the owned process group. This is not process sandboxing.

`generate` operations need `secret` and `bytes` (16–1024 random bytes), encoded
as URL-safe base64 without padding. Capture/generate refuse existing entries
unless the operation explicitly sets `replace: true`. Replacement does not
revoke the old provider credential. Deletion is available only on the human CLI.

## Browser workflow

Use a dedicated local Chrome profile with remote debugging enabled. Login/MFA
may be necessary first. Never expose its debugging port to the network. ASM
attaches only to loopback CDP and selects exactly one already-open page by URL:

```json
{
  "kind": "browser",
  "page": {
    "endpoint": "http://127.0.0.1:9222",
    "url": "https://provider.example/settings/tokens",
    "timeout_seconds": 15
  },
  "click": "#create-token",
  "selector": "#new-token"
}
```

The click and capture occur inside ASM. With `click`, capture waits for a nonempty
value different from the pre-click value, preventing stale-token capture during
asynchronous issuance. A click that merely reveals an unchanged value will time
out; omit `click` when capturing an already-issued value. Input/textarea `.value` or element
`.textContent` is read. Delivery sets an input/textarea value, dispatches input
and change events, optionally clicks submit and waits for `success_selector`.
Every evaluation checks the exact page URL. Navigation during an operation fails
closed. No screenshots, page bodies, console events or CDP errors are returned.

Current scope: top-level DOM fields. Canvas/OCR, clipboard, network interception,
iframes, shadow DOM and arbitrary SPA flows are not implemented. Each provider
needs selectors and a meaningful success condition; a selector merely existing
does not independently prove a credential was accepted.

## Verification and limits

`stored` means the store accepted the write; `delivered` means the file write or
form fill completed. `command_succeeded` means exit 0; `http_succeeded` means
2xx; `browser_condition_met` means the configured selector appeared. Configure
a real authenticated check when you need proof the provider accepted a token.
ASM does not infer deployment success from a successful field assignment.

```sh
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --locked
python3 tests/e2e.py
python3 tests/e2e.py --keyring  # optional live OS store test, unique item cleaned up
```

Python tests use only the standard library and local HTTP fixtures. Set
`ASM_CHROME` to Chrome/Chromium if auto-discovery fails. `--skip-browser` is an
explicit partial run. Tests exercise two MCP protocol versions, every adapter,
provider errors/echoes, overwrite rejection, subprocess failure/timeouts and
absence of synthetic credentials in stdout/stderr/tool results. Browser tests
verify the exact submitted value at the fixture server. Test resources have
scoped teardown. See [verification evidence](docs/verification.md).

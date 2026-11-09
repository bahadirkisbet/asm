# Runnable ASM examples

These use the real ASM executable with synthetic credentials and an in-memory
store. No account, API key, browser login, Rust compiler or Keychain unlock is
needed. Python 3.9+ and a supported bundled platform are required; Linux also
needs the `libdbus-1-3` runtime library (an unlocked Secret Service is not needed
for these ephemeral examples).

From the repository root (or the installed plugin directory):

```sh
python3 examples/run.py all
```

Run one workflow, or show the exact value-free operation config:

```sh
python3 examples/run.py file
python3 examples/run.py cli
python3 examples/run.py http --show-config
```

| Example | Flow | What is verified |
|---|---|---|
| `file` | JSON file → ASM → private destination file | The destination has exactly the source value and permissions `0600`. Environment: `development`. |
| `cli` | Token-issuing CLI → ASM → child process environment | The receiving program authenticates using `SERVICE_TOKEN`, without printing it. Environment: `development`. |
| `http` | Local token endpoint → ASM → authenticated HTTP request | The local server accepts the exact credential in the Authorization header. Environment: `staging`. |

Each workflow calls `asm_catalog`, then `asm_execute` with `capture-token` and
`use-token`. The client sends operation names, never the credential value.
Successful output contains references, environments, statuses and `verified: true`.
The credential does not appear in console output. An unexpected failure returns
`{"error":"example_failed"}` and a nonzero exit code, without dumping upstream
output. `--show-config` exposes only definitions; temporary paths and ports expire
when the run finishes.

Files, the local HTTP server and ASM processes are cleaned up on completion or
ordinary failure. Existing operations and OS-stored secrets are untouched.
The HTTP example binds only to `127.0.0.1` on an automatically allocated port.

`provider.py` is a fake issuing CLI used **inside ASM** by the `cli` example.
Do not run its `issue` subcommand in the agent's shell: its purpose is to model a
provider CLI that emits a credential, which ASM captures privately.

## Adapt to a real setup

Inspect `run.py` or use `--show-config` to see the definitions. Copy the relevant
operations into your trusted ASM config, replace fixture paths/endpoints with
your provider's equivalents, and set the correct secret description/environment.
For a real CLI, replace the command's program/arguments and JSON pointer; for a
real API, use HTTPS and an existing secret reference for authentication when
needed. Never paste tokens into JSON configuration or tool arguments.

These are synthetic provider workflows, not evidence that a particular cloud
provider accepts the same commands, response fields or authentication method.

## Development checks

From a source checkout, use a freshly built binary explicitly:

```sh
cargo build --locked
python3 examples/run.py all --binary target/debug/asm
```

The launcher is otherwise discovered relative to this file, so the same examples
work from a relocated plugin cache without a source checkout.

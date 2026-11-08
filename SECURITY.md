# Security boundary

ASM prevents its capture/delivery results from directly exposing plaintext values
to an agent. It does not guarantee secrecy against an agent or process with the
same OS privileges, filesystem access, or access to the browser debugging port.

## Trusted components

- The local configuration, executable, OS credential store and OS user session.
- Programs receiving environment variables, HTTP destinations and browser pages.
- Metadata: names, descriptions, URLs and command arguments must be non-secret.
- The person or automation authorizing operations and configuring client tools.

ASM does not intercept other tools. A normal shell read, browser snapshot or
provider CLI outside ASM can still expose a secret. Child programs can write
files, send network requests or create detached processes. Binding a secret to
an agent-editable program is not a barrier against malicious code. Stronger
guarantees need a separate OS identity/sandbox and controlled egress.

## Implemented controls

- No plaintext read MCP/CLI endpoint and no secret-valued MCP parameters.
- Static error codes; no raw upstream errors, captured stdout/stderr, HTTP bodies,
  CDP responses, screenshots or logging subscribers.
- OS-backed persistent storage; explicit memory-only test mode; no fallback.
- Fail-closed operation lookup, declared secret bindings, length checks, nonempty
  UTF-8 values and NUL rejection. Capture limit 1 MiB, secret limit 16 KiB.
- OS entropy for generation. No homegrown encryption.
- HTTPS by default, redirects/proxies off; local HTTP requires explicit opt-in.
- Local-only CDP endpoint and exact page URL checks.
- Clean child environment, bounded capture and timeout, owned process-group cleanup.
- Private atomic destination files, explicit overwrite policy and process locking
  for ASM store mutations. Other OS-store clients do not honor the ASM lock.
- Owned secret buffers are zeroized where practical. Library/JSON/HTTP/browser
  buffers can retain copies; no complete memory erasure or core-dump protection
  is claimed. Credentials are plaintext in memory while in use.

## Operational limits

The OS may require unlock or access consent. Provider MFA/CAPTCHA remains intact.
An external token may be issued before local persistence fails. A submitted
request may have succeeded before a network timeout. File sync failure can occur
after publication. Errors do not mean side effects were rolled back; check the
provider before retrying non-idempotent operations. Source credentials are not
deleted after capture, and rotation/revocation is provider-specific.

References include namespace and name and are identifiers, not bearer tokens.
Descriptions and operation results can still reveal service/project metadata.
Protect config and logs accordingly. Do not place secrets in URL query strings
or identifiers. Browser target content remains visible to that browser session.

Report security issues privately to the repository owner. Never include real
credentials, account cookies or unredacted production logs in an issue.

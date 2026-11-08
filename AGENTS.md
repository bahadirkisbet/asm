# ASM

Read README.md and docs/adr/0001-secret-boundary.md before changes.
Never return or log captured values, subprocess output, HTTP bodies, browser
responses, or upstream error strings. Public errors are static codes.
Secret values must not be MCP tool arguments. Tools execute named local operations.
Test with synthetic secrets only. No real account credentials in fixtures.
Run cargo fmt --check, cargo clippy --all-targets -- -D warnings, cargo test,
and python3 tests/e2e.py before declaring success. Browser E2E needs Chrome.

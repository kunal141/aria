"""
ARIA offline demo harness (Week 30 — Launch Readiness).

This package contains demonstration entry points ONLY. It builds no new
capability and is never imported by production code paths (the graph, the
model router, the skills). Every demo here is:

  - offline      — forces a key-gated provider with no key, so skills take
                   their deterministic mock path; no paid API call is possible
  - deterministic — fixed seed inputs, isolated temp ledger, repeatable output
  - local-only   — no network, no model download, no deployment
  - non-mutating — writes to a temp directory that is removed on exit

See ``golden_path.py`` for the end-to-end request -> routing -> skill ->
evidence -> artifact -> Work Ledger -> ROI flow.
"""

# Securva Snapshot — Scanner (Phase 2)

This directory contains the scanner orchestrator for the Securva Snapshot
product. The orchestrator takes a domain as input, runs 8 section collectors
in sequence, and emits a structured JSON blob that Phase 3 (Jinja2 PDF
templating) will consume.

## Architecture

```
orchestrator.py
    ├── collectors/security_headers.py    (api.securva.net)
    ├── collectors/ssl_tls.py             (api.securva.net)
    ├── collectors/ndpa_compliance.py     (api.securva.net)
    ├── collectors/infrastructure.py      (local dig + optional box subfinder)
    ├── collectors/known_cves.py          (response headers, box nuclei in Phase 2.1)
    ├── collectors/code_exposure.py       (box github-dork-runner-v4 in Phase 2.1)
    ├── collectors/remediation.py         (derived from other sections)
    └── collectors/executive_summary.py   (derived from all sections)
```

Each collector exposes `collect(domain, box_ssh=None) -> dict` matching a
well-defined shape. Collectors that need Securva-box tooling (subfinder, dnsx,
nuclei, github-dork-runner) check for `box_ssh` and fall back to stubs when
running locally.

## Running it

```
python3 orchestrator.py --domain babakizo.com
```

or with an output file:

```
python3 orchestrator.py --domain babakizo.com --output sample-output.json
```

or with full box access for complete scans:

```
python3 orchestrator.py --domain babakizo.com \
    --box-ssh babakinzo@165.232.109.143 \
    --output scan-result.json
```

Total runtime against a clean site: **~3 seconds** (without box).
With box subfinder + dork runner: **~2-3 minutes** depending on target surface.

## JSON schema

The output schema is `snapshot-report/v1`. Top-level structure:

```json
{
  "schema_version": "snapshot-report/v1",
  "report_id": "SEC-SS-YYYYMMDD-HHMM",
  "domain": "example.com",
  "generated_at_utc": "2026-04-15T15:52:00Z",
  "generator": "securva-snapshot-orchestrator/0.2",
  "orchestration_seconds": 3.0,
  "sections": {
    "security_headers": { ... },
    "ssl_tls": { ... },
    "ndpa_compliance": { ... },
    "infrastructure": { ... },
    "known_cves": { ... },
    "code_exposure": { ... },
    "remediation": { ... },
    "executive_summary": { ... }
  }
}
```

See `sample-output-babakizo-com.json` for a real rendered example.

## Next: Phase 3

Phase 3 will wire this JSON output into the existing `pdf-template/template.html`
via Jinja2, so the same template renders any domain's report instead of just
babakizo.com's hardcoded values. That work is scoped for next session.

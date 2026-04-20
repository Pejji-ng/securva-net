#!/usr/bin/env python3
"""
Securva Snapshot — Scanner API (Phase 4.1)

FastAPI service that wraps orchestrator.py + render.py so the Cloudflare
Worker can invoke end-to-end scan+render over HTTP.

Phase 4.1 change: Box no longer uploads PDF to R2 directly.
Instead, the PDF bytes are returned base64-encoded in the response JSON.
The Worker is responsible for writing to R2 via its native binding.

Rationale: eliminates dependency on R2 S3-API endpoint, removes need
for R2 S3 credentials on the box, keeps all R2 writes inside the
Worker runtime (tighter blast radius).

Deployed on the Securva research box. Not publicly accessible — nginx
reverse-proxies from scanner.internal.securva.net with IP allowlist
restricted to Cloudflare's edge IPs + our own IPs.

Run locally for testing:
  uvicorn api:app --reload --host 127.0.0.1 --port 8089

Production systemd service: see DEPLOY.md.

Endpoint:
  POST /scan-and-render
    Headers: Authorization: Bearer <BOX_API_TOKEN>
    Body:    { "domain": "...", "tier": "Starter", "job_id": "..." }
    Returns: { "status": "ok", "pdf_base64": "<base64>",
               "scan_json": {orchestrator output}, "runtime_ms": 2500 }
"""

import base64
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

# Path setup so we can import from the sibling package
SCANNER_DIR = Path(__file__).parent
sys.path.insert(0, str(SCANNER_DIR))

from orchestrator import orchestrate  # noqa: E402
from render import prepare_template_context, render_html, render_pdf  # noqa: E402


def render_pdf_from_json(scan_json: dict, output_path: str, tier: str = "Starter") -> None:
    """Convenience wrapper: report JSON -> HTML -> PDF."""
    ctx = prepare_template_context(scan_json)
    ctx["tier"] = tier
    html = render_html(ctx)
    render_pdf(html, output_path)


# Reject absurdly large PDFs (our template produces ~1-5 MB; anything over
# 20 MB is either a template bug or an attack).
MAX_PDF_BYTES = 20 * 1024 * 1024

EXPECTED_TOKEN = os.environ.get("BOX_API_TOKEN")
if not EXPECTED_TOKEN:
    print("WARNING: BOX_API_TOKEN not set — every request will 401", file=sys.stderr)


app = FastAPI(
    title="Securva Snapshot Scanner API",
    version="0.4.1",
    description="Internal. Not for public use.",
)


class ScanRequest(BaseModel):
    domain: str
    tier: str = "Starter"
    job_id: str

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if v.startswith("https://"):
            v = v[8:]
        if v.startswith("http://"):
            v = v[7:]
        v = v.split("/")[0]
        if "." not in v or len(v) > 253:
            raise ValueError("invalid domain")
        return v

    @field_validator("tier")
    @classmethod
    def valid_tier(cls, v: str) -> str:
        if v not in {"Card", "Starter", "Pro", "Whitelabel"}:
            raise ValueError(f"invalid tier: {v}")
        return v


@app.get("/health")
def health():
    return {"status": "ok", "service": "securva-snapshot-scanner"}


@app.post("/scan-and-render")
async def scan_and_render(
    req: ScanRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not authorization or authorization != f"Bearer {EXPECTED_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    start = time.monotonic()

    try:
        scan_json = orchestrate(req.domain)
    except Exception as e:
        raise HTTPException(500, f"Scan failed: {e}")

    pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
        render_pdf_from_json(scan_json, output_path=pdf_path, tier=req.tier)

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        if len(pdf_bytes) > MAX_PDF_BYTES:
            raise HTTPException(
                500,
                f"PDF exceeds {MAX_PDF_BYTES} byte ceiling "
                f"({len(pdf_bytes)} bytes) — refusing to return",
            )

        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Render failed: {e}")
    finally:
        if pdf_path:
            try:
                os.unlink(pdf_path)
            except OSError:
                pass

    runtime_ms = int((time.monotonic() - start) * 1000)

    return {
        "status": "ok",
        "pdf_base64": pdf_b64,
        "pdf_bytes": len(pdf_bytes),
        "scan_json": scan_json,
        "runtime_ms": runtime_ms,
    }

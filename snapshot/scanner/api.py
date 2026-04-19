#!/usr/bin/env python3
"""
Securva Snapshot — Scanner API (Phase 4)

FastAPI service that wraps orchestrator.py + render.py so the Cloudflare
Worker can invoke end-to-end scan+render over HTTP.

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
    Returns: { "status": "ok", "pdf_url": "r2-signed-url",
               "scan_json": {orchestrator output}, "runtime_ms": 2500 }
"""

import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, HttpUrl, field_validator

# Path setup so we can import from the sibling package
SCANNER_DIR = Path(__file__).parent
sys.path.insert(0, str(SCANNER_DIR))

from orchestrator import orchestrate  # noqa: E402
from render import prepare_template_context, render_html, render_pdf  # noqa: E402


def render_pdf_from_json(scan_json: dict, output_path: str, tier: str = "Starter") -> None:
    """Convenience wrapper: report JSON -> HTML -> PDF."""
    # Tier is informational; the template currently uses a hardcoded tier string
    # that could be parameterized later if needed.
    ctx = prepare_template_context(scan_json)
    ctx["tier"] = tier
    html = render_html(ctx)
    render_pdf(html, output_path)

# ============================================================
# Config
# ============================================================

EXPECTED_TOKEN = os.environ.get("BOX_API_TOKEN")
if not EXPECTED_TOKEN:
    print("WARNING: BOX_API_TOKEN not set — every request will 401", file=sys.stderr)

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "securva-snapshots")
R2_PRESIGN_TTL_SECONDS = 14 * 24 * 3600  # 14 days

# Construct S3-compatible client for R2
_r2_client = None


def get_r2_client():
    global _r2_client
    if _r2_client is None:
        _r2_client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _r2_client


# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(
    title="Securva Snapshot Scanner API",
    version="0.4.0",
    description="Internal. Not for public use.",
)


class ScanRequest(BaseModel):
    domain: str
    tier: str = "Starter"
    job_id: str

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, v: str) -> str:
        # Normalize: strip scheme if present, strip path, lowercase
        v = v.strip().lower()
        if v.startswith("https://"):
            v = v[8:]
        if v.startswith("http://"):
            v = v[7:]
        v = v.split("/")[0]
        # Basic sanity
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
    # Auth
    if not authorization or authorization != f"Bearer {EXPECTED_TOKEN}":
        raise HTTPException(401, "Unauthorized")

    start = time.monotonic()

    # 1. Run scanner orchestrator
    try:
        scan_json = orchestrate(req.domain)
    except Exception as e:
        raise HTTPException(500, f"Scan failed: {e}")

    # 2. Render PDF to tempfile
    pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
        render_pdf_from_json(scan_json, output_path=pdf_path, tier=req.tier)
    except Exception as e:
        raise HTTPException(500, f"Render failed: {e}")

    # 3. Upload to R2
    r2_key = f"snapshots/{req.job_id}.pdf"
    try:
        client = get_r2_client()
        with open(pdf_path, "rb") as f:
            client.put_object(
                Bucket=R2_BUCKET,
                Key=r2_key,
                Body=f.read(),
                ContentType="application/pdf",
            )
        # 4. Generate presigned URL (14-day expiration)
        presigned_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET, "Key": r2_key},
            ExpiresIn=R2_PRESIGN_TTL_SECONDS,
        )
    except Exception as e:
        raise HTTPException(500, f"R2 upload failed: {e}")
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass

    runtime_ms = int((time.monotonic() - start) * 1000)

    return {
        "status": "ok",
        "pdf_url": presigned_url,
        "scan_json": scan_json,
        "runtime_ms": runtime_ms,
    }

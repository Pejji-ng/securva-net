#!/usr/bin/env python3
"""
Securva Snapshot - Scanner API (Phase 4.1)

FastAPI service that wraps orchestrator.py + render.py so the Cloudflare
Worker can invoke end-to-end scan+render over HTTP.

Phase 4.1 change: Box no longer uploads PDF to R2 directly.
Instead, the PDF bytes are returned base64-encoded in the response JSON.
The Worker is responsible for writing to R2 via its native binding.

Rationale: eliminates dependency on R2 S3-API endpoint, removes need
for R2 S3 credentials on the box, keeps all R2 writes inside the
Worker runtime (tighter blast radius).

Deployed on the Securva research box. Not publicly accessible - nginx
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
import shutil
import subprocess
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


def render_pdf_from_json(
    scan_json: dict,
    output_path: str,
    tier: str = "Starter",
    web2_jsonl: Optional[str] = None,
    vendor_jsonl: Optional[str] = None,
) -> None:
    """Convenience wrapper: report JSON -> HTML -> PDF.

    v1.0 (2026-04-21): optional `web2_jsonl` forwards a pattern-lab-web2 scanner
    output path into prepare_template_context so Section 9 (Sector Peer
    Benchmarks) renders when findings are present.

    v1.1 (2026-04-23): optional `vendor_jsonl` forwards a TIN-verify output path
    into prepare_template_context so Section 10 (Vendor Compliance / NTAA 2026
    §45) renders when vendor findings are present.
    """
    ctx = prepare_template_context(
        scan_json,
        web2_jsonl=web2_jsonl,
        vendor_jsonl=vendor_jsonl,
    )
    ctx["tier"] = tier
    html = render_html(ctx)
    render_pdf(html, output_path)


# Path to pattern-lab-web2 scanner. Overridable via env for non-default deploys.
WEB2_SCANNER_PATH = os.environ.get(
    "WEB2_SCANNER_PATH",
    "/home/babakinzo/bounty/pattern-lab-web2/scanner-web2.py",
)
WEB2_SCANNER_TIMEOUT_SEC = 60

# Path to TIN-verify CLI. Overridable via env for non-default deploys.
TIN_VERIFY_PATH = os.environ.get(
    "TIN_VERIFY_PATH",
    "/home/babakinzo/bounty/tools/tin-verify/tin_verify.py",
)
TIN_VERIFY_TIMEOUT_SEC = 120  # 25 vendors at ~1.5s each + slack
TIN_VERIFY_MAX_VENDOR_CSV_BYTES = 256 * 1024  # Enforced pre-decode. Caps list size.


def _invoke_web2_scanner(domain: str) -> tuple[Optional[str], Optional[str]]:
    """Run scanner-web2.py for this domain and return (jsonl_path, tmpdir).

    Returns (None, None) on any failure - the render path's `{% if web2_findings %}`
    guard in the template means absent JSONL is safe (report renders without Section 9).

    Caller is responsible for cleaning up `tmpdir` once render is complete.
    """
    scanner_path = Path(WEB2_SCANNER_PATH)
    if not scanner_path.exists():
        print(f"WARN: web2 scanner not found at {scanner_path}", file=sys.stderr)
        return None, None
    try:
        tmpdir = tempfile.mkdtemp(prefix="web2-scan-")
        result = subprocess.run(
            ["python3", str(scanner_path), "--target", domain, "--out-dir", tmpdir],
            capture_output=True,
            text=True,
            timeout=WEB2_SCANNER_TIMEOUT_SEC,
        )
        # Exit codes 0 and 1 are both legitimate (1 = high-conf finding present).
        # Only orchestrator failures (exit 2) or timeouts are degrade-to-None.
        if result.returncode == 2:
            print(f"WARN: web2 scanner orchestrator error: {result.stderr[:200]}", file=sys.stderr)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, None
        jsonls = list(Path(tmpdir).glob("scan-results-*.jsonl"))
        if not jsonls:
            print(f"WARN: web2 scanner produced no JSONL output", file=sys.stderr)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, None
        return str(jsonls[0]), tmpdir
    except subprocess.TimeoutExpired:
        print(f"WARN: web2 scanner exceeded {WEB2_SCANNER_TIMEOUT_SEC}s timeout", file=sys.stderr)
        return None, None
    except Exception as e:
        print(f"WARN: web2 scanner invocation failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None, None


def _invoke_tin_verify(vendor_csv_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
    """Run tin_verify.py against a vendor CSV and return (jsonl_path, tmpdir).

    `vendor_csv_bytes` is the raw CSV content (already size-checked by caller).
    The CSV is written to a temp file, the CLI is invoked, the resulting JSONL
    is returned. On any failure returns (None, None) — template's
    `{% if vendor_findings %}` guard makes absence safe.

    Privacy: the temp CSV is deleted in this function's finally block. The
    JSONL that persists (in tmpdir, caller cleans up) is verdict-only per the
    TIN-verify schema and stores no raw TINs or phone numbers.

    Caller is responsible for cleaning up `tmpdir` once render is complete.
    """
    cli_path = Path(TIN_VERIFY_PATH)
    if not cli_path.exists():
        print(f"WARN: tin-verify CLI not found at {cli_path}", file=sys.stderr)
        return None, None

    tmpdir = None
    csv_path = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="tin-verify-")
        csv_fd, csv_path = tempfile.mkstemp(suffix=".csv", prefix="vendors-", dir=tmpdir)
        with os.fdopen(csv_fd, "wb") as f:
            f.write(vendor_csv_bytes)
        jsonl_path = Path(tmpdir) / "vendors.jsonl"

        result = subprocess.run(
            ["python3", str(cli_path),
             "--input", csv_path,
             "--output", str(jsonl_path)],
            capture_output=True,
            text=True,
            timeout=TIN_VERIFY_TIMEOUT_SEC,
        )
        if result.returncode != 0:
            print(f"WARN: tin-verify CLI exit {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, None
        if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
            print("WARN: tin-verify produced no JSONL output", file=sys.stderr)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None, None
        return str(jsonl_path), tmpdir
    except subprocess.TimeoutExpired:
        print(f"WARN: tin-verify exceeded {TIN_VERIFY_TIMEOUT_SEC}s timeout", file=sys.stderr)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return None, None
    except Exception as e:
        print(f"WARN: tin-verify invocation failed: {type(e).__name__}: {e}", file=sys.stderr)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return None, None
    finally:
        if csv_path:
            try:
                os.unlink(csv_path)
            except OSError:
                pass


# Reject absurdly large PDFs (our template produces ~1-5 MB; anything over
# 20 MB is either a template bug or an attack).
MAX_PDF_BYTES = 20 * 1024 * 1024

EXPECTED_TOKEN = os.environ.get("BOX_API_TOKEN")
if not EXPECTED_TOKEN:
    print("WARNING: BOX_API_TOKEN not set - every request will 401", file=sys.stderr)


app = FastAPI(
    title="Securva Snapshot Scanner API",
    version="0.4.2",
    description="Internal. Not for public use.",
)


class ScanRequest(BaseModel):
    domain: str
    tier: str = "Starter"
    job_id: str
    # Optional: base64-encoded CSV of vendors to feed into TIN-verify for
    # Section 10 (Vendor Compliance / NTAA 2026 §45). Format documented at
    # ~/bounty/tools/tin-verify/README.md (columns: business_name, rc_number,
    # tin, phone). Absent → Section 10 doesn't render; the PDF falls through
    # to web-only Snapshot.
    vendor_csv_b64: Optional[str] = None

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

    @field_validator("vendor_csv_b64")
    @classmethod
    def valid_vendor_csv_b64(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        # Reject anything that couldn't fit in memory cleanly. The decoded-bytes
        # limit is enforced after decode in the handler for the ground truth.
        if len(v) > TIN_VERIFY_MAX_VENDOR_CSV_BYTES * 2:
            raise ValueError("vendor_csv_b64 too large")
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

    # v1.0 (2026-04-21): fire the pattern-lab-web2 scanner in-line. The JSONL
    # gets passed into render so Section 9 (Sector Peer Benchmarks) renders when
    # findings exist. Scanner failure degrades gracefully - report renders
    # without Section 9 rather than failing the whole /scan-and-render call.
    web2_jsonl, web2_tmpdir = _invoke_web2_scanner(req.domain)

    # v1.1 (2026-04-23): when the caller supplies a vendor_csv_b64, fire
    # TIN-verify against it so Section 10 (Vendor Compliance / NTAA 2026 §45)
    # renders. Same degrade-gracefully semantics as web2: a failure here
    # produces no Section 10, not a failed report.
    vendor_jsonl: Optional[str] = None
    vendor_tmpdir: Optional[str] = None
    if req.vendor_csv_b64:
        try:
            vendor_csv_bytes = base64.b64decode(req.vendor_csv_b64, validate=True)
        except Exception as e:
            raise HTTPException(400, f"vendor_csv_b64 not valid base64: {e}")
        if len(vendor_csv_bytes) > TIN_VERIFY_MAX_VENDOR_CSV_BYTES:
            raise HTTPException(
                400,
                f"vendor CSV exceeds {TIN_VERIFY_MAX_VENDOR_CSV_BYTES} byte limit "
                f"({len(vendor_csv_bytes)} bytes)",
            )
        vendor_jsonl, vendor_tmpdir = _invoke_tin_verify(vendor_csv_bytes)

    pdf_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
        render_pdf_from_json(
            scan_json,
            output_path=pdf_path,
            tier=req.tier,
            web2_jsonl=web2_jsonl,
            vendor_jsonl=vendor_jsonl,
        )

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        if len(pdf_bytes) > MAX_PDF_BYTES:
            raise HTTPException(
                500,
                f"PDF exceeds {MAX_PDF_BYTES} byte ceiling "
                f"({len(pdf_bytes)} bytes) - refusing to return",
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
        if web2_tmpdir:
            shutil.rmtree(web2_tmpdir, ignore_errors=True)
        if vendor_tmpdir:
            shutil.rmtree(vendor_tmpdir, ignore_errors=True)

    runtime_ms = int((time.monotonic() - start) * 1000)

    return {
        "status": "ok",
        "pdf_base64": pdf_b64,
        "pdf_bytes": len(pdf_bytes),
        "scan_json": scan_json,
        "runtime_ms": runtime_ms,
        "web2_findings_included": bool(web2_jsonl),
        "vendor_findings_included": bool(vendor_jsonl),
    }

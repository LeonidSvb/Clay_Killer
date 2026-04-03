"""
core/errors.py — Unified error normalization for all enrichment adapters.

Error format: "{source}_{type}" with optional "({detail})"
  api_rate_limit (429)
  api_server_error (500)
  api_timeout (30s)
  api_no_result
  api_not_found (404)
  llm_parse_error
  llm_empty_response
  data_empty_url
  data_empty_email
  sys_stopped
  sys_unknown

Result schema (all adapters must return this):
  {
    "idx":     int,
    "ok":      bool,
    "data":    dict,       # output columns only — empty on failure
    "error":   str | None, # standardized code — None on success
    "elapsed": float,
    **extra                # adapter-specific fields (url, domain, etc.)
  }

When saving to table:
  - success row: data written to output col, error col left empty/skipped
  - failure row: error written to "{output_col} Error", output col left empty
  This way "Fill missing" on the output col naturally re-queues failed rows.
"""

import re as _re


# ── Error code normalization ───────────────────────────────────────────────────

def normalize_http_error(status: int, body: str = "") -> str:
    """Map HTTP status to a standardized error code."""
    if status == 429:
        return "api_rate_limit (429)"
    if status == 404:
        return "api_not_found (404)"
    if status >= 500:
        return f"api_server_error ({status})"
    if status >= 400:
        return f"api_client_error ({status})"
    return f"api_http_{status}"


def normalize_exception(exc: Exception) -> str:
    """Map a Python exception to a standardized error code."""
    name = type(exc).__name__
    msg  = str(exc)[:80]
    if "timeout" in name.lower() or "timeout" in msg.lower():
        return "api_timeout"
    if "connectionerror" in name.lower() or "connection" in msg.lower():
        return "api_connection_error"
    if "sslerror" in name.lower() or "ssl" in msg.lower():
        return "api_ssl_error"
    return f"sys_unknown ({name})"


def make_result(
    idx: int,
    ok: bool,
    data: dict,
    error: str | None,
    elapsed: float,
    **extra,
) -> dict:
    """
    Construct a standardized result dict.
    All enrichment adapters should use this to build their return values.
    """
    return {
        "idx":     idx,
        "ok":      ok,
        "data":    data,
        "error":   error,
        "elapsed": elapsed,
        **extra,
    }


def error_result(idx: int, error: str, elapsed: float = 0.0, **extra) -> dict:
    """Shorthand for a failed result with no data."""
    return make_result(idx=idx, ok=False, data={}, error=error, elapsed=elapsed, **extra)


def success_result(idx: int, data: dict, elapsed: float, **extra) -> dict:
    """Shorthand for a successful result."""
    return make_result(idx=idx, ok=True, data=data, error=None, elapsed=elapsed, **extra)


# ── Result post-processing ─────────────────────────────────────────────────────

def split_into_output_and_error(
    results: list[dict],
    output_col: str,
) -> list[dict]:
    """
    For each result, restructure data so that:
      - success → data[output_col] = value (error col absent)
      - failure → data[f"{output_col} Error"] = error_code (output col absent)
      - unknown → data[f"{output_col} Error"] = "sys_unknown" (both absent)

    This ensures Fill missing works correctly:
      - output col empty on failure → re-queued on next run
      - error col tells you WHY it failed
    """
    out = []
    for r in results:
        r2 = dict(r)
        error_col = f"{output_col} Error"

        if r["ok"] and r.get("data"):
            # Success: keep data as-is, ensure no error col
            r2["data"] = {k: v for k, v in r["data"].items()}
        elif r.get("error"):
            # Known failure: blank output, write error to error col
            r2["data"] = {error_col: r["error"]}
        else:
            # Unknown / no data / no error — sys_unknown
            r2["ok"] = False
            r2["error"] = "sys_unknown"
            r2["data"] = {error_col: "sys_unknown"}

        out.append(r2)
    return out


def collect_output_keys(results: list[dict]) -> set[str]:
    """All data keys across all results, excluding internal fields."""
    keys: set[str] = set()
    for r in results:
        if r.get("data"):
            keys.update(r["data"].keys())
    keys.discard("raw")
    return keys

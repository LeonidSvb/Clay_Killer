"""
app/components/col_stats.py — Column statistics widget for generated columns.

Auto-detects value type and renders appropriate stats:
  boolean      → true/false/null distribution
  json         → per-field recursive stats
  few_unique   → full distribution with % bars + clickable filters
  categorical  → top-5 + other + clickable filters
  scraped_text → word count buckets
  generative   → uniqueness ratio + top repeats detection
  numeric      → min/avg/max + bucket histogram
"""

import json
from collections import Counter

import pandas as pd
import streamlit as st


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _coverage(series: pd.Series) -> tuple[int, int, float]:
    total = len(series)
    if total == 0:
        return 0, 0, 0.0
    empty = int(
        series.isna().sum()
        + series.astype(str).str.strip().isin(["", "nan", "None"]).sum()
    )
    filled = total - min(empty, total)
    return filled, total, filled / total * 100


def _clean(series: pd.Series) -> pd.Series:
    return series[~(series.isna() | series.astype(str).str.strip().isin(["", "nan", "None"]))]


def _add_filter(col: str, val: str) -> None:
    filters = st.session_state.get("filters", [])
    for f in filters:
        if f.get("col") == col and f.get("val") == val and f.get("op") == "=":
            return
    filters.append({"col": col, "op": "=", "val": val})
    st.session_state.filters = filters
    st.rerun()


# ── Mode detection ─────────────────────────────────────────────────────────────

def _detect_mode(series: pd.Series) -> str:
    clean = _clean(series)
    if len(clean) == 0:
        return "empty"

    str_vals = clean.astype(str).str.strip()
    unique_vals = str_vals.unique()
    n_unique = len(unique_vals)

    # Boolean
    bool_set = {"true", "false", "null", "yes", "no", "1", "0", "none"}
    if n_unique <= 4 and all(v.lower() in bool_set for v in unique_vals):
        return "boolean"

    # Numeric
    numeric_ok = pd.to_numeric(str_vals, errors="coerce").notna().sum()
    if numeric_ok / len(str_vals) > 0.8:
        return "numeric"

    # JSON
    sample = str_vals.head(30)
    json_hits = sum(1 for v in sample if v.strip().startswith("{"))
    if json_hits / len(sample) > 0.5:
        return "json"

    # Scraped text (by median word count)
    wc = str_vals.apply(lambda x: len(x.split()))
    if wc.median() > 80:
        return "scraped_text"

    # Few unique / categorical
    if n_unique <= 7:
        return "few_unique"
    if n_unique <= 50:
        return "categorical"

    return "generative"


# ── Mode renderers ─────────────────────────────────────────────────────────────

def _render_boolean(series: pd.Series) -> None:
    str_vals = series.astype(str).str.strip().str.lower()
    counts = Counter(str_vals)
    total = len(str_vals)
    for val, cnt in counts.most_common():
        pct = cnt / total * 100
        st.markdown(f"`{val}` &nbsp; {_bar(pct)} &nbsp; **{pct:.0f}%** ({cnt:,})")


def _render_few_unique(series: pd.Series, col: str) -> None:
    clean = _clean(series).astype(str).str.strip()
    counts = Counter(clean)
    total = len(clean)
    for val, cnt in counts.most_common():
        pct = cnt / total * 100
        c1, c2 = st.columns([6, 1])
        with c1:
            st.markdown(f"`{val[:60]}` &nbsp; {_bar(pct)} &nbsp; **{pct:.0f}%** ({cnt:,})")
        with c2:
            if st.button("filter", key=f"_flt_{col}_{val[:30]}", use_container_width=True):
                _add_filter(col, val)


def _render_categorical(series: pd.Series, col: str) -> None:
    clean = _clean(series).astype(str).str.strip()
    counts = Counter(clean)
    total = len(clean)
    top = counts.most_common(5)
    top_total = sum(cnt for _, cnt in top)
    other = total - top_total

    for val, cnt in top:
        pct = cnt / total * 100
        c1, c2 = st.columns([6, 1])
        with c1:
            st.markdown(f"`{val[:60]}` &nbsp; {_bar(pct)} &nbsp; **{pct:.0f}%** ({cnt:,})")
        with c2:
            if st.button("filter", key=f"_flt_{col}_{val[:30]}", use_container_width=True):
                _add_filter(col, val)

    if other > 0:
        pct = other / total * 100
        n_other = len(counts) - 5
        st.caption(f"other &nbsp; {_bar(pct)} &nbsp; {pct:.0f}% ({other:,} rows, {n_other} values)")


def _render_numeric(series: pd.Series, label: str = "") -> None:
    nums = pd.to_numeric(series.astype(str).str.strip(), errors="coerce").dropna()
    if len(nums) == 0:
        st.caption("no numeric values")
        return

    mn, mx, avg = nums.min(), nums.max(), nums.mean()
    prefix = f"**{label}** &nbsp; " if label else ""
    st.markdown(f"{prefix}min **{mn:.0f}** · avg **{avg:.1f}** · max **{mx:.0f}**")

    # Confidence/score buckets (1-10 scale)
    if mx <= 10:
        buckets = [("1–3", 1, 3), ("4–6", 4, 6), ("7–8", 7, 8), ("9–10", 9, 10)]
    elif mx <= 100:
        buckets = [("0–25", 0, 25), ("26–50", 26, 50), ("51–75", 51, 75), ("76–100", 76, 100)]
    else:
        return

    total = len(nums)
    for name, lo, hi in buckets:
        cnt = int(((nums >= lo) & (nums <= hi)).sum())
        if cnt == 0:
            continue
        pct = cnt / total * 100
        st.markdown(f"`{name}` &nbsp; {_bar(pct)} &nbsp; **{pct:.0f}%** ({cnt:,})")


def _render_scraped_text(series: pd.Series) -> None:
    clean = _clean(series).astype(str)
    wc = clean.apply(lambda x: len(x.split()))
    total = len(wc)
    med = int(wc.median())

    st.markdown(f"median **{med}** words")

    buckets = [
        ("0–50 words", 0, 50, "failed / JS-heavy"),
        ("51–200", 51, 200, "sparse"),
        ("201–500", 201, 500, "partial"),
        ("501–1000", 501, 1000, "good"),
        ("1000+", 1001, 999999, "rich"),
    ]
    for name, lo, hi, hint in buckets:
        cnt = int(((wc >= lo) & (wc <= hi)).sum())
        if cnt == 0:
            continue
        pct = cnt / total * 100
        # Show exact word range hint only for big buckets
        st.markdown(f"`{name}` &nbsp; {_bar(pct)} &nbsp; **{pct:.0f}%** ({cnt:,}) &nbsp; _{hint}_")

    failed = int((wc <= 50).sum())
    if failed / total > 0.15:
        st.warning(f"{failed:,} pages with ≤50 words — likely JS-heavy or failed scrape")


def _render_generative(series: pd.Series) -> None:
    clean = _clean(series).astype(str).str.strip()
    total = len(clean)
    n_unique = clean.nunique()
    ratio = n_unique / total * 100

    bar = _bar(ratio)
    st.markdown(f"uniqueness &nbsp; {bar} &nbsp; **{ratio:.0f}%** &nbsp; ({n_unique:,} / {total:,})")

    if ratio < 50:
        st.warning("Low diversity — LLM may be repeating answers")

    # Top repeats
    counts = Counter(clean)
    top_repeats = [(v, c) for v, c in counts.most_common(5) if c > 1]
    if top_repeats:
        st.caption("Top repeating values:")
        for val, cnt in top_repeats:
            pct = cnt / total * 100
            preview = val[:70] + "..." if len(val) > 70 else val
            st.markdown(f"- `{preview}` &nbsp; ×{cnt} &nbsp; ({pct:.1f}%)")

    # Prefix fingerprint (template leak detection)
    prefix_len = 30
    prefix_counts = Counter(v[:prefix_len] for v in clean if len(v) >= prefix_len)
    stuck = [(p, c) for p, c in prefix_counts.most_common(3) if c / total > 0.1]
    if stuck:
        st.warning("Template pattern detected — LLM may be stuck:")
        for prefix, cnt in stuck:
            pct = cnt / total * 100
            st.markdown(f'- `"{prefix}..."` &nbsp; {pct:.0f}% of rows')


def _render_json(series: pd.Series) -> None:
    clean = _clean(series).astype(str).str.strip()
    parsed = []
    for v in clean:
        try:
            obj = json.loads(v)
            if isinstance(obj, dict):
                parsed.append(obj)
        except Exception:
            pass

    if not parsed:
        st.caption("Could not parse JSON values")
        return

    all_keys: set[str] = set()
    for obj in parsed:
        all_keys.update(obj.keys())

    for key in sorted(all_keys):
        values = []
        for obj in parsed:
            if key not in obj:
                continue
            val = obj[key]
            if isinstance(val, list):
                values.extend(str(x) for x in val)
            else:
                values.append(str(val))

        if not values:
            continue

        field_series = pd.Series(values)
        mode = _detect_mode(field_series)

        st.markdown(f"**{key}**")
        if mode == "boolean":
            _render_boolean(field_series)
        elif mode == "numeric":
            _render_numeric(field_series)
        elif mode == "few_unique":
            _render_few_unique(field_series, col=f"_json_{key}")
        elif mode == "categorical":
            _render_categorical(field_series, col=f"_json_{key}")
        elif mode == "generative":
            _render_generative(field_series)
        else:
            n_unique = field_series.nunique()
            st.caption(f"{n_unique} unique values")


# ── Anomaly flags ──────────────────────────────────────────────────────────────

def _render_anomaly_flags(series: pd.Series, mode: str) -> None:
    clean = _clean(series).astype(str).str.strip()
    if len(clean) == 0:
        return

    flags = []

    if mode in ("few_unique", "categorical", "boolean"):
        counts = Counter(clean)
        top_val, top_cnt = counts.most_common(1)[0]
        if top_cnt / len(clean) > 0.9:
            flags.append(f'"{top_val[:40]}" dominates — {top_cnt / len(clean) * 100:.0f}% of values')

    if mode == "generative":
        low_conf = clean[clean.str.lower().isin(["insufficient data", "insufficient_data", "n/a", "unknown"])]
        if len(low_conf) / len(clean) > 0.1:
            flags.append(f'{len(low_conf):,} rows with "insufficient data" ({len(low_conf)/len(clean)*100:.0f}%)')

    if mode not in ("scraped_text", "json", "numeric", "boolean"):
        lens = clean.str.len()
        median_len = lens.median()
        if median_len > 0:
            too_short = int((lens < max(5, median_len * 0.2)).sum())
            too_long = int((lens > median_len * 5).sum())
            if too_short / len(clean) > 0.05:
                flags.append(f"{too_short:,} suspiciously short answers")
            if too_long / len(clean) > 0.05:
                flags.append(f"{too_long:,} unusually long answers")

    for flag in flags:
        st.warning(flag)


# ── Main entry point ───────────────────────────────────────────────────────────

def render_col_stats(df: pd.DataFrame, col: str) -> None:
    try:
        _render_col_stats_inner(df, col)
    except Exception as e:
        st.error(f"Stats error: {e}")


def _render_col_stats_inner(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        st.caption("Column not found")
        return

    series = df[col]
    filled, total, cov_pct = _coverage(series)
    missing = total - filled
    clean = _clean(series)
    n_unique = clean.astype(str).str.strip().nunique() if len(clean) > 0 else 0
    mode = _detect_mode(series)

    # ── Header row ─────────────────────────────────────────────────────────────
    h1, h2, h3, h4 = st.columns(4)
    with h1:
        st.metric("coverage", f"{cov_pct:.0f}%", help=f"{filled:,} filled / {total:,} total")
    with h2:
        st.metric("missing", f"{missing:,}")
    with h3:
        st.metric("unique", f"{n_unique:,}")
    with h4:
        st.metric("type", mode.replace("_", " "))

    # ── Mode-specific stats ────────────────────────────────────────────────────
    if mode == "empty":
        st.caption("All values are empty")
        return
    elif mode == "boolean":
        _render_boolean(series)
    elif mode == "json":
        _render_json(series)
    elif mode == "numeric":
        _render_numeric(series)
    elif mode == "few_unique":
        _render_few_unique(series, col)
    elif mode == "categorical":
        _render_categorical(series, col)
    elif mode == "scraped_text":
        _render_scraped_text(series)
    elif mode == "generative":
        _render_generative(series)

    # ── Anomaly flags ──────────────────────────────────────────────────────────
    _render_anomaly_flags(series, mode)

    # ── Quick sample (toggle button — no nested expander) ─────────────────────
    sample_key = f"_sample_open_{col}"
    show_sample = st.session_state.get(sample_key, False)
    if st.button(
        "Hide sample" if show_sample else "5 random rows",
        key=f"_btn_sample_{col}",
        use_container_width=False,
    ):
        st.session_state[sample_key] = not show_sample
        st.rerun()

    if show_sample and len(clean) > 0:
        sample_idx = clean.sample(min(5, len(clean))).index
        input_cols = [c for c in df.columns if c != col][:3]
        show_cols = input_cols + [col]
        st.dataframe(
            df.loc[sample_idx, [c for c in show_cols if c in df.columns]],
            hide_index=True,
            use_container_width=True,
        )

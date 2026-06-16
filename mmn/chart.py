"""Dependency-free SVG charts for the simulator.

No matplotlib - we emit SVG text directly so it renders in any browser or on
GitHub with zero install. Two charts:

  * ownership_and_roi_svg(result): two stacked panels vs market-cap multiple
    (log x) - top = % ownership, bottom = ROI multiples (redeem & settlement).
  * mc_histogram_svg(mc_result): distribution of the Monte Carlo settlement
    multiple, with mean / median / break-even markers.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence

from .montecarlo import McResult
from .simulator import SimResult

_COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed"]
_W = 720  # panel width
_PH = 240  # panel height
_ML, _MR, _MT, _MB = 70, 120, 36, 48  # margins (left/right/top/bottom)


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 2.5, 5, 10):
        if step * mag >= raw:
            step *= mag
            break
    start = math.ceil(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 1e-9:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _esc(s) -> str:
    return html.escape(str(s))


def _line_panel(
    oy: int,
    title: str,
    x_vals: Sequence[float],
    series: list[tuple[str, Sequence[float], str]],  # (label, y values, units)
    x_label: str,
    y_label: str,
    *,
    x_log: bool = True,
) -> str:
    """One panel with origin y-offset ``oy``. Returns SVG fragment."""
    px0, px1 = _ML, _W - _MR
    py0, py1 = oy + _MT, oy + _PH - _MB

    xs = [math.log10(x) if x_log else x for x in x_vals]
    xmin, xmax = min(xs), max(xs)
    if xmax == xmin:
        xmax = xmin + 1.0
    all_y = [v for _, ys, _ in series for v in ys]
    ymin, ymax = min(all_y + [0.0]), max(all_y)
    if ymax == ymin:
        ymax = ymin + 1.0

    def sx(x):
        xv = math.log10(x) if x_log else x
        return px0 + (xv - xmin) / (xmax - xmin) * (px1 - px0)

    def sy(y):
        return py1 - (y - ymin) / (ymax - ymin) * (py1 - py0)

    out = [
        f'<text x="{_W / 2:.0f}" y="{oy + 20}" text-anchor="middle" '
        f'font-size="15" font-weight="600">{_esc(title)}</text>'
    ]

    # y gridlines + labels
    for t in _nice_ticks(ymin, ymax):
        y = sy(t)
        out.append(
            f'<line x1="{px0}" y1="{y:.1f}" x2="{px1}" y2="{y:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{px0 - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#374151">{t:g}</text>'
        )
    # x ticks (at the actual multiples)
    for xv in x_vals:
        x = sx(xv)
        out.append(
            f'<line x1="{x:.1f}" y1="{py1}" x2="{x:.1f}" y2="{py1 + 5}" '
            f'stroke="#9ca3af" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{py1 + 18}" text-anchor="middle" '
            f'font-size="10" fill="#374151">{xv:g}x</text>'
        )
    # axes
    out.append(f'<line x1="{px0}" y1="{py0}" x2="{px0}" y2="{py1}" stroke="#374151"/>')
    out.append(f'<line x1="{px0}" y1="{py1}" x2="{px1}" y2="{py1}" stroke="#374151"/>')
    out.append(
        f'<text x="{px0 - 46}" y="{(py0 + py1) / 2:.0f}" text-anchor="middle" '
        f'font-size="12" fill="#111827" transform="rotate(-90 {px0 - 46} '
        f'{(py0 + py1) / 2:.0f})">{_esc(y_label)}</text>'
    )
    out.append(
        f'<text x="{(px0 + px1) / 2:.0f}" y="{py1 + 38}" text-anchor="middle" '
        f'font-size="12" fill="#111827">{_esc(x_label)}</text>'
    )

    # series
    for idx, (label, ys, _units) in enumerate(series):
        color = _COLORS[idx % len(_COLORS)]
        pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(x_vals, ys, strict=False))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for x, y in zip(x_vals, ys, strict=False):
            out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" fill="{color}"/>')
        ly = py0 + 6 + idx * 18
        out.append(
            f'<line x1="{px1 + 12}" y1="{ly}" x2="{px1 + 30}" y2="{ly}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        out.append(
            f'<text x="{px1 + 34}" y="{ly + 4}" font-size="11" fill="#111827">{_esc(label)}</text>'
        )
    return "\n".join(out)


def _wrap(height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_W}" height="{height}" '
        f'viewBox="0 0 {_W} {height}" font-family="system-ui,Arial,sans-serif">'
        f'<rect width="{_W}" height="{height}" fill="white"/>{body}</svg>'
    )


def ownership_and_roi_svg(result: SimResult) -> str:
    """Two stacked panels: % ownership and ROI multiples vs market-cap multiple."""
    st = result.stages
    x = [s.multiple for s in st]
    own = [s.ownership_pct for s in st]
    redeem = [s.redeem_roi + 1.0 for s in st]
    settle = [s.settle_roi + 1.0 for s in st]

    p1 = _line_panel(
        0,
        "Your % ownership as market cap grows",
        x,
        [("ownership %", own, "%")],
        "market-cap multiple (log)",
        "ownership %",
    )
    p2 = _line_panel(
        _PH,
        "Return multiple as market cap grows",
        x,
        [("sell-back (redeem)", redeem, "x"), ("settlement win", settle, "x")],
        "market-cap multiple (log)",
        "value / spend  (x)",
    )
    return _wrap(2 * _PH, p1 + p2)


def mc_histogram_svg(mc: McResult, bins: int = 40) -> str:
    """Histogram of the Monte Carlo settlement multiple (value / spend)."""
    vals = sorted(mc.settle_mult)
    if not vals:
        return _wrap(_PH, "")
    lo, hi = vals[0], min(vals[-1], mc.p95_settle * 1.6 + 1e-9)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        b = min(int((v - lo) / width), bins - 1) if v <= hi else bins - 1
        counts[b] += 1
    cmax = max(counts) or 1

    px0, px1 = _ML, _W - _MR
    py0, py1 = _MT, _PH - _MB

    def sx(v):
        return px0 + (v - lo) / (hi - lo) * (px1 - px0)

    out = [
        f'<text x="{_W / 2:.0f}" y="20" text-anchor="middle" font-size="15" '
        f'font-weight="600">Monte Carlo: distribution of settlement return '
        f"({mc.config.n_trials:,} trials)</text>"
    ]
    for i, c in enumerate(counts):
        if c == 0:
            continue
        x = sx(lo + i * width)
        bw = (px1 - px0) / bins
        bh = (c / cmax) * (py1 - py0)
        out.append(
            f'<rect x="{x:.1f}" y="{py1 - bh:.1f}" width="{bw - 1:.1f}" '
            f'height="{bh:.1f}" fill="#93c5fd"/>'
        )
    out.append(f'<line x1="{px0}" y1="{py1}" x2="{px1}" y2="{py1}" stroke="#374151"/>')
    # markers
    for val, color, lab in [
        (1.0, "#374151", "break-even"),
        (mc.median_settle, "#059669", "median"),
        (mc.mean_settle, "#dc2626", "mean"),
    ]:
        if lo <= val <= hi:
            x = sx(val)
            out.append(
                f'<line x1="{x:.1f}" y1="{py0}" x2="{x:.1f}" y2="{py1}" '
                f'stroke="{color}" stroke-width="1.5" stroke-dasharray="4 3"/>'
            )
            out.append(
                f'<text x="{x:.1f}" y="{py0 - 2}" text-anchor="middle" '
                f'font-size="10" fill="{color}">{_esc(lab)} {val:.2f}x</text>'
            )
    for t in _nice_ticks(lo, hi):
        x = sx(t)
        out.append(
            f'<text x="{x:.1f}" y="{py1 + 16}" text-anchor="middle" '
            f'font-size="10" fill="#374151">{t:g}x</text>'
        )
    out.append(
        f'<text x="{(px0 + px1) / 2:.0f}" y="{py1 + 34}" text-anchor="middle" '
        f'font-size="12">settlement payout / total spend</text>'
    )
    return _wrap(_PH, "\n".join(out))

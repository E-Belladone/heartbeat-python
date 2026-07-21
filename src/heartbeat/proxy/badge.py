"""Render the aggregate presence as embeddable flat SVG badges.

Shields-style badges (the CI/CD look) served at /api/badge/{metric}.svg so
the public presence can drop into a README, a personal site, or a forum
signature as a live `<img>`.

Pure: `PublicPresence` in, SVG string out. The data is exactly what
`/api/presence` already exposes, so this opens no new privacy surface
(invariant #1): only counts and ages, never a device, name, or id.
"""

from collections.abc import Callable

from heartbeat.models import PublicPresence

__all__ = ["BADGE_METRICS", "render_badge", "render_error"]

# rose-pine (dark). Label side stays dark with light text; the message side
# is coloured per state, with dark text on the light accents for contrast.
_LABEL_BG = "#26233a"  # overlay
_LIGHT = "#e0def4"  # text
_DARK = "#191724"  # base
_MUTED = "#6e6a86"
_FOAM = "#9ccfd8"
_GOLD = "#f6c177"
_LOVE = "#eb6f92"
_IRIS = "#c4a7e7"

# crude but clip-free text metric: 11px Verdana averages well under 7px/char,
# so this over-reserves slightly rather than truncating.
_CHAR_PX = 7
_PAD_PX = 12


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _svg(label: str, message: str, msg_bg: str, msg_fg: str) -> str:
    lw = len(label) * _CHAR_PX + _PAD_PX
    mw = len(message) * _CHAR_PX + _PAD_PX
    w = lw + mw
    label, message = _esc(label), _esc(message)
    aria = f"{label}: {message}"
    lx, mx = lw / 2, lw + mw / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" '
        f'role="img" aria-label="{aria}">'
        f"<title>{aria}</title>"
        '<linearGradient id="s" x2="0" y2="100%">'
        '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>'
        '<g clip-path="url(#r)">'
        f'<rect width="{lw}" height="20" fill="{_LABEL_BG}"/>'
        f'<rect x="{lw}" width="{mw}" height="20" fill="{msg_bg}"/>'
        f'<rect width="{w}" height="20" fill="url(#s)"/></g>'
        '<g text-anchor="middle" font-family="Verdana,DejaVu Sans,Geneva,sans-serif" '
        'font-size="11">'
        f'<text x="{lx}" y="15" fill="#010101" fill-opacity=".3">{label}</text>'
        f'<text x="{lx}" y="14" fill="{_LIGHT}">{label}</text>'
        f'<text x="{mx}" y="15" fill="#010101" fill-opacity=".3">{message}</text>'
        f'<text x="{mx}" y="14" fill="{msg_fg}">{message}</text>'
        "</g></svg>"
    )


def _ago(seconds: int) -> str:
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def _count(n: int) -> str:
    if n < 1000:
        return str(n)
    unit, scale = ("k", 1000) if n < 1_000_000 else ("M", 1_000_000)
    return f"{n / scale:.1f}".rstrip("0").rstrip(".") + unit


def _status(p: PublicPresence) -> tuple[str, str, str]:
    if not p.online:
        return "offline", _LOVE, _DARK
    fg = _LIGHT if p.activity == "away" else _DARK
    bg = {"active": _FOAM, "around": _GOLD, "away": _MUTED}[p.activity]
    return p.activity, bg, fg


def _last_seen(p: PublicPresence) -> tuple[str, str, str]:
    msg = "never" if p.last_seen is None else _ago(p.last_seen_relative)
    return msg, _IRIS, _DARK


def _beats(p: PublicPresence) -> tuple[str, str, str]:
    return _count(p.total_beats), _IRIS, _DARK


# metric name -> (label, message-builder). The label is fixed so a badge can
# still render ("unavailable") when the snapshot can't be read.
_METRICS: dict[str, tuple[str, Callable[[PublicPresence], tuple[str, str, str]]]] = {
    "status": ("presence", _status),
    "last-seen": ("last seen", _last_seen),
    "beats": ("beats", _beats),
}

BADGE_METRICS = frozenset(_METRICS)


def render_badge(metric: str, presence: PublicPresence) -> str:
    """SVG for a known metric. Caller guarantees `metric in BADGE_METRICS`."""
    label, build = _METRICS[metric]
    message, bg, fg = build(presence)
    return _svg(label, message, bg, fg)


def render_error(metric: str) -> str:
    """Muted 'unavailable' badge for when the snapshot read failed; the embed
    is decorative, so it degrades instead of breaking the image."""
    label, _ = _METRICS[metric]
    return _svg(label, "unavailable", _MUTED, _LIGHT)

"""Pure badge rendering: aggregate presence in, flat SVG out."""

from heartbeat.models import PublicPresence
from heartbeat.proxy import badge


def presence(**overrides: object) -> PublicPresence:
    base: dict[str, object] = {
        "online": True,
        "activity": "around",
        "last_seen": 1_800_000_000,
        "last_seen_relative": 42,
        "longest_absence": 86_400,
        "total_beats": 99_999,
        "device_count": 3,
        "total_strong_signals": 12,
        "last_strong_signal": 1_800_000_000,
        "last_strong_signal_relative": 42,
        "uptime": 3600,
    }
    return PublicPresence.model_validate(base | overrides)


def test_every_metric_renders_wellformed_svg() -> None:
    for metric in badge.BADGE_METRICS:
        svg = badge.render_badge(metric, presence())
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_status_reflects_online_and_tier() -> None:
    assert "active" in badge.render_badge("status", presence(activity="active"))
    assert "around" in badge.render_badge("status", presence(activity="around"))
    assert "offline" in badge.render_badge("status", presence(online=False))


def test_last_seen_is_humanised() -> None:
    assert "just now" in badge.render_badge("last-seen", presence(last_seen_relative=5))
    assert "9m ago" in badge.render_badge("last-seen", presence(last_seen_relative=9 * 60))
    assert "3h ago" in badge.render_badge("last-seen", presence(last_seen_relative=3 * 3600))
    assert "2d ago" in badge.render_badge("last-seen", presence(last_seen_relative=2 * 86_400))
    assert "never" in badge.render_badge("last-seen", presence(last_seen=None))


def test_beats_count_is_humanised() -> None:
    assert ">999<" in badge.render_badge("beats", presence(total_beats=999))
    assert "1.2k" in badge.render_badge("beats", presence(total_beats=1234))
    assert "12k" in badge.render_badge("beats", presence(total_beats=12_000))
    assert "3.5M" in badge.render_badge("beats", presence(total_beats=3_500_000))


def test_error_badge_is_wellformed_and_muted() -> None:
    svg = badge.render_error("beats")
    assert svg.startswith("<svg")
    assert "unavailable" in svg


def test_untrusted_text_would_be_escaped() -> None:
    # metric messages are all internal today, but the escaper must hold if that
    # ever changes, so the SVG can't be broken by a stray angle bracket
    assert "&lt;" in badge._svg("x", "<b>", badge._IRIS, badge._DARK)

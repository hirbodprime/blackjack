"""Pure rendering of a horse-race frame for Telegram (HTML)."""

from html import escape

TRACK_CELLS = 14
PLACES = ("🥇", "🥈", "🥉")


def _label(name: str, limit: int = 18) -> str:
    name = " ".join(name.split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def render_frame(
    *,
    race_id: int,
    tick: int,
    horses: list[int],
    positions: dict[int, int],
    distance: int,
    names: dict[int, str],
    emojis: dict[int, str],
    spells: dict[int, list[str]],
    broken: set[int],
    events: list[str],
    pot: int,
    winner: int | None = None,
    dealer_horse: int = 1,
) -> str:
    """Leader first; each row shows place, progress track, and the horse."""
    order = sorted(horses, key=lambda h: (h in broken, positions[h], h))
    header = "🏆 PHOTO FINISH" if winner is not None else f"🏇 RACE #{race_id} · LAP {tick}"
    lines = [f"<b>{header}</b>", f"💰 Pot {pot:,} · {distance} furlongs", "━━━━━━━━━━━━━━━"]
    for place, horse in enumerate(order, start=1):
        done = distance - positions[horse]
        filled = min(TRACK_CELLS, max(0, done * TRACK_CELLS // distance))
        runner = "💥" if horse in broken else emojis.get(horse) or "🐎"
        if positions[horse] == 0 and horse not in broken:
            track = "▰" * TRACK_CELLS + "🏁"
        else:
            track = "▰" * filled + runner + "▱" * (TRACK_CELLS - filled)
        if horse == winner:
            badge = "👑"
        elif horse in broken:
            badge = "🚫"
        else:
            badge = PLACES[place - 1] if place <= len(PLACES) else f"{place}."
        tag = " 🎩" if horse == dealer_horse else ""
        spell = f" {spells[horse][0].split(' ')[0]}" if spells.get(horse) else ""
        lines.append(f"{badge} {track}")
        lines.append(f"     <b>#{horse}</b> {escape(_label(names[horse]))}{tag}{spell}")
    if events:
        lines.append("━━━━━━━━━━━━━━━")
        lines.extend(f"<i>{escape(event)}</i>" for event in events[-3:])
    return "\n".join(lines)

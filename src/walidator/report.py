"""Self-contained HTML report (inline CSS and SVG, no external files), printable to PDF."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

from walidator import APP_NAME, __version__
from walidator.errors import OutputError
from walidator.model import ColumnRule, ColumnType
from walidator.results import ColumnStats, RunResult
from walidator.validators import format_value

MAX_PROBLEM_ROWS = 500
MAX_NEAR_DUPLICATE_GROUPS = 30


def write_report(result: RunResult, path: Path) -> None:
    try:
        path.write_text(render_report(result), encoding="utf-8")
    except PermissionError as error:
        raise OutputError(
            f"Nie można zapisać raportu {path.name} – plik jest zablokowany."
        ) from error


def render_report(result: RunResult) -> str:
    sections = [
        _header(result),
        _summary(result),
        _composition(result),
        _charts_row(result),
        _column_table(result.columns),
        _fix_examples(result.columns),
        _problems(result),
        _near_duplicates(result),
        _footer(result),
    ]
    title = f"Raport walidacji – {result.source.path.name}"
    return (
        '<!doctype html>\n<html lang="pl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(section for section in sections if section)
        + "\n</main>\n</body>\n</html>\n"
    )


# --- formatting helpers ----------------------------------------------------------------------


def num(value: int) -> str:
    """Polish thousands grouping with a non-breaking space: 100000 -> "100 000"."""
    return f"{value:,}".replace(",", "\u00a0")


def pct(part: int, whole: int, digits: int = 1) -> str:
    share = part / whole * 100 if whole else 0.0
    return f"{share:.{digits}f}".replace(".", ",") + "\u00a0%"


def seconds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + "\u00a0s"


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Polish plural forms: 1 wiersz, 2 wiersze, 5 wierszy, 22 wiersze."""
    if count == 1:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def _shown(value: object) -> str:
    if isinstance(value, Decimal):
        return num(int(value)) if value == value.to_integral_value() else format_value(value)
    if isinstance(value, int):
        return num(value)
    if isinstance(value, date):
        return value.isoformat()
    return escape(str(value))


# --- sections --------------------------------------------------------------------------------


def _header(result: RunResult) -> str:
    info = result.source
    accepted = result.accepted / result.total if result.total else 1.0
    meta = [
        ("Format", info.description),
        ("Sprawdzono", result.started_at.strftime("%d.%m.%Y, %H:%M")),
        ("Reguły", result.rules_source or "wykryte automatycznie"),
        ("Czas", f"{seconds(result.elapsed)} · {num(round(result.rows_per_second))} wierszy/s"),
    ]
    meta_html = "".join(f"<div><dt>{escape(k)}</dt><dd>{escape(v)}</dd></div>" for k, v in meta)
    return f"""
<header class="top">
  <div class="title">
    <p class="eyebrow">{APP_NAME} · raport walidacji</p>
    <h1>{escape(info.path.name)}</h1>
    <dl class="meta">{meta_html}</dl>
  </div>
  <div class="score" role="img" aria-label="Przyjęto {pct(result.accepted, result.total)} wierszy">
    {_ring(accepted)}
    <div><strong>{pct(result.accepted, result.total)}</strong><span>wierszy przyjętych</span></div>
  </div>
</header>"""


def _ring(share: float) -> str:
    radius, stroke = 38, 10
    circumference = 2 * 3.14159265 * radius
    filled = circumference * max(0.0, min(share, 1.0))
    color = "var(--ok)" if share >= 0.95 else "var(--warn)" if share >= 0.8 else "var(--bad)"
    return (
        f'<svg viewBox="0 0 100 100" width="92" height="92" aria-hidden="true">'
        f'<circle cx="50" cy="50" r="{radius}" fill="none" stroke="var(--track)" '
        f'stroke-width="{stroke}"/>'
        f'<circle cx="50" cy="50" r="{radius}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-dasharray="{filled:.1f} {circumference:.1f}" '
        f'transform="rotate(-90 50 50)"/></svg>'
    )


def _summary(result: RunResult) -> str:
    cards = [
        ("Wiersze", num(result.total), "w pliku (bez nagłówka)", "neutral"),
        (
            "Poprawne",
            num(result.unchanged),
            pct(result.unchanged, result.total) + " bez zmian",
            "ok",
        ),
        (
            "Poprawione",
            num(result.fixed),
            pct(result.fixed, result.total) + " wyczyszczonych",
            "fix",
        ),
        (
            "Odrzucone",
            num(result.rejected),
            f"w tym {num(result.duplicates)} "
            + _plural(result.duplicates, "duplikat", "duplikaty", "duplikatów"),
            "bad",
        ),
        ("Problemy", num(result.problems_total), "błędnych komórek i wierszy", "warn"),
    ]
    items = "".join(
        f'<div class="card {tone}"><span class="label">{label}</span>'
        f'<span class="value">{value}</span><span class="hint">{escape(hint)}</span></div>'
        for label, value, hint, tone in cards
    )
    return f'<section class="cards" aria-label="Podsumowanie">{items}</section>'


def _composition(result: RunResult) -> str:
    total = result.total or 1
    parts = [
        ("Poprawne", result.unchanged, "ok"),
        ("Poprawione", result.fixed, "fix"),
        ("Odrzucone (błędy)", result.rejected - result.duplicates, "bad"),
        ("Duplikaty", result.duplicates, "dup"),
    ]
    bar = "".join(
        f'<span class="seg {tone}" style="width:{count / total * 100:.3f}%" '
        f'title="{label}: {num(count)}"></span>'
        for label, count, tone in parts
        if count
    )
    legend = "".join(
        f'<li><i class="dot {tone}"></i>{label} <b>{num(count)}</b> '
        f"<span>{pct(count, total)}</span></li>"
        for label, count, tone in parts
    )
    return f"""
<section class="panel">
  <h2>Struktura wierszy</h2>
  <div class="stack" role="img"
       aria-label="Udział wierszy poprawnych, poprawionych i odrzuconych">{bar}</div>
  <ul class="legend">{legend}</ul>
</section>"""


def _charts_row(result: RunResult) -> str:
    return f"""
<div class="grid2">
  <section class="panel">
    <h2>Rodzaje błędów</h2>
    {_error_chart(result)}
  </section>
  <section class="panel">
    <h2>Duplikaty i uwagi</h2>
    {_notes(result)}
  </section>
</div>"""


def _error_chart(result: RunResult) -> str:
    items = result.categories.most_common(14)
    if not items:
        return '<p class="empty">Brak błędów – wszystkie wiersze spełniają reguły.</p>'
    row_height, label_width, bar_width, top = 34, 200, 250, 4
    largest = items[0][1]
    height = top + row_height * len(items)
    rows = []
    for index, (category, count) in enumerate(items):
        y = top + index * row_height
        width = max(bar_width * count / largest, 2)
        rows.append(
            f'<text x="0" y="{y + 19}" class="axis">{escape(category)}</text>'
            f'<rect x="{label_width}" y="{y + 6}" width="{bar_width}" height="18" rx="4" '
            f'class="track"/>'
            f'<rect x="{label_width}" y="{y + 6}" width="{width:.1f}" height="18" rx="4" '
            f'class="bar"><title>{escape(category)}: {count}</title></rect>'
            f'<text x="{label_width + bar_width + 10}" y="{y + 19}" class="count">'
            f"{num(count)}</text>"
        )
    return (
        f'<svg class="chart" viewBox="0 0 {label_width + bar_width + 60} {height}" '
        f'role="img" aria-label="Liczba błędów według rodzaju">{"".join(rows)}</svg>'
    )


def _notes(result: RunResult) -> str:
    facts = [
        (
            "Usunięte duplikaty wierszy",
            num(result.duplicates),
            "identyczne po oczyszczeniu, zostawiono pierwszy",
        ),
        (
            "Podobne rekordy",
            num(result.near_duplicate_rows),
            f"wg kolumny „{result.similarity_key}”"
            if result.similarity_key
            else "nie wybrano klucza",
        ),
        (
            "Poprawione komórki",
            num(sum(column.fixed for column in result.columns)),
            f"w {num(sum(1 for column in result.columns if column.fixed))} z "
            f"{num(len(result.columns))} kolumn",
        ),
        (
            "Wiersze z błędami",
            num(result.rejected - result.duplicates),
            "zapisane z powodami w pliku odrzuconych",
        ),
    ]
    html = "".join(
        f'<div class="fact"><b>{value}</b><span>{escape(label)}</span>'
        f"<small>{escape(hint)}</small></div>"
        for label, value, hint in facts
    )
    if result.warnings:
        warnings = "".join(f"<li>{escape(warning)}</li>" for warning in result.warnings)
        html += f'<div class="warnings"><h3>Ostrzeżenia</h3><ul>{warnings}</ul></div>'
    return f'<div class="facts">{html}</div>'


def _rule_badges(rule: ColumnRule) -> str:
    badges = []
    if rule.required:
        badges.append("wymagane")
    if rule.unique:
        badges.append("unikalne")
    if rule.minimum is not None or rule.maximum is not None:
        badges.append(_range_badge(rule))
    if rule.allowed:
        badges.append(f"lista ({len(rule.allowed)})")
    return "".join(f'<span class="badge">{badge}</span>' for badge in badges)


def _range_badge(rule: ColumnRule) -> str:
    unit = " zn." if rule.type is ColumnType.TEXT else ""
    low, high = rule.minimum, rule.maximum
    if low is not None and high is not None:
        return f"{_shown(low)}–{_shown(high)}{unit}"
    if low is not None:
        return f"min. {_shown(low)}{unit}"
    return f"maks. {_shown(high)}{unit}"


def _column_table(columns: list[ColumnStats]) -> str:
    rows = []
    for stats in columns:
        cells = stats.filled + stats.empty
        quality = stats.valid_share
        tone = "ok" if quality >= 0.98 else "warn" if quality >= 0.9 else "bad"
        value_range = (
            f"{_shown(stats.minimum)} – {_shown(stats.maximum)}"
            if stats.minimum is not None
            else ""
        )
        distinct = num(stats.distinct) + ("+" if stats.distinct_overflow else "")
        rows.append(
            f'<tr><th scope="row">{escape(stats.name)}<div>{_rule_badges(stats.rule)}</div></th>'
            f"<td>{stats.rule.type.label}</td>"
            f'<td><div class="fill"><span style="width:{stats.filled / (cells or 1) * 100:.1f}%">'
            f"</span></div><small>{pct(stats.filled, cells, 0)}</small></td>"
            f'<td class="n">{num(stats.fixed)}</td>'
            f'<td class="n">{num(stats.invalid)}</td>'
            f'<td class="n">{distinct}</td>'
            f'<td class="range">{value_range}</td>'
            f'<td><span class="pill {tone}">{pct(stats.filled - stats.invalid, stats.filled or 1)}'
            f"</span></td></tr>"
        )
    return f"""
<section class="panel">
  <h2>Statystyki kolumn</h2>
  <div class="scroll"><table class="columns">
    <thead><tr><th scope="col">Kolumna i reguły</th><th scope="col">Typ</th>
    <th scope="col">Wypełnienie</th><th scope="col" class="n">Poprawione</th>
    <th scope="col" class="n">Błędne</th><th scope="col" class="n">Unikalne wartości</th>
    <th scope="col">Zakres w danych</th><th scope="col">Poprawność</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
</section>"""


def _fix_examples(columns: list[ColumnStats]) -> str:
    groups = []
    for stats in columns:
        if not stats.fix_examples:
            continue
        examples = "".join(
            f'<li><code class="before">{_cell(before)}</code><span class="arrow">→</span>'
            f'<code class="after">{_cell(after)}</code></li>'
            for before, after in stats.fix_examples
        )
        groups.append(
            f'<div class="fixes"><h3>{escape(stats.name)} <span>{num(stats.fixed)} '
            f"{_plural(stats.fixed, 'poprawka', 'poprawki', 'poprawek')}</span></h3>"
            f"<ul>{examples}</ul></div>"
        )
    if not groups:
        return ""
    return f"""
<section class="panel">
  <h2>Przykłady poprawek <small>przed → po</small></h2>
  <div class="fix-grid">{"".join(groups)}</div>
</section>"""


def _cell(value: str) -> str:
    if value == "":
        return '<em class="blank">(puste)</em>'
    return escape(value).replace(" ", "·") if value != value.strip() else escape(value)


def _problems(result: RunResult) -> str:
    if not result.problems:
        return ""
    rows = "".join(
        f'<tr><td class="n">{problem.row}</td><td>{escape(problem.column)}</td>'
        f"<td><code>{_cell(problem.value)}</code></td>"
        f'<td><span class="tag">{escape(problem.category)}</span> '
        f"{escape(problem.reason)}</td></tr>"
        for problem in result.problems[:MAX_PROBLEM_ROWS]
    )
    shown = min(len(result.problems), MAX_PROBLEM_ROWS)
    note = (
        f'<p class="note">Pokazano {num(shown)} z {num(result.problems_total)} problemów. Pełna '
        f"lista jest w pliku <b>{escape(result.outputs.rejected.name)}</b>.</p>"
        if result.problems_total > shown
        else ""
    )
    return f"""
<section class="panel problems">
  <h2>Problemy <small>{num(result.problems_total)}</small></h2>
  {note}
  <div class="scroll"><table>
    <thead><tr><th scope="col" class="n">Wiersz</th><th scope="col">Kolumna</th>
    <th scope="col">Wartość</th><th scope="col">Powód</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</section>"""


def _near_duplicates(result: RunResult) -> str:
    if not result.near_duplicates:
        return ""
    groups = "".join(
        '<li><ul class="variants">'
        + "".join(
            f'<li><span class="row">wiersz {number}</span>{escape(text)}</li>'
            for number, text in group.rows[:6]
        )
        + "</ul></li>"
        for group in result.near_duplicates[:MAX_NEAR_DUPLICATE_GROUPS]
    )
    return f"""
<section class="panel">
  <h2>Podobne rekordy <small>kolumna „{escape(result.similarity_key or "")}”</small></h2>
  <p class="note">Te wiersze przeszły walidację, ale mają prawie taką samą wartość klucza (bez
  wielkości liter, polskich znaków i formy prawnej). Warto sprawdzić, czy to ten sam klient.</p>
  <ol class="near">{groups}</ol>
</section>"""


def _footer(result: RunResult) -> str:
    outputs = [result.outputs.clean, result.outputs.rejected]
    files = "".join(f"<li>{escape(path.name)}</li>" for path in outputs)
    return f"""
<footer>
  <div><b>Pliki wynikowe</b><ul>{files}</ul></div>
  <div class="by">{APP_NAME} {__version__} · {result.started_at.strftime("%d.%m.%Y %H:%M")}</div>
</footer>"""


CSS = """
:root{--bg:#f4f6fa;--surface:#fff;--ink:#141a26;--muted:#5d6878;--line:#e3e7ee;--track:#edf0f5;
--accent:#3a5bd9;--ok:#1f9d63;--fix:#3a6fd9;--bad:#d64550;--dup:#c58a19;--warn:#c58a19;
--bar:#d64550;--radius:14px;
font-family:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
color:var(--ink);background:var(--bg)}*{box-sizing:border-box}body{margin:0;background:var(--bg);
font-size:14px;line-height:1.5}main{max-width:1180px;margin:0 auto;padding:36px 28px 48px}
h1{font-size:30px;line-height:1.15;margin:4px 0 14px;letter-spacing:-.01em}h2{font-size:16px;
margin:0 0 16px;letter-spacing:.01em}h2 small{color:var(--muted);font-weight:500;margin-left:6px}
h3{font-size:14px;margin:0 0 8px}.top{display:flex;justify-content:space-between;gap:24px;
align-items:center;background:var(--surface);border:1px solid var(--line);
border-radius:var(--radius);padding:26px 30px;margin-bottom:18px;
box-shadow:0 1px 2px rgba(16,24,40,.04)}.eyebrow{margin:0;color:var(--accent);font-weight:600;
font-size:12px;text-transform:uppercase;letter-spacing:.08em}.meta{display:flex;flex-wrap:wrap;
gap:8px 28px;margin:0}.meta div{min-width:0}.meta dt{font-size:11px;text-transform:uppercase;
letter-spacing:.06em;color:var(--muted)}.meta dd{margin:0;font-weight:500}.score{display:flex;
align-items:center;gap:14px;flex-shrink:0}.score strong{display:block;font-size:26px;
line-height:1.1}.score span{color:var(--muted);font-size:13px}.cards{display:grid;
grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:18px}.card{background:var(--surface);
border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;display:flex;
flex-direction:column;gap:2px;border-top:4px solid var(--line)}.card .label{font-size:12px;
color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.card .value{font-size:28px;font-weight:650;letter-spacing:-.01em;
font-variant-numeric:tabular-nums}.card .hint{font-size:12.5px;color:var(--muted)}
.card.ok{border-top-color:var(--ok)}.card.fix{border-top-color:var(--fix)}
.card.bad{border-top-color:var(--bad)}.card.warn{border-top-color:var(--warn)}
.card.neutral{border-top-color:#9aa4b2}.panel{background:var(--surface);
border:1px solid var(--line);border-radius:var(--radius);padding:22px 24px;margin-bottom:18px;
box-shadow:0 1px 2px rgba(16,24,40,.04)}.stack{display:flex;height:18px;border-radius:9px;
overflow:hidden;background:var(--track);gap:2px}.seg.ok,.dot.ok{background:var(--ok)}
.seg.fix,.dot.fix{background:var(--fix)}.seg.bad,.dot.bad{background:var(--bad)}
.seg.dup,.dot.dup{background:var(--dup)}.legend{display:flex;flex-wrap:wrap;gap:10px 26px;
list-style:none;padding:0;margin:14px 0 0}.legend li{display:flex;align-items:center;gap:7px}
.legend span{color:var(--muted)}.dot{width:10px;height:10px;border-radius:3px;
display:inline-block}.grid2{display:grid;grid-template-columns:1.25fr 1fr;gap:18px}
.grid2 .panel{margin-bottom:18px}.chart{width:100%;height:auto;display:block}
.chart .axis{font-size:13px;fill:var(--ink)}.chart .count{font-size:13px;font-weight:600;
fill:var(--ink)}.chart .bar{fill:var(--bar)}.chart .track{fill:var(--track)}.facts{display:grid;
gap:12px}.fact{display:grid;grid-template-columns:76px 1fr;column-gap:12px;align-items:baseline;
padding-bottom:12px;border-bottom:1px solid var(--line)}.fact b{font-size:24px;grid-row:span 2;
font-variant-numeric:tabular-nums}.fact span{font-weight:600}.fact small{color:var(--muted)}
.warnings h3{color:var(--warn);margin-top:4px}.warnings ul{margin:0;padding-left:18px;
color:var(--muted)}.empty{color:var(--muted)}.scroll{overflow-x:auto}table{width:100%;
border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:9px 10px;
border-bottom:1px solid var(--line);vertical-align:top}thead th{font-size:11.5px;
text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600;
background:#f8f9fc;border-bottom:1px solid var(--line)}
tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}.n{text-align:right;
white-space:nowrap}.columns tbody th{font-weight:600}.columns td{white-space:nowrap}
.columns tbody th div{margin-top:3px;
display:flex;flex-wrap:wrap;gap:4px}.badge{font-size:11px;font-weight:500;color:#40506a;
background:#eef2f8;border-radius:6px;padding:1px 7px}.fill{width:110px;height:7px;
border-radius:4px;background:var(--track);overflow:hidden;margin-top:7px;display:inline-block;
vertical-align:middle}.fill span{display:block;height:100%;background:var(--accent)}
td small{margin-left:8px;color:var(--muted)}.range{color:var(--muted);white-space:nowrap}
.pill{display:inline-block;font-weight:600;font-size:12.5px;border-radius:999px;padding:2px 10px;
white-space:nowrap}.pill.ok{background:#e3f5ec;color:#167a4c}.pill.warn{background:#fbf0d9;
color:#8a5d09}.pill.bad{background:#fde6e7;color:#ab2a34}.fix-grid{display:grid;
grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:14px}
.fixes{border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.fixes h3 span{color:var(--muted);font-weight:500;margin-left:4px;font-size:12.5px}
.fixes ul{list-style:none;margin:0;padding:0;display:grid;gap:7px}.fixes li{display:grid;
grid-template-columns:minmax(0,1fr) 18px minmax(0,1fr);align-items:center;gap:6px}
code{font-family:"Cascadia Mono",Consolas,monospace;font-size:12.5px;border-radius:6px;
padding:2px 7px;overflow-wrap:anywhere}.before{background:#fdeeee;color:#9b2c33}
.after{background:#e7f6ee;color:#16683f}.arrow{color:var(--muted);text-align:center}
.blank{color:var(--muted);font-style:italic}.problems td code{background:#f3f5f9}
.tag{display:inline-block;font-size:11px;font-weight:600;color:#ab2a34;background:#fde6e7;
border-radius:6px;padding:1px 7px;margin-right:6px}.note{color:var(--muted);margin:-6px 0 14px}
.near{margin:0;padding-left:22px;display:grid;gap:10px}.variants{list-style:none;padding:0;
margin:0;display:flex;flex-wrap:wrap;gap:6px 18px}.variants .row{color:var(--muted);
font-size:12px;margin-right:6px}footer{display:flex;justify-content:space-between;
align-items:flex-end;gap:20px;color:var(--muted);font-size:12.5px;padding:6px 4px}
footer ul{margin:4px 0 0;padding-left:18px}
@media (max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}
.grid2{grid-template-columns:1fr}.top{flex-direction:column;align-items:flex-start}
main{padding:20px 16px}}@media print{@page{size:A4;margin:12mm}:root,body{background:#fff}
main{max-width:none;padding:0}.panel,.top,.card{box-shadow:none;break-inside:avoid}
.problems,.columns{break-inside:auto}tr{break-inside:avoid}.scroll{overflow:visible}
.cards{grid-template-columns:repeat(5,1fr);gap:8px}.card .value{font-size:22px}
.grid2{grid-template-columns:1.25fr 1fr}*{-webkit-print-color-adjust:exact;
print-color-adjust:exact}}
"""

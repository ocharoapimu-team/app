#!/usr/bin/env python3
"""
build_site.py — El Niño Climate Knowledge Wiki → single-file microsite
styled on the OCHA Products Design System (UN Blue #009EDB, Roboto /
Roboto Condensed, hairline rules, square corners, OCHA Humanitarian Icons).

Usage:
    python build_site.py --wiki "<path to Climate_Knowledge_Wiki>" --out "<output folder>"

Reads   wiki/themes.md, wiki/index.md, wiki/log.md, wiki/notes/*.md
Writes  <out>/index.html   (self-contained: all notes, search, icons, logo inline)

Requires: Python 3.8+ and the `markdown` package (pip install markdown).
Assets (OCHA icons + logo) are read from the `assets/` folder next to this script.
"""
import argparse
import datetime as dt
import html
import json
import re
from collections import OrderedDict, defaultdict
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets" if (HERE / "assets").exists() else HERE.parent / "assets"

MD_EXT = ["tables", "sane_lists"]

# ---------------------------------------------------------------------------
# Theme → OCHA Humanitarian Icon (file stem in assets/icons)
# ---------------------------------------------------------------------------
THEME_ICONS = {
    "ENSO, Signals & Forecasts": "Trending",
    "Early Warning Systems": "Alert",
    "Drought": "Drought",
    "Floods & Storms": "Flood",
    "Heat": "Heatwave",
    "Food Security & Livelihoods": "Food-Security",
    "Populations & Vulnerability": "People-affected",
    "Economic Impacts": "Trade-and-market",
    "Health Impacts": "Health",
    "Anticipatory Action": "Anticipatory-action",
    "Emergency Response": "Response",
    "Methods": "Analysis",
}
UI_ICONS = ["Search", "Report", "Data", "Document", "Link", "Calendar", "Filter",
            "Table", "Monitoring", "Chart", "Bookmark", "Information-management",
            "Expand-right", "Expand-down", "Exit-Cancel", "Go", "Up", "Fire",
            "Financing", "Storm", "Water-source", "Nutrition", "Country", "Map",
            "Coordination", "Preparedness", "Menu", "Previous-item", "Next-item",
            "Flood", "Cyclone", "Storm-surge", "Drought", "Epidemic", "Health", "People-affected",
            "Trending", "Alert", "Food-Security"]

TAG_FAMILIES = OrderedDict([
    ("Signal-to-action chain", ["signal", "forecast", "hazard", "disaster", "exposure",
                                "vulnerability", "impact", "action"]),
    ("ENSO phase", ["el-nino", "la-nina", "neutral"]),
    ("Hazard type", ["drought", "flood", "cyclone", "wildfire", "heatwave", "landslide",
                     "storm", "frost", "haze", "volcano", "earthquake", "tsunami",
                     "cold-wave", "storm-surge", "fire"]),
    ("Sector", ["food-security", "water", "health", "displacement", "agriculture",
                "education", "protection", "nutrition", "energy", "wash", "shelter",
                "livelihoods", "fisheries", "gbv", "early-warning", "anticipatory-action",
                "emergency-response", "economic", "trade", "shipping", "remittances",
                "governance", "climate-change"]),
    ("Impact type", ["inflation", "food-price", "economic-loss", "gdp"]),
    ("Kind", ["method"]),
])


def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def md_html(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXT)


def md_inline(text: str) -> str:
    out = md_html(text).strip()
    if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        out = out[3:-4]
    return out


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Link post-processing
# ---------------------------------------------------------------------------
def rewrite_links(h: str, known: set, from_index=False) -> str:
    def repl(m):
        slug = m.group(1)
        cls = "wl" if slug in known else "wl missing"
        return f'href="#/note/{slug}" class="{cls}"'
    if from_index:
        h = re.sub(r'href="notes/([a-z0-9][a-z0-9\-]*)\.md"', repl, h)
    h = re.sub(r'href="([a-z0-9][a-z0-9\-]*)\.md"', repl, h)
    # external links open in a new tab
    h = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', h)
    # raw/ artefact identifiers
    h = re.sub(r"<code>(raw/[^<]+)</code>", r'<code class="raw">\1</code>', h)
    return h


def add_heading_ids(h: str, prefix: str):
    toc = []
    used = set()

    def repl(m):
        level, inner = m.group(1), m.group(2)
        text = strip_tags(inner)
        base = slugify(text)[:60] or "section"
        hid = base
        n = 2
        while hid in used:
            hid = f"{base}-{n}"
            n += 1
        used.add(hid)
        toc.append({"level": int(level), "id": hid, "text": text})
        return f'<h{level} id="{hid}">{inner}</h{level}>'

    h = re.sub(r"<h([23])>(.*?)</h\1>", repl, h, flags=re.S)
    return h, toc


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
SRC_RE = re.compile(
    r"^- \[(?P<key>[^\]]+)\]\((?P<url>[^)\s]+)\)\s*[—–-]\s*(?P<attr>.*?)(?:\s*·\s*`(?P<raw>raw/[^`]+)`)?\s*$"
)
REL_RE = re.compile(r"^\|\s*\[(?P<label>[^\]]+)\]\((?P<slug>[a-z0-9\-]+)\.md\)\s*\|\s*(?P<desc>.*?)\s*\|\s*$")


def parse_note(path: Path) -> dict:
    text = read_text(path)
    lines = text.split("\n")
    slug = path.stem
    note = {"slug": slug, "title": slug, "summary_md": "", "tags": [], "theme": "",
            "updated": "", "body_md": "", "sources": [], "sources_other_md": [],
            "related": []}
    i = 0
    n = len(lines)
    # header block
    while i < n:
        ln = lines[i]
        if ln.startswith("# ") and note["title"] == slug:
            note["title"] = ln[2:].strip()
        elif ln.startswith("**Summary:**"):
            s = ln[len("**Summary:**"):].strip()
            j = i + 1
            while j < n and lines[j].strip() and not lines[j].startswith("**"):
                s += " " + lines[j].strip()
                j += 1
            note["summary_md"] = s
        elif ln.startswith("**Tags:**"):
            note["tags"] = [t.lstrip("#").strip().lower() for t in ln[len("**Tags:**"):].split() if t.startswith("#")]
        elif ln.startswith("**Theme:**"):
            note["theme"] = ln[len("**Theme:**"):].strip()
        elif ln.startswith("**Updated:**"):
            note["updated"] = ln[len("**Updated:**"):].strip()
        elif ln.strip() == "---" and note["updated"]:
            i += 1
            break
        i += 1
    body = []
    while i < n and not lines[i].startswith("**Sources:**"):
        body.append(lines[i])
        i += 1
    note["body_md"] = "\n".join(body).strip()
    if i < n:
        i += 1
    while i < n and not lines[i].startswith("**Related Notes:**"):
        ln = lines[i].rstrip()
        if ln.strip():
            m = SRC_RE.match(ln)
            if m:
                note["sources"].append({"key": m.group("key"), "url": m.group("url"),
                                        "attr": m.group("attr"), "raw": m.group("raw") or ""})
            else:
                note["sources_other_md"].append(ln)
        i += 1
    if i < n:
        i += 1
    while i < n:
        m = REL_RE.match(lines[i].strip())
        if m:
            note["related"].append({"slug": m.group("slug"), "label": m.group("label"), "desc": m.group("desc")})
        i += 1
    return note


def parse_themes(p: Path):
    out = []
    for ln in read_text(p).split("\n"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def parse_index(p: Path):
    text = read_text(p)
    lines = text.split("\n")
    dash = {"asof": "", "bullets": []}
    summaries = {}
    theme_order = []
    section = None
    in_dash = False
    for ln in lines:
        if ln.startswith("## Dashboard"):
            in_dash = True
            continue
        if in_dash:
            if ln.strip() == "---":
                in_dash = False
                continue
            s = ln.strip()
            if s.startswith("*") and s.endswith("*") and not s.startswith("**"):
                dash["asof"] = s.strip("*").strip()
            elif s.startswith("- "):
                dash["bullets"].append(s[2:].strip())
            continue
        if ln.startswith("## "):
            section = ln[3:].strip()
            theme_order.append(section)
            continue
        m = re.match(r"^\|\s*\[([a-z0-9\-]+)\]\(notes/[a-z0-9\-]+\.md\)\s*\|\s*(.*?)\s*\|\s*$", ln.strip())
        if m and section:
            summaries[m.group(1)] = {"theme": section, "summary": m.group(2)}
    return dash, summaries, theme_order


LOG_HEAD = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})(?: (\d{4})hrs)?\]?\s*\|?\s*(\w+)\s*(?:#[^|]*)?\|\s*(.*)$")


def parse_log(p: Path):
    entries = []
    cur = None
    for ln in read_text(p).split("\n"):
        m = LOG_HEAD.match(ln)
        if m:
            num = re.search(r"#\d[\d–\-#]*", ln[:ln.index("|")] if "|" in ln else "")
            cur = {"date": m.group(1), "time": m.group(2) or "0000", "type": m.group(3), "num": num.group(0) if num else "",
                   "subject": m.group(4).strip(), "lines": []}
            entries.append(cur)
        elif cur is not None and ln.strip():
            cur["lines"].append(ln.rstrip())
    return entries


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
def load_icon_symbols(names):
    symbols = []
    for name in sorted(set(names)):
        f = ASSETS / "icons" / f"{name}.svg"
        if not f.exists():
            continue
        svg = f.read_text(encoding="utf-8")
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
        svg = re.sub(r"<defs>.*?</defs>", "", svg, flags=re.S)
        svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)
        svg = re.sub(r'\s*class="cls-\d+"', "", svg)
        svg = re.sub(r'\s*style="[^"]*"', "", svg)
        svg = re.sub(r'\s*fill="#[0-9a-fA-F]{3,6}"', "", svg)
        m = re.search(r"<svg[^>]*viewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", svg, flags=re.S)
        if not m:
            continue
        symbols.append(f'<symbol id="i-{name}" viewBox="{m.group(1)}" fill="currentColor">{m.group(2).strip()}</symbol>')
    return "\n".join(symbols)


def load_logo():
    # Prefer the official vertical lockup from the OCHA 2024 logo pack if it has been dropped in;
    # fall back to the vertical lockup composed from the official horizontal geometry.
    candidates = ["OCHA_logo_vertical_blue.svg", "ocha-lockup-vertical-blue.svg", "ocha-lockup-blue.svg"]
    f = next((ASSETS / "logo" / c for c in candidates if (ASSETS / "logo" / c).exists()), None)
    if f is None:
        return '<span class="logo-text">OCHA</span>'
    svg = f.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r'<svg([^>]*)>', r'<svg\1 class="ocha-lockup" role="img" aria-label="OCHA">', svg, count=1)
    return svg.strip()


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def fmt_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:
        return iso


def load_inform():
    """INFORM Risk / INFORM Climate Change extract for the INFORM risk page.
    Produced by process_inform.py (next to this script) from the frozen raw/ workbooks."""
    f = HERE / "inform_data.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  inform_data.json skipped: {e}")
        return None


def build(wiki: Path, out: Path):
    wdir = wiki / "wiki"
    themes = parse_themes(wdir / "themes.md")
    dash, idx_summaries, idx_theme_order = parse_index(wdir / "index.md")
    log = parse_log(wdir / "log.md")
    note_paths = sorted((wdir / "notes").glob("*.md"))
    notes = [parse_note(p) for p in note_paths]
    known = {nt["slug"] for nt in notes}

    # raw/ artefact count (if the raw/ folder is reachable)
    raw_dir = wiki / "raw"
    raw_count = None
    if raw_dir.exists():
        raw_count = len([p for p in raw_dir.iterdir() if p.is_file() and not p.name.endswith(".meta.json") and not p.name.startswith(".")])
    processed = set()
    for e in log:
        for ln in e["lines"]:
            processed.update(re.findall(r"raw/[^\s;,)]+", ln))

    # render notes
    backlinks = defaultdict(set)
    edges = set()
    tag_counts = defaultdict(int)
    sources_index = OrderedDict()
    for nt in notes:
        body_html = md_html(nt["body_md"])
        body_html = rewrite_links(body_html, known)
        body_html, toc = add_heading_ids(body_html, nt["slug"])
        nt["body_html"] = body_html
        nt["toc"] = toc
        nt["summary_html"] = rewrite_links(md_inline(nt["summary_md"]), known)
        nt["one_liner"] = idx_summaries.get(nt["slug"], {}).get("summary", "")
        nt["one_liner_html"] = rewrite_links(md_inline(nt["one_liner"]), known) if nt["one_liner"] else nt["summary_html"]
        nt["text"] = strip_tags(body_html).lower()
        nt["words"] = len(nt["text"].split())
        nt["sources_other_html"] = rewrite_links(md_html("\n".join(nt["sources_other_md"])), known) if nt["sources_other_md"] else ""
        for s in nt["sources"]:
            s["attr_html"] = md_inline(s["attr"])
            key = s["raw"] or s["url"]
            rec = sources_index.setdefault(key, {"key": s["key"], "url": s["url"], "attr_html": s["attr_html"], "raw": s["raw"], "cited_by": []})
            if nt["slug"] not in rec["cited_by"]:
                rec["cited_by"].append(nt["slug"])
        for r in nt["related"]:
            r["desc_html"] = rewrite_links(md_inline(r["desc"]), known)
        for t in nt["tags"]:
            tag_counts[t] += 1
        linked = set(re.findall(r'href="#/note/([a-z0-9\-]+)"', body_html)) | {r["slug"] for r in nt["related"]}
        for tgt in linked:
            if tgt in known and tgt != nt["slug"]:
                backlinks[tgt].add(nt["slug"])
                edges.add(tuple(sorted((nt["slug"], tgt))))
        del nt["body_md"], nt["summary_md"], nt["sources_other_md"]
    titles = {nt["slug"]: nt["title"] for nt in notes}

    def add_titles(h):
        return re.sub(r'<a href="#/note/([a-z0-9\-]+)" class="wl">',
                      lambda m: f'<a href="#/note/{m.group(1)}" class="wl" title="{html.escape(titles.get(m.group(1), ""))}">', h)
    for nt in notes:
        nt["backlinks"] = sorted(backlinks.get(nt["slug"], []))
        nt["body_html"] = add_titles(nt["body_html"])
        nt["summary_html"] = add_titles(nt["summary_html"])

    # themes with counts (order per themes.md)
    theme_list = []
    for th in themes:
        members = [nt["slug"] for nt in notes if nt["theme"] == th]
        if not members:
            continue
        theme_list.append({"name": th, "slug": slugify(th), "icon": THEME_ICONS.get(th, "Document"), "count": len(members), "notes": members})
    theme_slug = {t["name"]: t["slug"] for t in theme_list}
    for nt in notes:
        nt["theme_slug"] = theme_slug.get(nt["theme"], slugify(nt["theme"]))

    # tag families
    fam_of = {}
    for fam, tags in TAG_FAMILIES.items():
        for t in tags:
            fam_of[t] = fam
    tags_by_family = OrderedDict((f, []) for f in TAG_FAMILIES)
    tags_by_family["Place"] = []
    for t, c in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        tags_by_family[fam_of.get(t, "Place")].append({"tag": t, "count": c})
    tags_by_family = OrderedDict((k, v) for k, v in tags_by_family.items() if v)

    # dashboard bullets
    bullets = []
    for b in dash["bullets"]:
        m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", b, flags=re.S)
        lead, rest = (m.group(1), m.group(2)) if m else ("", b)
        links = []
        if "→" in rest:
            rest, tail = rest.rsplit("→", 1)
            links = re.findall(r"\[([^\]]+)\]\(notes/([a-z0-9\-]+)\.md\)", tail)
        bullets.append({"lead_html": rewrite_links(md_inline(lead), known, from_index=True),
                        "body_html": rewrite_links(md_inline(rest.strip()), known, from_index=True),
                        "links": [{"label": l, "slug": s} for l, s in links if s in known]})

    # log
    log_entries = []
    for e in reversed(log):
        lines_html = []
        for ln in e["lines"]:
            s = ln.lstrip("- ").strip()
            s = re.sub(r"\b(notes/)([a-z0-9\-]+)\.md", lambda m: f"[{m.group(2)}]({m.group(2)}.md)", s)
            s = re.sub(r"(raw/[^\s;,)]+)", r"`\1`", s)
            lines_html.append(rewrite_links(md_inline(s), known))
        log_entries.append({"date": e["date"], "time": e["time"], "type": e["type"], "num": e.get("num", ""),
                            "subject_html": md_inline(e["subject"]), "lines_html": lines_html})
    ingests = sum(1 for e in log if e["type"] == "ingest")
    lints = sum(1 for e in log if e["type"] == "lint")

    last_updated = max((nt["updated"] for nt in notes if nt["updated"]), default="")
    stats = {
        "notes": len(notes),
        "themes": len(theme_list),
        "sources_cited": len(sources_index),
        "raw_artefacts": raw_count if raw_count is not None else len(processed),
        "raw_processed": len(processed),
        "log_entries": len(log),
        "ingests": ingests,
        "lints": lints,
        "tags": len(tag_counts),
        "links": sum(len(v) for v in backlinks.values()),
        "words": sum(nt["words"] for nt in notes),
        "last_updated": last_updated,
        "last_updated_fmt": fmt_date(last_updated),
        "built": dt.datetime.now().strftime("%d %B %Y %H:%M"),
    }

    data = {
        "title": "El Niño 2026–27 Climate Knowledge Wiki",
        "subtitle": "Asia and the Pacific · ENSO signals, hazards, impacts and action",
        "asof": dash["asof"],
        "stats": stats,
        "themes": theme_list,
        "notes": {nt["slug"]: nt for nt in notes},
        "note_order": [nt["slug"] for nt in sorted(notes, key=lambda x: (x["theme_slug"], x["title"].lower()))],
        "bullets": bullets,
        "edges": sorted([list(e) for e in edges]),
        "tags": tags_by_family,
        "sources": list(sources_index.values()),
        "log": log_entries,
        "wiki_path": str(wiki),
        "inform": load_inform(),
    }

    icon_names = list(THEME_ICONS.values()) + UI_ICONS
    symbols = load_icon_symbols(icon_names)
    logo = load_logo()
    page = TEMPLATE.replace("/*__CSS__*/", CSS).replace("/*__JS__*/", JS)
    page = page.replace("<!--__SYMBOLS__-->", symbols).replace("<!--__LOGO__-->", logo)
    page = page.replace("<!--__TITLE__-->", html.escape(data["title"]))
    js_data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("/*__DATA__*/", js_data)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"Built {out / 'index.html'}  —  {stats['notes']} notes, {stats['themes']} themes, "
          f"{stats['sources_cited']} sources cited, {stats['log_entries']} log entries, "
          f"{(out / 'index.html').stat().st_size // 1024} KB")


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><!--__TITLE__--></title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,300;0,400;0,500;0,700;1,400;1,700&family=Roboto+Condensed:ital,wght@0,400;0,700;1,400;1,700&display=swap" rel="stylesheet">
<style>
/*__CSS__*/
</style>
</head>
<body>
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
<!--__SYMBOLS__-->
</svg>
<a class="skip" href="#main">Skip to content</a>
<header class="masthead">
  <div class="wrap masthead-row">
    <a class="lockup" href="#/" aria-label="Dashboard"><!--__LOGO__--></a>
    <div class="vrule"></div>
    <div class="title-block">
      <div class="kicker">Asia and the Pacific</div>
      <h1 class="product-title"><a href="#/">El Niño 2026–27 <span class="thin">Climate Knowledge Wiki</span></a></h1>
      <div class="product-subtitle">ENSO signals, hazards, impacts and action — the knowledge base behind the situation dashboard</div>
    </div>
    <div class="asof"><span id="asof"></span><span class="sub badges"><span class="badge ok">Human verified sources</span><span class="badge ai">AI-generated analysis</span></span></div>
  </div>
  <div class="rule-heavy"></div>
</header>
<nav class="topnav" aria-label="Primary">
    <div class="wrap nav-row">
      <button class="nav-toggle" id="navToggle" aria-expanded="false" aria-controls="navLinks"><svg class="ico"><use href="#i-Menu"/></svg> Menu</button>
      <div class="nav-links" id="navLinks">
        <a href="#/" data-route="home">Dashboard</a>
        <a href="#/themes" data-route="themes">Themes</a>
        <a href="#/notes" data-route="notes">All notes</a>
        <a href="#/inform" data-route="inform">INFORM risk</a>
        <a href="#/tags" data-route="tags">Tags</a>
        <a href="#/sources" data-route="sources">Sources</a>
        <a href="#/log" data-route="log">Log</a>
        <a href="#/about" data-route="about">About</a>
        <a href="../index.html" class="ext" title="El Niño 2026–27 Situation and impacts">← Situation</a>
      </div>
      <form class="search" id="searchForm" role="search">
        <svg class="ico"><use href="#i-Search"/></svg>
        <input type="search" id="q" placeholder="Search the wiki…" aria-label="Search the wiki" autocomplete="off">
      </form>
    </div>
  </nav>
<main id="main" class="wrap"></main>
<footer class="product-footer">
  <div class="wrap">
    <div class="rule-medium"></div>
    <div class="footer-row" id="footer"></div>
  </div>
</footer>
<script id="wiki-data" type="application/json">/*__DATA__*/</script>
<script>
/*__JS__*/
</script>
</body>
</html>
"""

CSS = r"""
:root{
  /* OCHA Products Design System — colour tokens */
  --ocha-blue:#009edb; --ocha-black:#000; --ocha-white:#fff; --ocha-grey:#999; --ocha-slate-grey:#a1988f;
  --ocha-green:#72bf44; --ocha-yellow:#ffc800; --ocha-orange:#f58220; --ocha-red:#ed1847; --ocha-purple:#a05fb4;
  --blue-900:#002e6e; --blue-800:#004987; --blue-700:#0074b7; --blue-500:#009edb; --blue-300:#64bdea; --blue-200:#c5dfef; --blue-100:#e3edf6;
  --red-100:#fde7ec; --red-200:#fac0cd; --red-700:#ce1043; --orange-100:#fef0e2; --orange-700:#c86200; --green-100:#e7f4dd; --green-300:#a6d888; --green-900:#1e4d14;
  --grey-900:#231f20; --grey-800:#404040; --grey-700:#666; --grey-500:#999; --grey-400:#b3b3b3; --grey-300:#ccc; --grey-200:#e6e6e6; --grey-100:#f2f2f2;
  --text-body:var(--ocha-black); --text-heading:var(--ocha-blue); --text-muted:var(--grey-700); --text-figure:var(--ocha-blue); --text-date:var(--ocha-blue);
  --surface-page:#fff; --surface-panel:#eaf3fa; --surface-tint:var(--blue-100); --surface-row-alt:#f2f7fc;
  --border-hairline:var(--grey-300); --border-rule:var(--ocha-blue); --border-table:var(--ocha-black);
  --link:var(--blue-700); --link-hover:var(--blue-900); --focus-ring:var(--ocha-blue);
  /* type */
  --font-core:"Roboto",Arial,Helvetica,sans-serif; --font-condensed:"Roboto Condensed","Arial Narrow",Arial,sans-serif; --font-figure:var(--font-condensed);
  --fw-regular:400; --fw-medium:500; --fw-bold:700;
  --fs-product-title:30px; --fs-product-subtitle:17px; --fs-product-date:13px;
  --fs-section:15px; --fs-block-title:15px; --fs-block-subtitle:13px; --fs-body-lg:15px; --fs-body:14px;
  --fs-figure-xl:44px; --fs-figure-lg:30px; --fs-figure-md:22px; --fs-label-lg:12.5px; --fs-label-sm:10.5px; --fs-caption:11px; --fs-footnote:10px;
  --lh-figure:.95; --lh-tight:1.08; --lh-heading:1.18; --lh-body:1.45; --lh-loose:1.55;
  --tracking-caps:.04em; --tracking-caps-wide:.14em;
  /* geometry */
  --sp-1:2px; --sp-2:4px; --sp-3:6px; --sp-4:8px; --sp-5:12px; --sp-6:16px; --sp-7:20px; --sp-8:24px; --sp-9:32px; --sp-10:40px; --sp-11:48px; --sp-12:64px;
  --rule-heavy:3px; --rule-medium:1.5px; --rule-hairline:1px; --radius-0:0; --radius-pill:999px; --shadow-none:none;
  --ease-standard:cubic-bezier(.2,0,.2,1); --dur-fast:120ms; --dur-base:200ms;
  --wrap:1180px; --gutter:16px;
}
html{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;scroll-behavior:smooth}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--surface-page);color:var(--text-body);font-family:var(--font-core);font-size:var(--fs-body);line-height:var(--lh-body);font-weight:var(--fw-regular)}
p{margin:0 0 var(--sp-5);text-align:left;text-wrap:pretty}
h1,h2,h3,h4{margin:0;font-weight:var(--fw-bold);line-height:var(--lh-heading)}
a{color:var(--link);text-decoration:none;border-bottom:1px solid transparent;transition:color var(--dur-fast) var(--ease-standard),border-color var(--dur-fast) var(--ease-standard)}
a:hover{color:var(--link-hover);border-bottom-color:currentColor}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--focus-ring);outline-offset:2px}
strong,b{font-weight:var(--fw-bold)}
table{border-collapse:collapse}
::selection{background:var(--blue-200)}
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 var(--gutter)}
.skip{position:absolute;left:-9999px;top:0;background:var(--ocha-blue);color:#fff;padding:8px}
.skip:focus{left:8px;z-index:50}
.ico{width:1em;height:1em;display:inline-block;vertical-align:-.15em;fill:currentColor;flex:0 0 auto}
.num{font-variant-numeric:tabular-nums;text-align:right}

/* ---- masthead (ProductHeader) ---- */
.masthead{background:var(--surface-page)}
.masthead-row{display:flex;align-items:center;gap:var(--sp-6);padding-top:var(--sp-6);padding-bottom:var(--sp-5)}
.lockup{display:block;border:0;flex:0 0 auto;line-height:0}
.lockup .ocha-lockup{height:68px;width:auto;display:block}
.vrule{align-self:stretch;width:var(--rule-hairline);background:var(--ocha-blue);margin:0 var(--sp-2)}
.title-block{flex:1 1 auto;min-width:0}
.kicker{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--ocha-blue)}
.product-title{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-product-title);line-height:1.08;text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--ocha-blue)}
.product-title a{color:inherit;border:0}
.product-title .thin{font-weight:var(--fw-regular)}
.product-subtitle{font-family:var(--font-condensed);font-size:var(--fs-product-subtitle);color:var(--ocha-blue);margin-top:var(--sp-1)}
.asof{font-family:var(--font-condensed);font-style:italic;font-size:var(--fs-product-date);color:var(--text-date);white-space:nowrap;align-self:flex-end;padding-bottom:2px;text-align:right}
.asof .sub{display:block;font-style:normal;font-size:11px;color:var(--text-muted);white-space:normal}
.asof .badges{display:flex;flex-wrap:nowrap;justify-content:flex-end;gap:6px;margin-top:7px}
.badge{display:inline-flex;align-items:center;font-family:var(--font-condensed);font-style:normal;font-weight:700;font-size:11.5px;line-height:1;text-transform:uppercase;letter-spacing:.05em;padding:6px 11px 5px;border-radius:999px;color:#fff;white-space:nowrap}
.badge.ok{background:#3c7d22}
.badge.ai{background:#ce1043}
@media (max-width:700px){.asof .badges{justify-content:flex-start;flex-wrap:wrap}.badge{font-size:10.5px;padding:5px 8px 4px}}
.rule-heavy{height:var(--rule-heavy);background:var(--ocha-blue)}
.rule-medium{height:var(--rule-medium);background:var(--ocha-blue)}
.rule-hair{height:var(--rule-hairline);background:var(--border-hairline)}

/* ---- nav ---- */
.topnav{position:sticky;top:0;z-index:20;background:var(--surface-page);padding-bottom:14px}
.topnav::after{content:"";position:absolute;left:0;right:0;bottom:14px;height:var(--rule-hairline);background:var(--border-hairline)}
.nav-row{display:flex;align-items:center;gap:var(--sp-4);min-height:46px}
.nav-links{display:flex;gap:var(--sp-1);flex-wrap:wrap}
.nav-links a{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:13px;color:var(--ocha-black);padding:13px 8px 11px;border:0;border-bottom:3px solid transparent;white-space:nowrap}
.nav-links a:hover{color:var(--ocha-blue)}
.nav-links a.active{color:var(--ocha-blue);border-bottom-color:var(--ocha-blue)}
.nav-links a.ext{color:var(--ocha-blue);border-left:1px solid var(--border-hairline);margin-left:var(--sp-2);padding-left:var(--sp-4)}
.nav-toggle{display:none;background:none;border:1px solid var(--border-hairline);font:inherit;font-family:var(--font-condensed);text-transform:uppercase;padding:6px 10px;cursor:pointer}
.search{margin-left:auto;display:flex;align-items:center;gap:var(--sp-3);border:1px solid var(--border-hairline);padding:5px 10px;min-width:180px;flex:0 1 240px;background:#fff;color:var(--grey-700)}
.search input{border:0;outline:0;font:inherit;font-size:13px;width:100%;background:transparent;color:var(--ocha-black)}
.search:focus-within{border-color:var(--ocha-blue)}

/* ---- sections (SectionHeading) ---- */
main.wrap{padding-top:var(--sp-10);padding-bottom:var(--sp-10);min-height:60vh}
.section{margin-bottom:var(--sp-9)}
.sec-head{display:flex;align-items:center;gap:var(--sp-4);margin-bottom:var(--sp-3)}
.sec-head h2,.sec-head h3{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-section);text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--ocha-black)}
.sec-head .ico{width:18px;height:18px;color:var(--ocha-blue)}
.sec-head .meta{margin-left:auto;font-family:var(--font-condensed);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--text-muted)}
.sec-rule{height:1px;background:var(--ocha-black);margin-bottom:var(--sp-6)}
.sec-rule.blue{background:var(--ocha-blue)}
.lede{font-size:var(--fs-body-lg);max-width:70ch}

/* ---- key figures (KeyFigure) ---- */
.figures{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-6) var(--sp-8);padding:var(--sp-6) 0;border-top:1px solid var(--border-hairline);border-bottom:1px solid var(--border-hairline)}
.kf{display:flex;align-items:center;gap:var(--sp-4)}
.kf .ico{width:30px;height:30px;color:var(--ocha-blue)}
.kf .val{font-family:var(--font-figure);font-weight:var(--fw-bold);font-size:var(--fs-figure-lg);line-height:var(--lh-figure);color:var(--text-figure);letter-spacing:-.01em;white-space:nowrap}
.kf .val .unit{font-size:.55em}
.kf .lbl{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps);line-height:var(--lh-heading);color:var(--ocha-black)}
.kf .sub{font-size:var(--fs-caption);color:var(--text-muted)}

/* ---- dashboard situation panels ---- */
.panels{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:var(--sp-6)}
/* latest updates — compact cards */
.updates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--sp-5)}
.ncard{background:#fff;border:1px solid var(--border-hairline);border-top:3px solid var(--ocha-blue);padding:var(--sp-4) var(--sp-5) var(--sp-5);display:flex;flex-direction:column;gap:6px;min-width:0;min-height:188px}
.ncard .meta{display:flex;align-items:center;gap:6px;min-width:0}
.ncard .meta .ico{width:16px;height:16px;color:var(--ocha-blue)}
.ncard .meta .th{font-family:var(--font-condensed);font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--ocha-blue);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border:0}
.ncard .meta .u{margin-left:auto;font-family:var(--font-condensed);font-style:italic;font-size:11.5px;color:var(--text-date);white-space:nowrap}
.ncard .t{font-family:var(--font-condensed);font-weight:700;font-size:14.5px;line-height:1.2;color:var(--ocha-black);border:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ncard .t:hover{color:var(--ocha-blue)}
.ncard .s{font-size:12px;line-height:1.35;color:var(--grey-800);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ncard .srcs{display:flex;flex-wrap:wrap;gap:4px;margin-top:auto;overflow:hidden;min-width:0;align-items:center;padding-top:4px}
.spill{display:inline-block;padding:1px 8px;border-radius:var(--radius-pill);border:1px solid var(--grey-400);color:var(--grey-800);font-size:10.5px;line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;flex:0 1 auto}
.spill:hover{border-color:var(--ocha-blue);color:var(--ocha-blue)}
.ncard .more{font-family:var(--font-condensed);font-size:11px;color:var(--text-muted);white-space:nowrap;flex:0 0 auto;border:0}
.upd-layout{display:grid;grid-template-columns:minmax(0,2.1fr) minmax(280px,1fr);gap:var(--sp-8);align-items:start}
@media (max-width:980px){.upd-layout{grid-template-columns:1fr}}
.activity .act-list{list-style:none;margin:0;padding:0;max-height:578px;overflow-y:auto;border-bottom:1px solid var(--border-hairline);scrollbar-width:thin}
.act-list li{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;padding:7px 2px 8px;border-bottom:1px solid var(--grey-200);font-size:12.5px;line-height:1.35}
.act-list li:last-child{border-bottom:0}
.act-list .d{font-family:var(--font-condensed);font-style:italic;color:var(--text-date);font-size:11.5px;white-space:nowrap}
.act-list .ty{font-family:var(--font-condensed);font-weight:700;text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:9.5px;color:var(--ocha-blue);justify-self:end;align-self:center}
.act-list li.lint .ty{color:var(--orange-700)}
.act-list .s{grid-column:1/3;color:var(--grey-800);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;border:0}
.act-list .s:hover{color:var(--ocha-blue)}
@media (max-width:620px){.updates{grid-template-columns:1fr}}
.upd{background:var(--surface-panel);border-top:3px solid var(--ocha-blue);padding:var(--sp-4) var(--sp-5) var(--sp-5);display:flex;flex-direction:column;gap:6px;min-width:0;height:168px}
.upd.lint{border-top-color:var(--ocha-orange)}
.upd .meta{display:flex;align-items:center;gap:var(--sp-3);font-family:var(--font-condensed);font-size:11.5px;color:var(--text-date);font-style:italic}
.upd .pill{font-style:normal;font-weight:700;text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:9.5px;padding:1px 6px;border:1px solid currentColor;color:var(--ocha-blue)}
.upd.lint .pill{color:var(--orange-700)}
.upd .meta .n{margin-left:auto;font-style:normal;color:var(--text-muted);font-size:10.5px}
.upd .subj{font-family:var(--font-condensed);font-weight:700;font-size:14px;line-height:1.22;color:var(--ocha-black);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.upd .what{font-size:11.5px;color:var(--text-muted);margin-top:auto}
.upd .what.clamp{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;line-height:1.35}
.upd .chips{display:flex;flex-wrap:nowrap;gap:4px;overflow:hidden;min-width:0}
.upd .chips .chip{padding:1px 7px;font-size:10px;white-space:nowrap;max-width:60%;overflow:hidden;text-overflow:ellipsis;display:inline-block;flex:0 1 auto}
.upd .chips .more{font-family:var(--font-condensed);font-size:10.5px;color:var(--text-muted);white-space:nowrap;align-self:center;flex:0 0 auto}
/* knowledge graph */
.graph-wrap{position:relative;border:1px solid var(--border-hairline);background:#fff}
.graph-wrap svg{display:block;width:100%;height:auto}
.graph-wrap .gtip{position:absolute;pointer-events:none;display:none;background:#fff;border:1px solid var(--grey-500);padding:6px 9px;font-size:12px;line-height:1.35;max-width:280px;z-index:4}
.graph-wrap .gtip b{display:block;font-family:var(--font-condensed);font-size:13px}
.gnode{cursor:pointer;transition:opacity .12s}
.gdisc{fill:#fff;stroke:var(--ocha-blue);stroke-width:1.3}
.gicon{color:var(--ocha-blue);pointer-events:none}
.gnode:hover .gdisc,svg.gfocus .gnode.hub .gdisc{fill:var(--ocha-blue)}
.gnode:hover .gicon,svg.gfocus .gnode.hub .gicon{color:#fff}
.gedge{transition:opacity .12s,stroke .12s}
.glabel{font-family:var(--font-condensed);font-size:10.5px;fill:#262626;pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;transition:opacity .12s}
svg.gfocus .gnode,svg.gfocus .glabel{opacity:.15}
svg.gfocus .gedge{opacity:.06}
svg.gfocus .on{opacity:1}
svg.gfocus .gedge.on{opacity:.9;stroke:#404040}
.glegend{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--sp-4)}
.glegend button{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--grey-300);background:#fff;padding:4px 9px;font:12px var(--font-core);cursor:pointer;color:#000}
.glegend button[aria-pressed="true"]{border-color:#000;box-shadow:inset 0 0 0 1px #000}
.glegend .ico{width:18px;height:18px;color:var(--ocha-blue)}
.glegend button[aria-pressed="true"] .ico{color:var(--blue-900)}
.panel{background:var(--surface-panel);padding:var(--sp-6);display:flex;flex-direction:column;gap:var(--sp-4);border-top:3px solid var(--ocha-blue);min-width:0;overflow-wrap:anywhere}
.panel .num-badge{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-label-sm);letter-spacing:var(--tracking-caps-wide);color:var(--ocha-blue);text-transform:uppercase}
.panel .lead{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:16px;line-height:var(--lh-heading);color:var(--ocha-black)}
.panel .body{font-size:13.5px;line-height:var(--lh-body);flex:1 1 auto}
.panel .body strong{color:var(--blue-900)}
.panel .links{display:flex;flex-wrap:wrap;gap:var(--sp-2);margin-top:auto;padding-top:var(--sp-2)}

/* ---- chips (Chip) ---- */
.chip{display:inline-flex;align-items:center;gap:var(--sp-3);padding:3px 9px;border-radius:var(--radius-pill);border:1px solid var(--ocha-blue);color:var(--ocha-blue);font-size:var(--fs-label-sm);line-height:1.4;white-space:normal;text-align:left;background:#fff;font-family:var(--font-core);max-width:100%}
a.chip:hover{background:var(--ocha-blue);color:#fff;border-bottom-color:var(--ocha-blue)}
.chip.filled{background:var(--ocha-blue);color:#fff}
.chip.grey{border-color:var(--grey-400);color:var(--grey-800)}
a.chip.grey:hover{background:var(--grey-800);border-color:var(--grey-800);color:#fff}
.chip.tag::before{content:"#";opacity:.6}
.chip .cnt{font-family:var(--font-condensed);opacity:.75}

/* ---- theme grid ---- */
.theme-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:var(--sp-5)}
.theme-tile{display:flex;align-items:center;gap:var(--sp-5);padding:var(--sp-5);border:1px solid var(--border-hairline);color:var(--ocha-black);background:#fff}
.theme-tile:hover{border-color:var(--ocha-blue);color:var(--ocha-black);background:var(--surface-row-alt)}
.theme-tile .ico{width:36px;height:36px;color:var(--ocha-blue)}
.theme-tile .name{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:13px;line-height:var(--lh-heading)}
.theme-tile .cnt{font-family:var(--font-condensed);font-size:var(--fs-label-sm);color:var(--text-muted);text-transform:uppercase;letter-spacing:var(--tracking-caps)}

/* ---- two column ---- */
.cols-2{display:grid;grid-template-columns:1.2fr 1fr;gap:var(--sp-9)}
@media (max-width:860px){.cols-2{grid-template-columns:1fr}}

/* ---- note list / tables (DataTable) ---- */
.note-table{width:100%;font-size:13.5px}
.note-table th:first-child{width:30%}
.note-table th.th-theme{width:15%}
.note-table th:last-child{width:120px}
.note-table th{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:var(--fs-label-sm);text-align:left;padding:8px 10px;border-bottom:1px solid var(--ocha-black);color:var(--ocha-black)}
.note-table td{padding:9px 10px;border-bottom:1px solid var(--border-hairline);vertical-align:top}
.note-table tr:nth-child(even) td{background:var(--surface-row-alt)}
.note-table .t a{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:14px;color:var(--ocha-blue)}
.note-table .t .slug{display:block;font-size:var(--fs-caption);color:var(--text-muted);font-family:var(--font-core)}
.note-table .d{color:var(--grey-800)}
.note-table .u{white-space:nowrap;font-family:var(--font-condensed);color:var(--text-muted);font-size:12.5px}
.note-table .th{white-space:nowrap}
.note-table .tags{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.note-table .tags .chip{padding:1px 6px;font-size:9.5px}
.list-plain{list-style:none;margin:0;padding:0}
.recent-2{columns:2;column-gap:var(--sp-9)}
.recent-2 li{break-inside:avoid}
@media (max-width:860px){.recent-2{columns:1}}
.list-plain li{padding:8px 0;border-bottom:1px solid var(--border-hairline);display:flex;gap:var(--sp-4);align-items:baseline}
.list-plain li .date{font-family:var(--font-condensed);color:var(--text-date);font-style:italic;font-size:12.5px;white-space:nowrap;min-width:92px}
.list-plain li a.t{font-family:var(--font-condensed);font-weight:var(--fw-bold);color:var(--ocha-blue)}
.list-plain li .s{color:var(--grey-800);font-size:13px}

/* ---- filters ---- */
.filters{display:flex;flex-wrap:wrap;gap:var(--sp-4);align-items:center;margin-bottom:var(--sp-6)}
.filters select,.filters input{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--border-hairline);background:#fff;border-radius:0}
.filters .count{margin-left:auto;font-family:var(--font-condensed);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--text-muted)}
.filters .lbl{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps)}
.btn{font:inherit;font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:12px;padding:6px 12px;border:1px solid var(--ocha-blue);background:#fff;color:var(--ocha-blue);cursor:pointer;border-radius:0}
.btn:hover{background:var(--ocha-blue);color:#fff}

/* ---- note page ---- */
.crumbs{font-family:var(--font-condensed);font-size:12.5px;text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--text-muted);margin-bottom:var(--sp-5);display:flex;gap:var(--sp-3);flex-wrap:wrap}
.crumbs a{color:var(--ocha-blue)}
.note-head{display:flex;align-items:flex-start;gap:var(--sp-6);margin-bottom:var(--sp-5)}
.note-head .ico{width:44px;height:44px;color:var(--ocha-blue);flex:0 0 auto;margin-top:4px}
.note-title{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:30px;line-height:var(--lh-tight);color:var(--ocha-blue);text-transform:none}
.note-meta{display:flex;flex-wrap:wrap;gap:var(--sp-3) var(--sp-6);align-items:center;margin-top:var(--sp-3);font-size:12.5px}
.note-meta .updated{font-family:var(--font-condensed);font-style:italic;color:var(--text-date)}
.note-meta .theme-link{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:12px;color:var(--ocha-blue)}
.note-meta .theme-link .ico{width:14px;height:14px}
.note-tags{display:flex;flex-wrap:wrap;gap:var(--sp-2)}
.callout{display:flex;gap:var(--sp-5);padding:var(--sp-5) var(--sp-6);background:var(--surface-panel);border:1px solid var(--blue-200);color:var(--blue-900);font-size:var(--fs-body-lg);line-height:var(--lh-body);font-style:italic;margin:var(--sp-5) 0 var(--sp-7)}
.callout .ico{width:22px;height:22px;color:var(--blue-700);margin-top:3px}
.callout p:last-child{margin-bottom:0}
.note-layout{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:var(--sp-10);align-items:start}
@media (max-width:980px){.note-layout{grid-template-columns:1fr}.note-aside{position:static!important}}
.note-aside{position:sticky;top:76px;font-size:13px}
.aside-block{margin-bottom:var(--sp-7)}
.aside-block h4{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps-wide);color:var(--ocha-black);padding-bottom:var(--sp-2);border-bottom:1px solid var(--ocha-black);margin-bottom:var(--sp-3)}
.toc{list-style:none;margin:0;padding:0}
.toc li{padding:3px 0;line-height:1.3}
.toc li.l3{padding-left:14px;font-size:12px}
.toc a{color:var(--grey-800)}
.toc a:hover,.toc a.cur{color:var(--ocha-blue)}
.aside-links{list-style:none;margin:0;padding:0}
.aside-links li{padding:4px 0;border-bottom:1px solid var(--grey-200)}
.aside-links a{font-family:var(--font-condensed);font-weight:var(--fw-bold);color:var(--ocha-blue);font-size:13px}
.aside-links .s{display:block;color:var(--text-muted);font-size:12px;line-height:1.35}

/* ---- note body (markdown) ---- */
.prose{max-width:78ch;font-size:14.5px;line-height:var(--lh-loose)}
.prose>p:first-child{font-size:15.5px}
.prose h2{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:17px;text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--ocha-black);margin:var(--sp-9) 0 var(--sp-5);padding-bottom:var(--sp-3);border-bottom:1px solid var(--ocha-black);scroll-margin-top:80px}
.prose h3{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:15.5px;color:var(--ocha-blue);margin:var(--sp-7) 0 var(--sp-4);scroll-margin-top:80px}
.prose h4{font-size:14px;margin:var(--sp-6) 0 var(--sp-3)}
.prose ul,.prose ol{padding-left:1.4em;margin:0 0 var(--sp-5)}
.prose li{margin-bottom:var(--sp-2)}
.prose li>p{margin-bottom:var(--sp-2)}
.prose blockquote{margin:0 0 var(--sp-5);padding:var(--sp-4) var(--sp-6);border-left:3px solid var(--ocha-blue);background:var(--surface-row-alt);color:var(--grey-800);font-style:italic}
.prose code{font-family:ui-monospace,Consolas,"Roboto Mono",monospace;font-size:.86em;background:var(--grey-100);padding:1px 4px}
.prose code.raw{color:var(--grey-700);background:transparent;padding:0;font-size:.8em;word-break:break-all}
.prose pre{background:var(--grey-100);padding:var(--sp-5);overflow:auto;font-size:12.5px}
.prose pre code{background:transparent;padding:0}
.prose table{width:100%;margin:var(--sp-4) 0 var(--sp-6);font-size:13px;display:block;overflow-x:auto}
.prose table thead th{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:11px;text-align:left;padding:7px 9px;border-bottom:1px solid var(--ocha-black);white-space:nowrap}
.prose table td{padding:6px 9px;border-bottom:1px solid var(--border-hairline);vertical-align:top}
.prose table tr:nth-child(even) td{background:var(--surface-row-alt)}
.prose hr{border:0;border-top:1px solid var(--border-hairline);margin:var(--sp-7) 0}
.prose a.wl{color:var(--blue-700);border-bottom:1px solid var(--blue-200)}
.prose a.wl:hover{color:var(--blue-900);border-bottom-color:currentColor}
.prose a.missing{color:var(--red-700);border-bottom:1px dashed var(--red-700)}
.prose img{max-width:100%}
.prose strong{color:var(--ocha-black)}
.prose em{font-style:italic}

/* ---- sources ---- */
.src-list{list-style:none;margin:0;padding:0;font-size:13px}
.src-list li{padding:7px 0;border-bottom:1px solid var(--border-hairline);display:grid;grid-template-columns:150px 1fr;gap:var(--sp-5)}
.src-list .k a{font-family:var(--font-condensed);font-weight:var(--fw-bold);color:var(--ocha-blue);font-size:13px}
.src-list .k .ico{width:11px;height:11px;margin-left:3px;opacity:.7}
.src-list .raw{display:block;color:var(--grey-700);font-family:ui-monospace,Consolas,monospace;font-size:11px;word-break:break-all;margin-top:2px}
.src-list .cited{margin-top:3px;display:flex;flex-wrap:wrap;gap:3px}
.src-list .cited .chip{padding:1px 6px;font-size:9.5px}
@media (max-width:640px){.src-list li{grid-template-columns:1fr;gap:var(--sp-2)}}
.rel-table td.t{white-space:nowrap}

/* ---- tags page ---- */
.tag-fam{margin-bottom:var(--sp-7)}
.tag-cloud{display:flex;flex-wrap:wrap;gap:var(--sp-2)}

/* ---- log ---- */
.log-entry{padding:var(--sp-5) 0;border-bottom:1px solid var(--border-hairline);display:grid;grid-template-columns:140px 1fr;gap:var(--sp-5);font-size:13px}
.log-entry .when{font-family:var(--font-condensed);color:var(--text-date);font-style:italic;font-size:12.5px;line-height:1.4}
.log-entry .type{display:inline-block;font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);font-size:10px;padding:1px 6px;border:1px solid currentColor;margin-top:4px}
.log-entry .type.ingest{color:var(--ocha-blue)}.log-entry .type.lint{color:var(--orange-700)}.log-entry .type.init{color:var(--green-900)}
.log-entry .subj{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:14px;color:var(--ocha-black);margin-bottom:var(--sp-2)}
.log-entry ul{margin:0;padding-left:1.1em;color:var(--grey-800)}
.log-entry li{margin-bottom:3px}
.log-entry code{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--grey-700)}
@media (max-width:640px){.log-entry{grid-template-columns:1fr;gap:var(--sp-2)}}

/* ---- search results ---- */
.result{padding:var(--sp-5) 0;border-bottom:1px solid var(--border-hairline)}
.result .t{font-family:var(--font-condensed);font-weight:var(--fw-bold);font-size:16px;color:var(--ocha-blue)}
.result .th{font-family:var(--font-condensed);font-size:var(--fs-label-sm);text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--text-muted);margin-left:var(--sp-3)}
.result .snip{color:var(--grey-800);font-size:13px;margin-top:3px}
.result mark{background:var(--ocha-yellow);color:var(--ocha-black);padding:0 1px}
.empty{padding:var(--sp-9) 0;color:var(--text-muted);font-style:italic}

/* ---- about ---- */
.about-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:var(--sp-6)}
.rule-box{border:1px solid var(--border-hairline);padding:var(--sp-6)}
.rule-box h4{font-family:var(--font-condensed);font-weight:var(--fw-bold);text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--ocha-blue);font-size:13px;margin-bottom:var(--sp-3)}
.rule-box p{font-size:13.5px;margin-bottom:var(--sp-3)}
.rule-box code{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:var(--grey-100);padding:1px 4px}
.rule-box .ico{width:28px;height:28px;color:var(--ocha-blue);margin-bottom:var(--sp-3)}

/* ---- footer (ProductFooter) ---- */
.product-footer{margin-top:var(--sp-10);padding-bottom:var(--sp-9)}
.footer-row{display:flex;align-items:flex-start;gap:var(--sp-9);flex-wrap:wrap;padding-top:var(--sp-4);font-size:var(--fs-footnote);line-height:var(--lh-body);color:var(--ocha-black)}
.footer-row .disc{font-style:italic;flex:1 1 320px;min-width:240px}
.footer-row span{white-space:normal}

/* ---- responsive ---- */
@media (max-width:860px){
  .masthead-row{flex-wrap:wrap}
  .vrule{display:none}
  .title-block{flex-basis:100%}
  .asof{width:100%;padding-top:4px;text-align:left}
  .nav-toggle{display:inline-flex;align-items:center;gap:6px}
  .nav-links{display:none;width:100%;flex-direction:column;order:3;border-top:1px solid var(--border-hairline)}
  .nav-links.open{display:flex}
  .nav-links a{padding:10px 4px;border-bottom:1px solid var(--grey-200)}
  .search{min-width:0;flex:1 1 140px}
  .note-table .d,.note-table .u,.note-table .th{display:none}
}
@media (max-width:560px){
  :root{--fs-product-title:22px;--fs-product-subtitle:14px}
  .lockup .ocha-lockup{height:48px}
  .note-title{font-size:24px}
  .panels{grid-template-columns:1fr}
}
@media print{
  .topnav,.search,.note-aside,.skip{display:none!important}
  .note-layout{grid-template-columns:1fr}
  body{font-size:11pt}
  a{color:inherit}
}

/* ---------- INFORM risk page ---------- */
.inf-kfs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--sp-6);padding:var(--sp-5) 0 var(--sp-6);border-top:1px solid var(--grey-300);border-bottom:1px solid var(--grey-300);margin-bottom:var(--sp-8)}
@media (max-width:900px){.inf-kfs{grid-template-columns:repeat(2,minmax(0,1fr))}}
.inf-kfs .v{font-family:var(--font-condensed);font-weight:700;font-size:34px;line-height:1;color:var(--ocha-blue);white-space:nowrap}
.inf-kfs .v.crit{color:var(--ocha-red)}
.inf-kfs .l{font-family:var(--font-condensed);font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:var(--tracking-caps);margin-top:6px;line-height:1.25}
.inf-kfs .s{font-size:12px;color:var(--text-muted);margin-top:3px}
.inf-filters{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 var(--sp-4)}
.inf-filters .lbl{font-family:var(--font-condensed);font-size:11px;text-transform:uppercase;letter-spacing:var(--tracking-caps);color:var(--text-muted);margin-right:4px}
.inf-filters button,.inf-tabs button{font:700 12px/1 var(--font-condensed);text-transform:uppercase;letter-spacing:var(--tracking-caps);padding:7px 11px;border:1px solid var(--ocha-blue);background:#fff;color:var(--ocha-blue);cursor:pointer}
.inf-filters button[aria-pressed="true"],.inf-tabs button[aria-pressed="true"]{background:var(--ocha-blue);color:#fff}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border-top:2px solid #000}
.inf-tbl{width:100%;min-width:860px;font-size:12.5px}
.inf-tbl th{font-family:var(--font-condensed);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.03em;text-align:center;vertical-align:bottom;padding:8px 4px;border-bottom:1px solid #000;line-height:1.15}
.inf-tbl th.c{text-align:left}
.inf-tbl th button{all:unset;cursor:pointer;display:inline-flex;flex-direction:column;align-items:center;gap:3px}
.inf-tbl th.c button{align-items:flex-start}
.inf-tbl th button:hover{color:var(--ocha-blue)}
.inf-tbl th button:focus-visible{outline:2px solid var(--ocha-blue);outline-offset:2px}
.inf-tbl th .ico{width:20px;height:20px;color:var(--ocha-blue)}
.inf-tbl th[aria-sort="descending"] button::after{content:"▼";font-size:8px;color:var(--ocha-blue)}
.inf-tbl th[aria-sort="ascending"] button::after{content:"▲";font-size:8px;color:var(--ocha-blue)}
.inf-tbl th.grp{border-left:2px solid #fff}
.inf-tbl td{padding:0;border-bottom:1px solid #fff;border-left:1px solid #fff;text-align:center;height:28px;font-variant-numeric:tabular-nums}
.inf-tbl td.c{text-align:left;padding:4px 8px 4px 0;border-left:0;white-space:nowrap;min-width:170px}
.inf-tbl td.c a{font-weight:500}
.inf-tbl td.c .rk{display:inline-block;width:30px;color:var(--text-muted);font-size:11px}
.inf-tbl td.c .t1{display:inline-block;margin-left:6px;font:700 9.5px/1 var(--font-condensed);text-transform:uppercase;letter-spacing:.04em;padding:3px 5px;border:1px solid var(--ocha-red);color:var(--ocha-red);vertical-align:1px}
.inf-tbl td.c .t1:hover{background:var(--ocha-red);color:#fff}
.inf-tbl td.cls{font-family:var(--font-condensed);font-weight:700;font-size:11px;text-transform:uppercase;padding:0 6px;white-space:nowrap}
.inf-tbl tr:hover td.c{background:var(--surface-row-alt)}
.inf-tbl td.na{color:var(--grey-500)}
.inf-legend{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;font-size:11.5px;margin:var(--sp-3) 0 0;color:var(--text-muted)}
.inf-legend i{display:inline-block;width:22px;height:12px;vertical-align:-1px;margin-right:4px;border:1px solid rgba(0,0,0,.08)}
.inf-src{font-size:11px;color:var(--text-muted);font-style:italic;margin-top:var(--sp-3)}
.inf-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:var(--sp-4)}
.inf-bars{display:grid;grid-template-columns:150px minmax(0,1fr) 92px;gap:5px 10px;align-items:center;font-size:12.5px}
.inf-bars .n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inf-bars .b{height:16px;background:var(--surface-panel)}
.inf-bars .b i{display:block;height:100%;background:var(--ocha-blue)}
.inf-bars .b i.t1{background:var(--ocha-red)}
.inf-bars .v{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
@media (max-width:600px){.inf-bars{grid-template-columns:100px minmax(0,1fr) 70px}}
.inf-dumb{width:100%;max-width:1100px}
.inf-dumb svg{display:block;font-family:var(--font-core)}
.inf-dumb .lab{font-size:11px;fill:#000}
.inf-dumb .lab.t1{font-weight:700}
.inf-dumb .ax{font-size:10px;fill:var(--text-muted)}
.inf-dumb .chg{font-size:11px;font-weight:700}
.inf-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--sp-9)}
@media (max-width:900px){.inf-two{grid-template-columns:1fr}}
.inf-notes{display:flex;flex-wrap:wrap;gap:var(--sp-4);margin-top:var(--sp-3)}
.inf-cav{font-size:12.5px;margin:0;padding-left:1.1em}
.inf-cav li{margin-bottom:6px}
"""

JS = r"""
const DATA = JSON.parse(document.getElementById('wiki-data').textContent);
const NOTES = DATA.notes;
const $ = s => document.querySelector(s);
const main = $('#main');
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (n, cls='ico') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const themeBySlug = Object.fromEntries(DATA.themes.map(t => [t.slug, t]));
const themeByName = Object.fromEntries(DATA.themes.map(t => [t.name, t]));
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const fmtDate = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso||''); return m ? `${+m[3]} ${MONTHS[+m[2]-1]} ${m[1]}` : (iso||''); };
const fmtNum = n => Number(n).toLocaleString('en-GB');
const themeIcon = name => (themeByName[name]||{}).icon || 'Document';

function secHead(title, iconName, meta, blue){
  return `<div class="sec-head">${iconName?icon(iconName):''}<h2>${title}</h2>${meta?`<span class="meta">${meta}</span>`:''}</div><div class="sec-rule${blue?' blue':''}"></div>`;
}
function tagChip(t, grey){ return `<a class="chip tag${grey?' grey':''}" href="#/notes?tag=${encodeURIComponent(t)}">${esc(t)}</a>`; }
function noteChip(slug, label){ const n = NOTES[slug]; if(!n) return ''; return `<a class="chip" href="#/note/${slug}" title="${esc(n.title)}">${esc(label||n.title)}</a>`; }
function noteRow(slug, opts={}){
  const n = NOTES[slug]; if(!n) return '';
  return `<tr>
    <td class="t"><a href="#/note/${slug}">${esc(n.title)}</a><span class="slug">${slug}</span>${opts.tags?`<div class="tags">${n.tags.slice(0,6).map(t=>tagChip(t,true)).join('')}</div>`:''}</td>
    ${opts.theme?`<td class="th"><a href="#/theme/${n.theme_slug}">${esc(n.theme)}</a></td>`:''}
    <td class="d">${n.one_liner_html}</td>
    <td class="u">${fmtDate(n.updated)}</td></tr>`;
}
function noteTable(slugs, opts={}){
  if(!slugs.length) return `<div class="empty">No notes match.</div>`;
  return `<table class="note-table"><thead><tr><th>Note</th>${opts.theme?'<th class="th-theme">Theme</th>':''}<th>What it holds</th><th>Updated</th></tr></thead><tbody>${slugs.map(s=>noteRow(s,opts)).join('')}</tbody></table>`;
}

/* ---------- views ---------- */
function updCard(e){
  const touched=[]; const seen=new Set();
  e.lines_html.forEach(l=>{ const plain=l.replace(/<[^>]+>/g,''); if(/^(created|updated|split|merged)/i.test(plain)){ (l.match(/#\/note\/([a-z0-9-]+)/g)||[]).forEach(h=>{ const s=h.slice(7); if(!seen.has(s)&&NOTES[s]){ seen.add(s); touched.push(s); } }); } });
  const created=e.lines_html.some(l=>/^created/i.test(l.replace(/<[^>]+>/g,'')));
  const raws=e.lines_html.filter(l=>/^raw read/i.test(l.replace(/<[^>]+>/g,''))).map(l=>(l.match(/raw\//g)||[]).length).reduce((a,b)=>a+b,0);
  const show=touched.slice(0,3);
  return `<article class="upd ${e.type}"><div class="meta"><span class="pill">${esc(e.type)}${e.num?' '+esc(e.num):''}</span>${fmtDate(e.date)} · ${e.time.slice(0,2)}:${e.time.slice(2)}<span class="n">${raws?raws+' source'+(raws>1?'s':''):''}</span></div>
  <div class="subj" title="${esc(e.subject_html.replace(/<[^>]+>/g,''))}">${e.subject_html}</div>
  ${touched.length?`<div class="what">${created?'Created / updated':'Updated'} ${touched.length} note${touched.length>1?'s':''}</div>`:`<div class="what clamp">${esc((e.lines_html.map(l=>l.replace(/<[^>]+>/g,'')).find(l=>/^(updated|created|corrections)/i.test(l))||'').replace(/^(updated|created):\s*/i,''))}</div>`}
  <div class="chips">${show.map(s=>noteChip(s)).join('')}${touched.length>3?`<span class="more">+${touched.length-3} more</span>`:''}</div></article>`;
}
const THEME_COL=['#002e6e','#009edb','#f58220','#64bdea','#ed1847','#72bf44','#a05fb4','#ffc800','#0074b7','#a1988f','#1e4d14','#666666'];
let GLAYOUT=null;
function graphLayout(W,H){
  if(GLAYOUT) return GLAYOUT;
  const slugs=Object.keys(NOTES), idx=Object.fromEntries(slugs.map((s,i)=>[s,i]));
  const tIndex=Object.fromEntries(DATA.themes.map((t,i)=>[t.slug,i])); const nT=DATA.themes.length;
  let seed=7; const rnd=()=>{ seed=(seed*16807)%2147483647; return seed/2147483647; };
  const deg=new Array(slugs.length).fill(0); const E=DATA.edges.map(([a,b])=>{ deg[idx[a]]++; deg[idx[b]]++; return [idx[a],idx[b]]; });
  const cx=W/2, cy=H/2;
  const anchors=DATA.themes.map((t,i)=>{ const a=i/nT*Math.PI*2-Math.PI/2; return [cx+Math.cos(a)*W*0.36, cy+Math.sin(a)*H*0.36]; });
  const N=slugs.map((s,i)=>{ const ti=tIndex[NOTES[s].theme_slug]||0; const a=anchors[ti]; return {s,ti,deg:deg[i],x:a[0]+(rnd()-.5)*60,y:a[1]+(rnd()-.5)*60,vx:0,vy:0}; });
  for(let it=0;it<600;it++){
    const alpha=1-it/600;
    for(let i=0;i<N.length;i++) for(let j=i+1;j<N.length;j++){ const a=N[i],b=N[j]; let dx=b.x-a.x, dy=b.y-a.y, d2=dx*dx+dy*dy+0.01; if(d2>250000) continue; const f=7000*alpha/d2, d=Math.sqrt(d2); dx/=d; dy/=d; a.vx-=dx*f; a.vy-=dy*f; b.vx+=dx*f; b.vy+=dy*f; }
    E.forEach(([i,j])=>{ const a=N[i],b=N[j]; const dx=b.x-a.x, dy=b.y-a.y, d=Math.sqrt(dx*dx+dy*dy)||1; const f=(d-120)*0.01*alpha; a.vx+=dx/d*f; a.vy+=dy/d*f; b.vx-=dx/d*f; b.vy-=dy/d*f; });
    N.forEach(n=>{ const a=anchors[n.ti]; n.vx+=(a[0]-n.x)*0.008*alpha+(cx-n.x)*0.001*alpha; n.vy+=(a[1]-n.y)*0.008*alpha+(cy-n.y)*0.001*alpha; n.vx*=0.6; n.vy*=0.6; n.x+=n.vx; n.y+=n.vy; });
  }
  const pad=40; const xs=N.map(n=>n.x), ys=N.map(n=>n.y); const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  let kx=(W-2*pad-140)/(x1-x0||1), ky=(H-2*pad)/(y1-y0||1); if(kx>ky*1.6) kx=ky*1.6; if(ky>kx*1.6) ky=kx*1.6;
  N.forEach(n=>{ n.x=pad+(n.x-x0)*kx+((W-2*pad-140)-(x1-x0)*kx)/2; n.y=pad+(n.y-y0)*ky+((H-2*pad)-(y1-y0)*ky)/2; });
  GLAYOUT={N,E,idx}; return GLAYOUT;
}
const nodeR=n=>8+Math.sqrt(n.deg)*1.35;
function drawGraph(){
  const host=document.getElementById('graph'); if(!host) return;
  const W=1180,H=620, NSVG='http://www.w3.org/2000/svg';
  const mk=(t,a,p)=>{ const e=document.createElementNS(NSVG,t); for(const k in a) e.setAttribute(k,a[k]); if(p) p.appendChild(e); return e; };
  const {N,E}=graphLayout(W,H);
  const svg=mk('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':`Knowledge graph of ${N.length} notes and ${E.length} links`});
  host.insertBefore(svg,host.firstChild);
  const gE=mk('g',{},svg), gN=mk('g',{},svg), gL=mk('g',{},svg);
  const nb=N.map(()=>new Set()); E.forEach(([i,j])=>{ nb[i].add(j); nb[j].add(i); });
  const edgeEls=E.map(([i,j])=>mk('line',{x1:N[i].x.toFixed(1),y1:N[i].y.toFixed(1),x2:N[j].x.toFixed(1),y2:N[j].y.toFixed(1),stroke:'#b9d6ea','stroke-width':0.7,class:'gedge'},gE));
  const short=s=>{ let t=NOTES[s].title.split(' — ')[0].replace(/\s*\(.*?\)\s*/g,' ').trim(); return t.length>30?t.slice(0,29)+'…':t; };
  const boxes=[]; const topSet=new Set();
  [...N.keys()].sort((a,b)=>N[b].deg-N[a].deg).forEach(i=>{ if(topSet.size>=14) return; const n=N[i], r=nodeR(n), w=short(n.s).length*5.6, bx=[n.x+r+2,n.y-7,n.x+r+4+w,n.y+6]; const hit=boxes.some(b=>!(bx[2]<b[0]||bx[0]>b[2]||bx[3]<b[1]||bx[1]>b[3])) || N.some((m,j)=>j!==i && m.x>bx[0]-3 && m.x<bx[2]+3 && m.y>bx[1]-3 && m.y<bx[3]+3); if(!hit){ boxes.push(bx); topSet.add(i); } });
  const nodeEls=N.map((n,i)=>{ const r=nodeR(n); const g=mk('g',{class:'gnode','data-i':i,transform:`translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`},gN); mk('circle',{r:r.toFixed(1),class:'gdisc'},g); const s=r*1.3; mk('use',{href:'#i-'+DATA.themes[n.ti].icon,x:(-s/2).toFixed(1),y:(-s/2).toFixed(1),width:s.toFixed(1),height:s.toFixed(1),class:'gicon'},g); const tl=mk('title',{},g); tl.textContent=NOTES[n.s].title; return g; });
  const labelEls=N.map((n,i)=>{ const r=nodeR(n); const l=mk('text',{x:(n.x+r+3).toFixed(1),y:(n.y+3.5).toFixed(1),class:'glabel'},gL); l.textContent=short(n.s); if(!topSet.has(i)) l.style.display='none'; return l; });
  const tip=document.getElementById('gtip');
  let themeSel=null;
  function clear(){ svg.classList.remove('gfocus'); svg.querySelectorAll('.on,.hub').forEach(e=>e.classList.remove('on','hub')); labelEls.forEach((l,i)=>{ l.style.display=topSet.has(i)?'':'none'; }); }
  function focusNode(i){ clear(); svg.classList.add('gfocus'); nodeEls[i].classList.add('hub'); [i,...nb[i]].forEach(k=>{ nodeEls[k].classList.add('on'); labelEls[k].classList.add('on'); labelEls[k].style.display=''; }); E.forEach(([a,b],k)=>{ if(a===i||b===i) edgeEls[k].classList.add('on'); }); }
  function focusTheme(ti){ clear(); if(ti==null) return; svg.classList.add('gfocus'); N.forEach((n,i)=>{ if(n.ti===ti){ nodeEls[i].classList.add('on'); labelEls[i].classList.add('on'); labelEls[i].style.display=''; } }); E.forEach(([a,b],k)=>{ if(N[a].ti===ti&&N[b].ti===ti) edgeEls[k].classList.add('on'); }); }
  nodeEls.forEach((c,i)=>{
    c.addEventListener('mouseenter',e=>{ focusNode(i); const n=NOTES[N[i].s]; tip.innerHTML=`<b>${esc(n.title)}</b>${esc(n.theme)} · ${nb[i].size} linked notes`; tip.style.display='block'; const r=host.getBoundingClientRect(), b=c.getBoundingClientRect(); let left=b.right-r.left+8; if(left+280>r.width) left=b.left-r.left-288; tip.style.left=Math.max(0,left)+'px'; tip.style.top=(b.top-r.top-6)+'px'; });
    c.addEventListener('mouseleave',()=>{ tip.style.display='none'; if(themeSel!=null) focusTheme(themeSel); else clear(); });
    c.addEventListener('click',()=>{ location.hash='#/note/'+N[i].s; });
  });
  const lg=document.getElementById('glegend');
  lg.innerHTML=DATA.themes.map((t,i)=>`<button type="button" data-ti="${i}" aria-pressed="false"><svg class="ico" aria-hidden="true"><use href="#i-${t.icon}"/></svg>${esc(t.name)} <span style="color:var(--text-muted)">${t.count}</span></button>`).join('');
  lg.querySelectorAll('button').forEach(b=>b.onclick=()=>{ const ti=Number(b.dataset.ti); themeSel = themeSel===ti?null:ti; lg.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(Number(x.dataset.ti)===themeSel))); focusTheme(themeSel); });
}
function noteCard(n){
  const dk=s=>((s.raw||'').match(/_(\d{4}-\d{2}-\d{2})\./)||[])[1]||'';
  const srcs=n.sources.slice().sort((a,b)=>dk(b).localeCompare(dk(a)));
  const show=srcs.slice(0,3);
  return `<article class="ncard"><div class="meta">${icon(themeIcon(n.theme))}<a class="th" href="#/theme/${n.theme_slug}">${esc(n.theme)}</a><span class="u">Updated ${fmtDate(n.updated)}</span></div>
  <a class="t" href="#/note/${n.slug}">${esc(n.title)}</a>
  <div class="s">${n.one_liner_html}</div>
  <div class="srcs">${show.map(s=>`<a class="spill" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc((s.attr_html||'').replace(/<[^>]+>/g,''))}">${esc(s.key)}</a>`).join('')}${srcs.length>3?`<a class="more" href="#/note/${n.slug}#sources">+${srcs.length-3} sources</a>`:''}</div></article>`;
}
function viewHome(){
  const s = DATA.stats;
  const lastLog={}; DATA.log.forEach((e,i)=>{ (e.lines_html.join(' ').match(/#\/note\/([a-z0-9-]+)/g)||[]).forEach(h=>{ const sl=h.slice(7); if(!(sl in lastLog)) lastLog[sl]=i; }); });
  const recent = Object.values(NOTES).sort((a,b)=>b.updated<a.updated?-1:b.updated>a.updated?1:((lastLog[a.slug]??1e9)-(lastLog[b.slug]??1e9))||a.title.localeCompare(b.title)).slice(0,6);
  const figures = [
    ['Document', s.notes, 'Topic notes', 'one topic per note'],
    ['Bookmark', s.themes, 'Themes', 'from themes.md'],
    ['Report', s.sources_cited, 'Sources cited', 'distinct raw/ artefacts'],
    ['Data', s.raw_artefacts, 'Raw artefacts', 'frozen in raw/'],
    ['Link', s.links, 'Cross-links', 'note-to-note'],
    ['Monitoring', s.log_entries, 'Log entries', `${s.ingests} ingest · ${s.lints} lint`],
  ];
  return `
  <section class="section">
    ${secHead('Wiki at a glance','Chart', `Last note update ${fmtDate(s.last_updated)}`)}
    <div class="figures">${figures.map(f=>`<div class="kf">${icon(f[0])}<div><div class="val">${fmtNum(f[1])}</div><div class="lbl">${f[2]}</div><div class="sub">${f[3]}</div></div></div>`).join('')}</div>
  </section>
  <div class="upd-layout">
    <section class="section">
      ${secHead('Recently updated notes','Document', `<a href="#/notes">All notes →</a>`)}
      <div class="updates">${recent.map(noteCard).join('')}</div>
    </section>
    <aside class="section activity">
      ${secHead('Wiki activity','Calendar', `<a href="#/log">Full log →</a>`)}
      <ul class="act-list">${DATA.log.slice(0,60).map(e=>{ const n=(e.lines_html.join(' ').match(/#\/note\//g)||[]).length; return `<li class="${e.type}"><span class="d">${fmtDate(e.date).replace(/ 20\d\d$/,'')} · ${e.time.slice(0,2)}:${e.time.slice(2)}</span><span class="ty">${esc(e.type)}${e.num?' '+esc(e.num):''}</span><a class="s" href="#/log?q=${encodeURIComponent((e.num||e.subject_html.replace(/<[^>]+>/g,'')).slice(0,40))}">${e.subject_html.replace(/<[^>]+>/g,'')}</a></li>`; }).join('')}</ul>
    </aside>
  </div>
  <section class="section">
    ${secHead('Knowledge graph','Coordination', `${s.notes} notes · ${DATA.edges.length} links`)}
    <div class="graph-wrap" id="graph"><div class="gtip" id="gtip"></div></div>
    <div class="glegend" id="glegend"></div>
    <p style="font-size:12px;color:var(--text-muted);margin-top:var(--sp-4)">Each circle is a note, sized by how many notes it links to or is linked from; each line is a link in either direction (in-text or Related Notes). The icon is the note's theme (OCHA Humanitarian Icons). Hover to see a note's neighbours, click to open it, or pick a theme to isolate it.</p>
  </section>
  <section class="section">
    ${secHead('Browse by theme','Bookmark', `${DATA.themes.length} themes · ${s.notes} notes`)}
    <div class="theme-grid">${DATA.themes.map(t=>`<a class="theme-tile" href="#/theme/${t.slug}">${icon(t.icon)}<div><div class="name">${esc(t.name)}</div><div class="cnt">${t.count} note${t.count===1?'':'s'}</div></div></a>`).join('')}</div>
  </section>
`;
}

function viewThemes(){
  return `<section class="section">${secHead('Themes','Bookmark', `${DATA.themes.length} themes`)}
    <p class="lede">Notes are organised by topic and filed under exactly one theme — never by source. The theme list is fixed in <code>wiki/themes.md</code>; tags (<a href="#/tags">query layer</a>) cut across them.</p>
    ${DATA.themes.map(t=>`<div class="section" id="t-${t.slug}">${secHead(`<a href="#/theme/${t.slug}" style="color:inherit">${esc(t.name)}</a>`, t.icon, `${t.count} note${t.count===1?'':'s'}`)}${noteTable(t.notes)}</div>`).join('')}
  </section>`;
}
function viewTheme(slug){
  const t = themeBySlug[slug]; if(!t) return viewNotFound('theme', slug);
  return `<div class="crumbs"><a href="#/">Dashboard</a> › <a href="#/themes">Themes</a> › <span>${esc(t.name)}</span></div>
  <div class="note-head">${icon(t.icon)}<div><h1 class="note-title">${esc(t.name)}</h1><div class="note-meta"><span>${t.count} note${t.count===1?'':'s'}</span></div></div></div>
  <div class="rule-hair" style="margin-bottom:var(--sp-6)"></div>
  ${noteTable(t.notes,{tags:true})}`;
}

function viewNotes(params){
  const q = (params.get('q')||'').trim().toLowerCase();
  const theme = params.get('theme')||'';
  const tag = params.get('tag')||'';
  let slugs = DATA.note_order.filter(s=>{ const n=NOTES[s]; return (!theme||n.theme_slug===theme)&&(!tag||n.tags.includes(tag)); });
  let results = null;
  if(q){
    results = slugs.map(s=>{ const n=NOTES[s]; const hay=(n.title+' '+n.one_liner+' '+n.tags.join(' ')).toLowerCase(); let score=0; if(n.title.toLowerCase().includes(q))score+=10; if(hay.includes(q))score+=5; const idx=n.text.indexOf(q); if(idx>=0)score+=1+Math.min(5,(n.text.split(q).length-1)/4); return {s,score,idx}; }).filter(r=>r.score>0).sort((a,b)=>b.score-a.score);
  }
  const allTags = Object.values(DATA.tags).flat().map(t=>t.tag).sort();
  const ctl = `<div class="filters">
    <span class="lbl">Filter</span>
    <select id="fTheme"><option value="">All themes</option>${DATA.themes.map(t=>`<option value="${t.slug}"${t.slug===theme?' selected':''}>${esc(t.name)}</option>`).join('')}</select>
    <select id="fTag"><option value="">All tags</option>${allTags.map(t=>`<option value="${esc(t)}"${t===tag?' selected':''}>#${esc(t)}</option>`).join('')}</select>
    <input id="fQ" type="search" placeholder="Search text…" value="${esc(params.get('q')||'')}">
    ${(q||theme||tag)?'<a class="btn" href="#/notes">Clear</a>':''}
    <span class="count">${results?results.length:slugs.length} of ${DATA.stats.notes} notes</span></div>`;
  let body;
  if(results){
    body = results.length ? results.map(r=>{ const n=NOTES[r.s]; let snip=''; if(r.idx>=0){ const a=Math.max(0,r.idx-110), b=Math.min(n.text.length,r.idx+q.length+140); snip=(a>0?'… ':'')+esc(n.text.slice(a,b))+(b<n.text.length?' …':''); snip=snip.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'),m=>`<mark>${m}</mark>`);} else snip=n.one_liner_html; return `<div class="result"><a class="t" href="#/note/${n.slug}">${esc(n.title)}</a><span class="th">${esc(n.theme)}</span><div class="snip">${snip}</div></div>`; }).join('') : `<div class="empty">No notes contain “${esc(q)}”.</div>`;
  } else body = noteTable(slugs,{theme:true,tags:true});
  const title = tag?`Notes tagged #${esc(tag)}`:theme?`Notes in ${esc((themeBySlug[theme]||{}).name||theme)}`:q?`Search results`:'All notes';
  return `<section class="section">${secHead(title,'Table')}${ctl}${body}</section>`;
}

function viewNote(slug){
  const n = NOTES[slug]; if(!n) return viewNotFound('note', slug);
  const t = themeByName[n.theme] || {};
  const toc = n.toc.length ? `<div class="aside-block"><h4>On this page</h4><ul class="toc">${n.toc.map(h=>`<li class="l${h.level}"><a href="#/note/${slug}#${h.id}" data-anchor="${h.id}">${esc(h.text)}</a></li>`).join('')}</ul></div>` : '';
  const rel = n.related.length ? `<div class="aside-block"><h4>Related notes</h4><ul class="aside-links">${n.related.map(r=>NOTES[r.slug]?`<li><a href="#/note/${r.slug}">${esc(NOTES[r.slug].title)}</a><span class="s">${r.desc_html}</span></li>`:`<li><span style="color:var(--red-700)">${esc(r.label)}</span><span class="s">${r.desc_html}</span></li>`).join('')}</ul></div>` : '';
  const back = n.backlinks.length ? `<div class="aside-block"><h4>Cited by</h4><ul class="aside-links">${n.backlinks.map(b=>`<li><a href="#/note/${b}">${esc(NOTES[b].title)}</a></li>`).join('')}</ul></div>` : '';
  const src = (n.sources.length||n.sources_other_html) ? `<section class="section" id="sources">${secHead('Sources','Report', `${n.sources.length} source${n.sources.length===1?'':'s'}`)}<ul class="src-list">${n.sources.map(s=>`<li><div class="k"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.key)}${icon('Link')}</a></div><div>${s.attr_html}${s.raw?`<span class="raw">${esc(s.raw)}</span>`:''}</div></li>`).join('')}</ul>${n.sources_other_html?`<div class="prose" style="margin-top:8px">${n.sources_other_html}</div>`:''}</section>` : '';
  const relTable = n.related.length ? `<section class="section">${secHead('Related notes','Link')}<table class="note-table rel-table"><thead><tr><th>Note</th><th>Why it is related</th></tr></thead><tbody>${n.related.map(r=>`<tr><td class="t">${NOTES[r.slug]?`<a href="#/note/${r.slug}">${esc(NOTES[r.slug].title)}</a><span class="slug">${r.slug}</span>`:`<span style="color:var(--red-700)">${esc(r.label)}</span>`}</td><td class="d">${r.desc_html}</td></tr>`).join('')}</tbody></table></section>` : '';
  return `<div class="crumbs"><a href="#/">Dashboard</a> › <a href="#/theme/${n.theme_slug}">${esc(n.theme)}</a> › <span>${esc(slug)}</span></div>
  <div class="note-head">${icon(t.icon||'Document')}<div>
    <h1 class="note-title">${esc(n.title)}</h1>
    <div class="note-meta">
      <a class="theme-link" href="#/theme/${n.theme_slug}">${icon(t.icon||'Document')} ${esc(n.theme)}</a>
      <span class="updated">Updated ${fmtDate(n.updated)}</span>
      <span style="color:var(--text-muted)">${fmtNum(n.words)} words · ${n.sources.length} sources</span>
    </div>
    <div class="note-meta"><div class="note-tags">${n.tags.map(t=>tagChip(t)).join('')}</div></div>
  </div></div>
  <div class="callout">${icon('Alert')}<div>${n.summary_html}</div></div>
  <div class="note-layout">
    <div>
      <div class="prose">${n.body_html}</div>
      ${src}${relTable}
      <div style="font-size:var(--fs-footnote);color:var(--text-muted);margin-top:var(--sp-6)">Source file: <code>wiki/notes/${slug}.md</code></div>
    </div>
    <aside class="note-aside">${toc}${rel}${back}</aside>
  </div>`;
}

function viewTags(){
  const fams = Object.entries(DATA.tags);
  return `<section class="section">${secHead('Tags','Filter', `${DATA.stats.tags} tags`)}
  <p class="lede">Tags are the wiki’s query layer — multi-valued and cross-cutting. The signal-to-action chain tags make the chain queryable across every theme without imposing it as structure.</p>
  ${fams.map(([f,list])=>`<div class="tag-fam"><div class="sec-head"><h3>${esc(f)}</h3><span class="meta">${list.length}</span></div><div class="tag-cloud">${list.map(t=>`<a class="chip tag" href="#/notes?tag=${encodeURIComponent(t.tag)}">${esc(t.tag)} <span class="cnt">${t.count}</span></a>`).join('')}</div></div>`).join('')}
  </section>`;
}

function viewSources(params){
  const q=(params.get('q')||'').toLowerCase();
  let list = DATA.sources.slice();
  if(q) list = list.filter(s=>(s.key+' '+s.attr_html+' '+s.raw).toLowerCase().includes(q));
  list.sort((a,b)=>{ const da=(a.raw.match(/_(\d{4}-\d{2}-\d{2})\./)||[])[1]||'', db=(b.raw.match(/_(\d{4}-\d{2}-\d{2})\./)||[])[1]||''; return db.localeCompare(da)||a.key.localeCompare(b.key); });
  return `<section class="section">${secHead('Sources','Report', `${DATA.sources.length} artefacts cited · ${DATA.stats.raw_artefacts} frozen in raw/`)}
  <p class="lede">Every figure in the wiki traces to a frozen artefact in <code>raw/</code>. Each entry below links to the original publication; the <code>raw/</code> name is the stable local identifier. Sorted by publication date.</p>
  <div class="filters"><span class="lbl">Find</span><input id="sQ" type="search" placeholder="Publisher, title, key…" value="${esc(params.get('q')||'')}"><span class="count">${list.length} shown</span></div>
  <ul class="src-list">${list.map(s=>`<li><div class="k"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.key)}${icon('Link')}</a></div><div>${s.attr_html}${s.raw?`<span class="raw">${esc(s.raw)}</span>`:''}<div class="cited">${s.cited_by.map(c=>noteChip(c)).join('')}</div></div></li>`).join('')}</ul></section>`;
}

function viewLog(params){
  const q=(params.get('q')||'').toLowerCase();
  const type=params.get('type')||'';
  let list = DATA.log.filter(e=>(!type||e.type===type)&&(!q||(e.subject_html+' '+e.lines_html.join(' ')).toLowerCase().includes(q)));
  return `<section class="section">${secHead('Wiki log','Monitoring', `${DATA.log.length} entries · ${DATA.stats.ingests} ingest · ${DATA.stats.lints} lint`)}
  <p class="lede">Append-only ledger of every wiki-changing operation, newest first. A raw artefact counts as processed once its filename appears here.</p>
  <div class="filters"><span class="lbl">Filter</span><select id="lType"><option value="">All types</option><option value="ingest"${type==='ingest'?' selected':''}>Ingest</option><option value="lint"${type==='lint'?' selected':''}>Lint</option></select><input id="lQ" type="search" placeholder="Search log…" value="${esc(params.get('q')||'')}"><span class="count">${list.length} shown</span></div>
  ${list.map(e=>`<div class="log-entry"><div class="when">${fmtDate(e.date)}<br>${e.time.slice(0,2)}:${e.time.slice(2)} hrs<br><span class="type ${e.type}">${e.type}${e.num?' '+esc(e.num):''}</span></div><div><div class="subj">${e.subject_html}</div><ul>${e.lines_html.map(l=>`<li>${l}</li>`).join('')}</ul></div></div>`).join('')}
  </section>`;
}

function viewAbout(){
  const s=DATA.stats;
  return `<section class="section">${secHead('About this wiki','Information-management')}
  <p class="lede">The Climate Knowledge Wiki is a Markdown knowledge base on the 2026–27 El Niño and its humanitarian consequences across Asia and the Pacific, maintained by the OCHA Regional Office for Asia and the Pacific information-management team. Sources are frozen in <code>raw/</code>; the wiki is what they <em>mean</em>, reorganised by topic. This microsite is a read-only rendering of the wiki as it stood on ${fmtDate(s.last_updated)} (built ${esc(s.built)}).</p>
  <div class="about-grid">
    <div class="rule-box">${icon('Bookmark')}<h4>1 · Organise by topic, never by source</h4><p>A note is one topic — a single concept, phenomenon or subject. One source feeds several notes; one note draws on several sources. Topics file under exactly one theme in the index.</p></div>
    <div class="rule-box">${icon('Document')}<h4>2 · Update, don’t duplicate</h4><p>Before anything is written, the index and notes are checked for an existing topic. Existing notes are enriched in place; new notes exist only for genuinely new topics.</p></div>
    <div class="rule-box">${icon('Data')}<h4>3 · Keep the wiki currently true; never touch raw/</h4><p>When new information meets old it is reconciled. Wrong facts are replaced; forecasts that legitimately shifted keep their dated trajectory. <code>raw/</code> is the permanent, immutable record.</p></div>
    <div class="rule-box">${icon('Link')}<h4>4 · Interlink everything</h4><p>Every note links related notes in its text and ends with a Related Notes table. Every note is reachable from the index. No orphans, no dangling links, no stubs.</p></div>
  </div>
  </section>
  <section class="section">${secHead('How to read a note','Report')}
  <div class="prose">
  <ul>
    <li><strong>Summary</strong> (blue panel) — one to two sentences, conclusion first.</li>
    <li><strong>Theme</strong> — the one section the note files under; <strong>tags</strong> — the cross-cutting query layer (chain stage, ENSO phase, hazard, place, sector).</li>
    <li><strong>Numbers over adjectives.</strong> Figures carry their date and unit and are transcribed from the source, never rounded or recalculated. Anything computed in the wiki is labelled <em>derived</em>.</li>
    <li><strong>Source anchors</strong> — a <code class="raw">raw/…</code> identifier under a key fact names the frozen artefact; the <strong>Sources</strong> block links each one to its original publication.</li>
    <li><strong>Dated trajectories</strong> — where a forecast or indicator changed over time, each reading is kept at its date; the sequence is itself knowledge.</li>
  </ul>
  </div></section>
  <section class="section">${secHead('Regenerating this site','Data')}
  <div class="prose"><p>The site is generated from the wiki folder by <code>build_site.py</code>. After each ingest or lint, run:</p>
  <pre><code>python build_site.py --wiki "${esc(DATA.wiki_path)}" --out "&lt;this folder&gt;"</code></pre>
  <p>Everything — notes, search index, icons and logo — is embedded in the single <code>index.html</code>, so it can be opened from disk, attached or shared as one file.</p></div></section>`;
}
function viewNotFound(kind, slug){ return `<div class="empty">No ${kind} named “${esc(slug)}”. <a href="#/">Back to the dashboard</a>.</div>`; }


/* ---------- INFORM risk page ---------- */
const INF = DATA.inform;
const T1 = ['PNG','PHL','TLS','SLB','VUT','MMR'];   /* 28 Aug 2026 snapshot, Tier 1 — high concern */
const ISO_NOTE = {PNG:'png-drought-2026',PHL:'philippines-el-nino-2026',TLS:'timor-leste-el-nino-2026',IDN:'indonesia-drought-2026',VNM:'viet-nam-drought-2026-27',KHM:'cambodia-drought-el-nino',LKA:'sri-lanka-drought-2026',AFG:'afghanistan-food-security-el-nino',PAK:'pakistan-food-security-el-nino',BGD:'bangladesh-el-nino-food-security',NPL:'nepal-food-security-el-nino',IND:'india-monsoon-2026',SLB:'pacific-islands-el-nino-2026',VUT:'pacific-islands-el-nino-2026',FJI:'pacific-islands-el-nino-2026',TON:'pacific-islands-el-nino-2026',WSM:'pacific-islands-el-nino-2026',KIR:'pacific-islands-el-nino-2026',MHL:'pacific-islands-el-nino-2026',FSM:'micronesia-el-nino-storms-2026',PLW:'pacific-islands-el-nino-2026',NRU:'pacific-islands-el-nino-2026',TUV:'pacific-islands-el-nino-2026'};
const CLS_COL = {'Very Low':['#f2f7fc','#000'],'Low':['#c5dfef','#000'],'Medium':['#64bdea','#000'],'High':['#0074b7','#fff'],'Very High':['#002e6e','#fff']};
const BANDS = [[2,'#f2f7fc','#000'],[3.5,'#c5dfef','#000'],[5,'#64bdea','#000'],[6.5,'#0074b7','#fff'],[99,'#002e6e','#fff']];
const band = v => { if(v==null) return ['#fff','#999']; for(const [t,b,f] of BANDS) if(v<t) return [b,f]; };
const DIV = v => { if(v==null||v===0) return ['#fff','#737373']; if(v>0){ if(v<0.5) return ['#fde7ec','#000']; if(v<1.5) return ['#f7a1b5','#000']; if(v<3) return ['#ed1847','#fff']; return ['#a50d35','#fff']; } if(v>-1) return ['#e3edf6','#000']; if(v>-2.5) return ['#c5dfef','#000']; return ['#64bdea','#000']; };
const cmp = v => { const a=Math.abs(v); const sg=v<0?'−':''; if(a>=1e6) return sg+(a/1e6).toFixed(a>=1e7?0:1).replace(/\.0$/,'')+' M'; if(a>=1e3) return sg+Math.round(a/1e3)+' K'; return sg+Math.round(a); };
const whole = v => (v<0?'−':'')+Math.round(Math.abs(v)).toLocaleString('en-US');
const sgn = v => v>0?'+'+v:(v<0?'−'+Math.abs(v):'0');
const infState = {f:'all', key:'risk', dir:-1, ckey:'drought_he_p', cdir:-1, bar:'x_flood', hz:'2050'};
const RCOLS = [['risk','INFORM risk',null],['he','Hazard &amp; exposure',null],['flood','River flood','Flood'],['tc','Tropical cyclone','Cyclone'],['cflood','Coastal flood','Storm-surge'],['drought','Drought','Drought'],['epi','Epidemic','Epidemic'],['vu','Vulnera&shy;bility',null],['food','Food security',null],['lcc','Lack of coping capacity',null]];
const CCOLS = [['flood_he_p','River flood','Flood','flood_n_p'],['cflood_he_p','Coastal flood','Storm-surge','cflood_n_p'],['drought_he_p','Drought','Drought','drought_n_p'],['epi_he_p','Malaria &amp; dengue','Epidemic','epi_n_p']];
function infRows(){ let r=INF.countries.slice(); if(infState.f==='t1') r=r.filter(c=>T1.includes(c.iso)); else if(infState.f==='ROAP'||infState.f==='ROP') r=r.filter(c=>c.ocha===infState.f); else if(infState.f==='other') r=r.filter(c=>c.ocha!=='ROAP'&&c.ocha!=='ROP'); return r; }
function infName(c){ const note=ISO_NOTE[c.iso]&&NOTES[ISO_NOTE[c.iso]]?ISO_NOTE[c.iso]:null; const nm=note?`<a href="#/note/${note}" title="Wiki note: ${esc(NOTES[note].title)}">${esc(c.name)}</a>`:esc(c.name); return nm+(T1.includes(c.iso)?`<a class="t1" href="../country/${c.iso.toLowerCase()}.html" title="El Niño Tier 1 country profile">Tier 1</a>`:''); }
function infRiskBody(){
  const k=infState.key, d=infState.dir;
  const rows=infRows().sort((a,b)=>{ const x=k==='name'?a.name.localeCompare(b.name):((a[k]??-1)-(b[k]??-1)); return d*(k==='name'?x:x)||a.name.localeCompare(b.name); });
  return rows.map(c=>{ const [cb,cf]=CLS_COL[c.cls]||['#fff','#000'];
    return `<tr><td class="c"><span class="rk">${c.rank}</span>${infName(c)}</td><td class="cls" style="background:${cb};color:${cf}">${esc(c.cls)}</td>${RCOLS.map(([key])=>{ const v=c[key]; const [b,f]=band(v); return `<td${v==null?' class="na"':''} style="background:${b};color:${f}" title="${esc(c.name)} · ${key}: ${v==null?'no data':v}">${v==null?'–':v}</td>`; }).join('')}</tr>`; }).join('');
}
function infCcBody(){
  const k=infState.ckey, d=infState.cdir;
  const rows=infRows().filter(c=>c.cc).sort((a,b)=> k==='name'? d*a.name.localeCompare(b.name) : (d*((a.cc[k]??0)-(b.cc[k]??0)) || a.name.localeCompare(b.name)));
  return rows.map(c=>`<tr><td class="c">${infName(c)}</td>${CCOLS.map(([key,,,nk])=>{ const v=c.cc[key], n=c.cc[nk]; const [b,f]=DIV(v); return `<td style="background:${b};color:${f}" title="${esc(c.name)} · change in hazard &amp; exposure ${sgn(v)}; change in people exposed ${n==null?'–':whole(n)} (pessimistic, ≈2050)">${sgn(v)}<div style="font-size:10px;opacity:.85">${n==null||n===0?'':(n>0?'+':'')+cmp(n)}</div></td>`; }).join('')}</tr>`).join('');
}
function infDumb(){
  const h=infState.hz, P='p'+h, O='o'+h;
  const rows=infRows().filter(c=>c.cc).sort((a,b)=>(b.cc[P+'_chg']-a.cc[P+'_chg'])||(b.cc[P]-a.cc[P])||a.name.localeCompare(b.name));
  const box=document.getElementById('infDumb'), W=Math.max(320, Math.min(1100, (box&&box.clientWidth)||900)), L=W<640?108:160, R=W<640?44:56, top=26, rh=20, H=top+rows.length*rh+14, X=v=>L+(v/9)*(W-L-R);
  let g=`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="max-width:100%;height:auto" role="img" aria-label="INFORM Climate Change risk, 2022 baseline against ≈${h} pessimistic and optimistic scenarios">`;
  for(let t=0;t<=9;t++) g+=`<line x1="${X(t)}" x2="${X(t)}" y1="${top-6}" y2="${H-10}" stroke="${t%3?'#eee':'#ddd'}"/><text class="ax" x="${X(t)}" y="${top-10}" text-anchor="middle">${t}</text>`;
  g+=`<text class="ax" x="${W-R+8}" y="${top-10}">Δ pess.</text>`;
  rows.forEach((c,i)=>{ const y=top+i*rh+rh/2, k=c.cc, vals=[k.b2022,k[P],k[O]], lo=Math.min(...vals), hi=Math.max(...vals), ch=k[P+'_chg'];
    g+=`<g><title>${esc(c.name)} — 2022 baseline ${k.b2022}; ≈${h} pessimistic ${k[P]} (${sgn(k[P+'_chg'])}); optimistic ${k[O]} (${sgn(k[O+'_chg'])})</title>
    <text class="lab${T1.includes(c.iso)?' t1':''}" x="${L-8}" y="${y+4}" text-anchor="end">${esc(c.name)}</text>
    <line x1="${X(lo)}" x2="${X(hi)}" y1="${y}" y2="${y}" stroke="#bbb" stroke-width="2"/>
    <circle cx="${X(k.b2022)}" cy="${y}" r="4.5" fill="#fff" stroke="#737373" stroke-width="1.5"/>
    <circle cx="${X(k[O])}" cy="${y}" r="4" fill="#009edb"/>
    <circle cx="${X(k[P])}" cy="${y}" r="4" fill="#ed1847"/>
    <text class="chg" x="${W-R+8}" y="${y+4}" fill="${ch>0?'#ce1043':(ch<0?'#0074b7':'#737373')}">${sgn(ch)}</text></g>`; });
  return g+'</svg>';
}
function infBars(){
  const k=infState.bar; const rows=INF.countries.filter(c=>c[k]>0).sort((a,b)=>b[k]-a[k]).slice(0,12); if(!rows.length) return '<div class="empty">No data.</div>';
  const mx=rows[0][k];
  return rows.map(c=>`<div class="n" title="${esc(c.name)}">${esc(c.name)}</div><div class="b" title="${esc(c.name)}: ${whole(c[k])}"><i class="${T1.includes(c.iso)?'t1':''}" style="width:${Math.max(0.6,c[k]/mx*100)}%"></i></div><div class="v" title="${whole(c[k])}">${cmp(c[k])}</div>`).join('');
}
function viewInform(){
  if(!INF) return `<div class="empty">INFORM data not available. Run <code>process_inform.py</code> next to <code>build_site.py</code>, then rebuild.</div>`;
  const C=INF.countries;
  const top=C.slice().sort((a,b)=>b.risk-a.risk)[0];
  const hi=C.filter(c=>c.cls==='High'||c.cls==='Very High');
  let mxH={v:-99}; C.forEach(c=>CCOLS.forEach(([k,lab])=>{ if(c.cc&&c.cc[k]>mxH.v) mxH={v:c.cc[k],c,lab}; }));
  const mx80=C.filter(c=>c.cc).sort((a,b)=>b.cc.p2080_chg-a.cc.p2080_chg)[0];
  const th=(cols,state,keyName,dirName)=>cols.map(([k,lab,ic])=>`<th class="grp"${state[keyName]===k?` aria-sort="${state[dirName]<0?'descending':'ascending'}"`:''}><button type="button" data-sort="${k}">${ic?icon(ic):''}<span>${lab}</span></button></th>`).join('');
  const filt=[['all','All'],['ROAP','OCHA ROAP'],['ROP','Pacific (ROP)'],['other','Afghanistan, Pakistan'],['t1','El Niño Tier 1']];
  return `<div class="crumbs"><a href="#/">Dashboard</a> › <span>INFORM risk</span></div>
  <section class="section">${secHead('INFORM risk — Asia and the Pacific','Alert', esc(INF.risk_release.replace('INFORM Risk Index ','')))}
    <p class="lede">The <strong>INFORM Risk Index</strong> scores each country 0–10 for the risk of a humanitarian crisis that would need international assistance, from three dimensions — hazard &amp; exposure, vulnerability and lack of coping capacity. This page shows its <strong>climate-sensitive hazard components</strong> for ${C.length} Asia-Pacific countries and the <strong>INFORM Climate Change</strong> projections to ≈2050 and ≈2080. INFORM is structural, not a forecast: it shows where climate hazards habitually hit and where people can least absorb them — the baseline the 2026–27 El Niño lands on.</p>
    <div class="inf-notes">${noteChip('inform-risk-index','Wiki note: INFORM Risk Index — Asia-Pacific')}${noteChip('inform-climate-change-risk','Wiki note: INFORM Climate Change projections')}${noteChip('el-nino-priority-country-tiers-2026','El Niño priority tiers')}</div>
  </section>
  <div class="inf-kfs">
    <div><div class="v crit">${top.risk}</div><div class="l">Highest risk in the region</div><div class="s">${esc(top.name)} · ${esc(top.cls)} · rank ${top.rank} of 191</div></div>
    <div><div class="v">${hi.length}</div><div class="l">Countries in INFORM's High or Very High class</div><div class="s">${hi.map(c=>esc(c.name)).join(', ')}</div></div>
    <div><div class="v crit">${sgn(mxH.v)}</div><div class="l">Largest hazard shift by ≈2050</div><div class="s">${mxH.lab.replace('&amp;','&')}, ${esc(mxH.c.name)} · pessimistic scenario</div></div>
    <div><div class="v">${sgn(mx80.cc.p2080_chg)}</div><div class="l">Largest rise in overall risk by ≈2080</div><div class="s">${esc(mx80.name)}, ${mx80.cc.b2022} → ${mx80.cc.p2080} · pessimistic scenario</div></div>
  </div>
  <div class="inf-filters" role="group" aria-label="Filter countries"><span class="lbl">Show</span>${filt.map(([k,l])=>`<button type="button" data-f="${k}" aria-pressed="${infState.f===k}">${l}</button>`).join('')}</div>
  <section class="section">${secHead('Climate-hazard scores, Mid 2026','Data', 'Click a column to sort')}
    <div class="tbl-wrap"><table class="inf-tbl" id="infRisk"><thead><tr><th class="c"${infState.key==='name'?` aria-sort="${infState.dir<0?'descending':'ascending'}"`:''}><button type="button" data-sort="name"><span>Rank · country</span></button></th><th>Class</th>${th(RCOLS,infState,'key','dir')}</tr></thead><tbody>${infRiskBody()}</tbody></table></div>
    <div class="inf-legend"><span>Score 0–10:</span>${BANDS.map(([t,b],i)=>`<span><i style="background:${b}"></i>${i===0?'&lt; 2':(i===BANDS.length-1?'≥ 6.5':`${BANDS[i-1][0]}–${t}`)}</span>`).join('')}<span>Class column uses INFORM's own risk classes.</span></div>
    <div class="inf-src">Source: ${esc(INF.risk_release)}. Scope: ${esc(INF.scope)}. Rank of 191 countries; ties share a rank. River flood, cyclone and coastal flood are average annual exposure; drought rests on 1990–2013 impacts (EM-DAT) and FAO's Agriculture Stress Index.</div>
  </section>
  <section class="section">${secHead('People exposed each year','People-affected', 'Top 12 · Tier 1 countries in red')}
    <div class="inf-tabs" role="group" aria-label="Hazard">${[['x_flood','River flood'],['x_tc1','Cyclone wind ≥ Cat 1'],['x_cflood','Coastal flood'],['x_drought_aff','Drought affected']].map(([k,l])=>`<button type="button" data-bar="${k}" aria-pressed="${infState.bar===k}">${l}</button>`).join('')}</div>
    <div class="inf-bars" id="infBars">${infBars()}</div>
    <div class="inf-src">Source: ${esc(INF.risk_release)}, Indicator Data. Average annual expected population exposed (river flood, cyclone wind of Saffir-Simpson category 1+, coastal flood); drought: average annual people affected, 1990–2013 (EM-DAT). Bar labels rounded; hover for the published value to the nearest person.</div>
  </section>
  <section class="section">${secHead('Projected crisis risk to ≈2050 and ≈2080','Trending', 'INFORM Climate Change')}
    <div class="inf-tabs" role="group" aria-label="Horizon">${[['2050','Mid-century ≈2050'],['2080','End-century ≈2080']].map(([k,l])=>`<button type="button" data-hz="${k}" aria-pressed="${infState.hz===k}">${l}</button>`).join('')}</div>
    <div class="inf-legend" style="margin:0 0 8px"><span><i style="background:#fff;border:1.5px solid #737373;border-radius:50%;width:10px;height:10px"></i>Baseline 2022</span><span><i style="background:#009edb;border-radius:50%;width:10px;height:10px"></i>Optimistic scenario</span><span><i style="background:#ed1847;border-radius:50%;width:10px;height:10px"></i>Pessimistic scenario</span><span>Δ = pessimistic change from 2022 · El Niño Tier 1 in bold</span></div>
    <div class="inf-dumb" id="infDumb">${infDumb()}</div>
    <div class="inf-src">Source: ${esc(INF.cc_release)}. "Pessimistic" and "optimistic" are INFORM's combined climate and socio-economic scenarios. The 2022 baseline is INFORM Climate Change's own series and differs from the Mid 2026 scores above.</div>
  </section>
  <section class="section">${secHead('Change in hazard &amp; exposure by ≈2050','Monitoring', 'Pessimistic scenario · click a column to sort')}
    <div class="tbl-wrap"><table class="inf-tbl" id="infCc" style="min-width:560px"><thead><tr><th class="c"${infState.ckey==='name'?` aria-sort="${infState.cdir<0?'descending':'ascending'}"`:''}><button type="button" data-csort="name"><span>Country</span></button></th>${CCOLS.map(([k,lab,ic])=>`<th class="grp"${infState.ckey===k?` aria-sort="${infState.cdir<0?'descending':'ascending'}"`:''}><button type="button" data-csort="${k}">${icon(ic)}<span>${lab}</span></button></th>`).join('')}</tr></thead><tbody>${infCcBody()}</tbody></table></div>
    <div class="inf-legend"><span>Change in score:</span>${[[-3,'≤ −2.5'],[-2,'−2.5 to −1'],[-0.5,'−1 to 0'],[0.2,'0 to 0.5'],[1,'0.5 to 1.5'],[2,'1.5 to 3'],[4,'≥ 3']].map(([v,l])=>`<span><i style="background:${DIV(v)[0]}"></i>${l}</span>`).join('')}<span>Second line: change in people exposed.</span></div>
    <div class="inf-src">Source: ${esc(INF.cc_release)}. Change in the hazard &amp; exposure score and in the absolute number of people exposed, ≈2050, pessimistic scenario.</div>
  </section>
  <section class="section">${secHead('Reading INFORM alongside the El Niño tiers','Information-management')}
    <ul class="inf-cav">
      <li><strong>Structural, not seasonal.</strong> INFORM's drought component rests on 1990–2013 impacts and FAO cropland-stress probability, so the drier-side El Niño Tier 1 countries score low to moderate on drought (Timor-Leste 1.9 to Vanuatu 5.0). The Tier 1 list comes from the Sep–Nov 2026 rainfall forecast and price exposure.</li>
      <li><strong>Where they agree:</strong> weak coping capacity and food-security vulnerability in Papua New Guinea, Solomon Islands, Vanuatu and Timor-Leste — the conditions that turn a rainfall deficit into need.</li>
      <li><strong>Comparability.</strong> INFORM advises caution comparing the September 2026 midterm release with March 2026 because of unusually large input-data updates.</li>
      <li><strong>Reliability.</strong> Small island states carry the highest INFORM lack-of-reliability scores (Micronesia 7.9, Nauru 7.3, Marshall Islands 6.5).</li>
    </ul>
  </section>`;
}
function wireInform(){
  const rerender=(keep)=>{ const y=window.scrollY; main.innerHTML=viewInform(); wireInform(); window.scrollTo(0,y); if(keep){ const b=document.querySelector(keep); if(b) b.focus(); } };
  document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{ infState.f=b.dataset.f; rerender(`[data-f="${b.dataset.f}"]`); });
  document.querySelectorAll('#infRisk [data-sort]').forEach(b=>b.onclick=()=>{ const k=b.dataset.sort; if(infState.key===k) infState.dir*=-1; else { infState.key=k; infState.dir=k==='name'?1:-1; } rerender(`#infRisk [data-sort="${k}"]`); });
  document.querySelectorAll('#infCc [data-csort]').forEach(b=>b.onclick=()=>{ const k=b.dataset.csort; if(infState.ckey===k) infState.cdir*=-1; else { infState.ckey=k; infState.cdir=k==='name'?1:-1; } rerender(`#infCc [data-csort="${k}"]`); });
  document.querySelectorAll('[data-bar]').forEach(b=>b.onclick=()=>{ infState.bar=b.dataset.bar; document.querySelectorAll('[data-bar]').forEach(x=>x.setAttribute('aria-pressed',String(x===b))); $('#infBars').innerHTML=infBars(); });
  if($('#infDumb')) $('#infDumb').innerHTML=infDumb();
  if(!window.__infRz){ window.__infRz=1; let t; window.addEventListener('resize',()=>{ clearTimeout(t); t=setTimeout(()=>{ if($('#infDumb')) $('#infDumb').innerHTML=infDumb(); },150); }); }
  document.querySelectorAll('[data-hz]').forEach(b=>b.onclick=()=>{ infState.hz=b.dataset.hz; document.querySelectorAll('[data-hz]').forEach(x=>x.setAttribute('aria-pressed',String(x===b))); $('#infDumb').innerHTML=infDumb(); });
}

/* ---------- router ---------- */
function parseHash(){
  let h = location.hash.replace(/^#/, '') || '/';
  let anchor = '';
  const ai = h.indexOf('#'); if(ai>=0){ anchor = h.slice(ai+1); h = h.slice(0,ai); }
  const qi = h.indexOf('?'); let params = new URLSearchParams(qi>=0 ? h.slice(qi+1) : ''); if(qi>=0) h = h.slice(0,qi);
  const parts = h.split('/').filter(Boolean);
  return {parts, params, anchor};
}
function render(){
  const {parts, params, anchor} = parseHash();
  const r = parts[0]||'home';
  let html='', route=r, title=DATA.title;
  const isHome=!parts.length;
  if(isHome) html=viewHome();
  else if(r==='themes') html=viewThemes();
  else if(r==='theme'){ html=viewTheme(parts[1]); route='themes'; title=((themeBySlug[parts[1]]||{}).name||'Theme')+' · '+DATA.title; }
  else if(r==='notes') html=viewNotes(params);
  else if(r==='note'){ html=viewNote(parts[1]); route='notes'; title=((NOTES[parts[1]]||{}).title||'Note')+' · '+DATA.title; }
  else if(r==='tags') html=viewTags();
  else if(r==='sources') html=viewSources(params);
  else if(r==='log') html=viewLog(params);
  else if(r==='about') html=viewAbout();
  else if(r==='inform'){ html=viewInform(); title='INFORM risk · '+DATA.title; }
  else html=viewNotFound('page', r);
  main.innerHTML = html;
  document.title = title;
  document.querySelectorAll('.nav-links a').forEach(a=>a.classList.toggle('active', a.dataset.route===route));
  $('#navLinks').classList.remove('open'); $('#navToggle').setAttribute('aria-expanded','false');
  wireControls(params);
  if(isHome) drawGraph();
  if(r==='inform') wireInform();
  if(anchor){ const el=document.getElementById(anchor); if(el) el.scrollIntoView({block:'start'}); }
  else window.scrollTo(0,0);
}
function go(path, params){ const qs = params ? Array.from(params.entries()).filter(([k,v])=>v).map(([k,v])=>`${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&') : ''; location.hash = path + (qs?'?'+qs:''); }
function wireControls(params){
  const fTheme=$('#fTheme'), fTag=$('#fTag'), fQ=$('#fQ');
  if(fTheme){ const upd=()=>go('/notes', new URLSearchParams({theme:fTheme.value, tag:fTag.value, q:fQ.value})); fTheme.onchange=upd; fTag.onchange=upd; let t; fQ.oninput=()=>{clearTimeout(t); t=setTimeout(upd,250);}; fQ.onkeydown=e=>{ if(e.key==='Enter'){ e.preventDefault(); upd(); } }; }
  const sQ=$('#sQ'); if(sQ){ let t; sQ.oninput=()=>{clearTimeout(t); t=setTimeout(()=>go('/sources', new URLSearchParams({q:sQ.value})),250);}; }
  const lQ=$('#lQ'), lType=$('#lType'); if(lQ){ const upd=()=>go('/log', new URLSearchParams({type:lType.value,q:lQ.value})); lType.onchange=upd; let t; lQ.oninput=()=>{clearTimeout(t); t=setTimeout(upd,250);}; }
  // TOC highlight
  const tocLinks = Array.from(document.querySelectorAll('.toc a[data-anchor]'));
  if(tocLinks.length && 'IntersectionObserver' in window){
    const map = new Map(tocLinks.map(a=>[a.dataset.anchor,a]));
    const io = new IntersectionObserver(entries=>{ entries.forEach(en=>{ if(en.isIntersecting){ tocLinks.forEach(a=>a.classList.remove('cur')); const a=map.get(en.target.id); if(a) a.classList.add('cur'); } }); },{rootMargin:'-60px 0px -70% 0px'});
    map.forEach((a,id)=>{ const el=document.getElementById(id); if(el) io.observe(el); });
  }
}
$('#searchForm').addEventListener('submit', e=>{ e.preventDefault(); const v=$('#q').value.trim(); go('/notes', new URLSearchParams({q:v})); });
$('#navToggle').addEventListener('click', ()=>{ const nl=$('#navLinks'); const open=nl.classList.toggle('open'); $('#navToggle').setAttribute('aria-expanded', open?'true':'false'); });
$('#asof').textContent = (DATA.asof.match(/^As of [^.]+/)||[`As of ${fmtDate(DATA.stats.last_updated)}`])[0];
$('#footer').innerHTML = `<span class="disc">The boundaries and names shown and the designations used in this wiki do not imply official endorsement or acceptance by the United Nations. Figures are transcribed from the cited sources as published; see each note’s Sources block.</span><span><strong>Creation date:</strong> ${esc(DATA.stats.built)}</span><span><strong>Sources:</strong> ${DATA.stats.sources_cited} artefacts in raw/</span><span><strong>Feedback:</strong> OCHA ROAP Information Management</span><span><strong>Links:</strong> www.unocha.org, www.reliefweb.int</span>`;
window.addEventListener('hashchange', render);
render();
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wiki", required=True, help="Path to the Climate_Knowledge_Wiki folder (contains wiki/ and raw/)")
    ap.add_argument("--out", default=str(HERE.parent / "wiki"), help="Output folder for index.html (default: ../wiki)")
    a = ap.parse_args()
    build(Path(a.wiki), Path(a.out))

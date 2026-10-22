#!/usr/bin/env python3
"""
build_situation.py — assembles the El Niño 2026–27 Situation and Impacts pages.

  <out>/index.html            regional overview  (situation_template.html) — the site's main page
  <out>/country/<iso>.html    one page per Tier 1 country profile (profile_template.html + profiles/<ISO>.json)
  The knowledge wiki lives in <out>/wiki/ and is built separately by build_site.py.

Injects the OCHA icon symbols, the OCHA lockup, the boundary data and the Niño 3.4 series.
Masthead, nav, styles and footer are taken from situation_template.html for every page,
so the design stays single-sourced. The nav carries a "Country profiles" dropdown on all pages.

Usage (from the site folder):  python src/build_situation.py
        defaults: --assets ./assets  --out .   (i.e. the folder above src/)
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ORDER = ["PNG", "PHL", "TLS", "SLB", "VUT", "MMR"]
ICONS = ["Alert", "Report", "Trending", "Calendar", "Map", "Country", "People-affected", "Trade-and-market",
         "Anticipatory-action", "Monitoring", "Data", "Document", "Food-Security", "Water-source", "Health",
         "Nutrition", "Drought", "Fire", "Link", "Agriculture", "Education", "Livelihood", "Protection",
         "Internally-displaced", "Respiratory", "Government-office", "Print", "Fishery", "Coordination", "Response",
         "Bookmark"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def js(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def fmt_date(iso):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso or "")
    return f"{int(m[3])} {MONTHS[int(m[2]) - 1]} {m[1]}" if m else (iso or "")


def short_path(p):
    return re.split(r"[—(;]", (p.get("classification") or {}).get("pathway", ""))[0].strip()


def profile_menu(profiles, base, current=None):
    cur = ' aria-current="page"'
    items = "".join(
        f'<li role="none"><a role="menuitem" href="{base}{p["iso"].lower()}.html"'
        f'{cur if p["iso"] == current else ""}><b>{html.escape(p["name"])}</b>'
        f'<small>{html.escape(short_path(p))}</small></a></li>' for p in profiles)
    return (f'<div class="nav-drop{" current" if current else ""}" id="pdrop">'
            '<button type="button" aria-haspopup="true" aria-expanded="false" aria-controls="pmenu">'
            '<svg class="ico" aria-hidden="true"><use href="#i-Country"/></svg>'
            '<span class="long">Country profiles</span><span class="short">Profiles</span></button>'
            f'<ul class="nav-menu" id="pmenu" role="menu" hidden><li class="mh" role="none">Tier 1 — high concern</li>{items}</ul></div>')


DROP_JS = """<script>
(function(){ const d=document.getElementById('pdrop'); if(!d) return; const b=d.querySelector('button'), m=d.querySelector('.nav-menu');
  const items=()=>[...m.querySelectorAll('a')];
  const set=o=>{ b.setAttribute('aria-expanded',String(o)); m.hidden=!o; };
  b.addEventListener('click',e=>{ e.stopPropagation(); const o=m.hidden; set(o); if(o) (m.querySelector('[aria-current]')||items()[0]).focus(); });
  document.addEventListener('click',e=>{ if(!d.contains(e.target)) set(false); });
  d.addEventListener('keydown',e=>{ const it=items(), i=it.indexOf(document.activeElement);
    if(e.key==='Escape'){ set(false); b.focus(); }
    else if(e.key==='ArrowDown'&&!m.hidden){ e.preventDefault(); it[(i+1)%it.length].focus(); }
    else if(e.key==='ArrowUp'&&!m.hidden){ e.preventDefault(); it[(i-1+it.length)%it.length].focus(); }
    else if(e.key==='ArrowDown'&&m.hidden&&e.target===b){ e.preventDefault(); b.click(); } });
})();
</script>
"""


def geo_subset(G, iso):
    """Boundary features around one country, so a profile page carries only what its locator draws."""
    fix = lambda lo: lo + 360 if lo < -20 else lo
    pts = [(fix(lo), la) for ft in G["adm0"]["features"] if ft["properties"].get("iso") == iso
           for pl in ft["geometry"]["coordinates"] for lo, la in pl[0]]
    if not pts:
        return {"adm0": {"type": "FeatureCollection", "features": []}, "unsettled": {"type": "FeatureCollection", "features": []}, "disputed": {"type": "FeatureCollection", "features": []}}
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    pad = max(x1 - x0, y1 - y0) * 1.5 + 8   # generous: the Mapbox map can be panned and zoomed out
    x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
    def coords(ft):
        g = ft["geometry"]
        if g["type"] == "LineString":
            return g["coordinates"]
        return [c for pl in g["coordinates"] for c in pl[0]]
    near = lambda ft: any(x0 < fix(lo) < x1 and y0 < la < y1 for lo, la in coords(ft))
    return {"adm0": {"type": "FeatureCollection", "features": [f for f in G["adm0"]["features"] if near(f)]},
            "unsettled": {"type": "FeatureCollection", "features": [f for f in G["unsettled"]["features"] if near(f)]},
            "disputed": {"type": "FeatureCollection", "features": [f for f in G.get("disputed", {}).get("features", []) if near(f)]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=str(HERE.parent / "assets"))
    ap.add_argument("--out", default=str(HERE.parent))
    a = ap.parse_args()
    import build_site  # reuse the icon / logo loaders of the wiki builder
    build_site.ASSETS = Path(a.assets)
    symbols = build_site.load_icon_symbols(ICONS)
    logo = build_site.load_logo()
    geo_txt = (HERE / "geo_ll.json").read_text(encoding="utf-8")
    G = json.loads(geo_txt)
    nino = (HERE / "nino34_min.json").read_text(encoding="utf-8").replace("</", "<\\/")

    profiles = []
    for f in sorted((HERE / "profiles").glob("*.json")):
        try:
            profiles.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  skipped {f.name}: {e}")
    profiles.sort(key=lambda p: ORDER.index(p["iso"]) if p["iso"] in ORDER else 99)

    tpl = (HERE / "situation_template.html").read_text(encoding="utf-8")
    tpl = tpl.replace("<!--__SYMBOLS__-->", symbols).replace("<!--__LOGO__-->", logo)
    out = Path(a.out)
    (out / "country").mkdir(parents=True, exist_ok=True)

    # ---- regional overview ----
    page = (tpl.replace("<!--__PROFILE_MENU__-->", profile_menu(profiles, "country/"))
               .replace("/*__GEO__*/", geo_txt.replace("</", "<\\/")).replace("/*__NINO__*/", nino)
               .replace("</body>", DROP_JS + "</body>"))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"Built {out / 'index.html'}  {(out / 'index.html').stat().st_size // 1024} KB")

    # ---- country profile pages ----
    shell = tpl[:tpl.index('<main class="wrap">')]
    footer = tpl[tpl.index("</main>") + len("</main>"):tpl.index('<script id="geo"')]
    footer = footer.replace("<strong>Sources:</strong> see Sources section", "<strong>Sources:</strong> cited against each figure and event")
    shell = re.sub(r'href="#(\w+)"', r'href="../index.html#\1"', shell)       # section links go back to the overview
    shell = shell.replace('<a class="wiki" href="wiki/index.html">', '<a class="wiki" href="../wiki/index.html">')
    shell = shell.replace('class="nav-row" id="nav">\n    <a href="../index.html#overview">Overview</a>',
                          'class="nav-row" id="nav">\n    <a href="../index.html">← Regional overview</a>')
    body = (HERE / "profile_template.html").read_text(encoding="utf-8")
    body = body[body.index("-->") + 3:].lstrip()  # drop the authoring comment
    plist = [{"iso": p["iso"], "name": p["name"], "file": p["iso"].lower() + ".html"} for p in profiles]
    for p in profiles:
        c = p.get("classification") or {}
        name = html.escape(p["name"])
        sh = shell.replace("<!--__PROFILE_MENU__-->", profile_menu(profiles, "", p["iso"]))
        sh = re.sub(r"<title>.*?</title>", f"<title>{name}: El Niño 2026–27 country profile</title>", sh, flags=re.S)
        sh = re.sub(r'<div class="kicker">.*?</div>', '<div class="kicker">El Niño 2026–27 · Country profile</div>', sh, count=1, flags=re.S)
        sh = re.sub(r'<h1 class="product-title">.*?</h1>', f'<h1 class="product-title">{name}</h1>', sh, count=1, flags=re.S)
        sub = " · ".join(x for x in [c.get("tier", ""), short_path(p)] if x)
        sh = re.sub(r'<div class="product-subtitle">.*?</div>', f'<div class="product-subtitle">{html.escape(sub)}</div>', sh, count=1, flags=re.S)
        sh = re.sub(r'<div class="asof">As of [^<]*', f'<div class="asof">As of {fmt_date(p.get("as_of"))}', sh, count=1)
        pg = sh + (body.replace("<!--__FOOTER__-->", footer).replace("/*__PROFILE__*/", js(p))
                       .replace("/*__GEO__*/", js(geo_subset(G, p["iso"]))).replace("/*__LIST__*/", js(plist))
                       .replace("</body>", "")) + DROP_JS + "</body>\n</html>\n"
        f = out / "country" / f'{p["iso"].lower()}.html'
        f.write_text(pg, encoding="utf-8")
        print(f"Built {f}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

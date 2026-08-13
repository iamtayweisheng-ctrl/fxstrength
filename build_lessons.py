#!/usr/bin/env python3
"""Render FXStrength lesson pages ("Behind the Move" deep-dives).

Content-driven so ADDING A LESSON = writing ONE file in `lessons/` and re-running
this script (the step the weekly pipeline can later automate). Standard library
only; no pip — same discipline as worker/build_matrix.py.

    lessons/<slug>.md   →   public/behind-the-move/<slug>/index.html
                            public/behind-the-move/index.html  (library index)

FIXED (lives here, in the LAYOUT — write once):
    site header/nav · soft self-selecting signup CTA · related-lessons block ·
    footer · <head> meta + Article/Breadcrumb JSON-LD scaffolding · all styling.

PER-LESSON (swap each issue, in the .md):
    frontmatter metadata + the body (intro → story sections → callouts →
    figures → key takeaways → end-summary cards). See lessons/README.md.
"""

import hashlib
import html
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LESSONS_DIR = ROOT / "lessons"
SITE = "https://fxstrength.org"

# Content sections. Each is a URL segment with its own index page; a content file
# picks its section via `section:` frontmatter (default: behind-the-move).
DEFAULT_SECTION = "behind-the-move"
SECTIONS = {
    "behind-the-move": {
        "name": "Behind the Move",
        "tagline": "Why the market moved — explained.",
        "index_h1": "Why the market moved — explained",
        "index_desc": ("Behind the Move — deep-dives that explain why currencies moved, "
                       "not just what happened. Learn to read the market, not just the headlines."),
        "cover": "/og-behind-the-move.png",
    },
    "the-bigger-picture": {
        "name": "The Bigger Picture",
        "tagline": "A broader view of the economic forces shaping currencies and markets.",
        "index_h1": "The Bigger Picture",
        "index_desc": ("The Bigger Picture — a broader view of the economic forces shaping "
                       "currencies and markets. Evergreen macro frameworks for FX traders."),
        "cover": "/og-the-bigger-picture.png",
    },
    "guides": {
        "name": "Guides",
        "tagline": "Plain-English reference guides for FX traders.",
        "index_h1": "FX Guides",
        "index_desc": ("FXStrength guides — plain-English reference for FX traders: what drives "
                       "each currency, how to read the market, and how the pieces fit together."),
        "cover": "/og-guides.png",
    },
}


def sec_of(meta):
    """The section key for a content file (validated; falls back to default)."""
    return meta["section"] if meta.get("section") in SECTIONS else DEFAULT_SECTION

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ── tiny markdown-subset + frontmatter parsing ──────────────────────────────
def parse_frontmatter(text):
    """Split leading `---` frontmatter (simple `key: value` scalars) from body."""
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip("\n")
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                    v = v[1:-1]
                meta[k.strip()] = v
    return meta, body


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def heading(tag, text):
    """Render an h2/h3 with an auto or explicit `{#id}` anchor (for AEO deep-links)."""
    m = re.search(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$", text)
    if m:
        anchor, text = m.group(1), text[:m.start()].rstrip()
    else:
        anchor = slugify(text)
    return f'<{tag} id="{anchor}">{inline(text)}</{tag}>'


def parse_faq(lines):
    """Parse `### Question` / answer pairs from a block into [(q, a), ...]."""
    items, q, a = [], None, []
    for ln in lines:
        if ln.startswith("### "):
            if q is not None:
                items.append((q, " ".join(a).strip()))
            q, a = ln[4:].strip(), []
        elif ln.strip():
            a.append(ln.strip())
    if q is not None:
        items.append((q, " ".join(a).strip()))
    return items


def extract_faq(body):
    """Pull the :::faq block's Q/A out of the body so head can emit FAQPage schema."""
    m = re.search(r"^:::faq\s*$(.*?)^:::\s*$", body, re.M | re.S)
    return parse_faq(m.group(1).splitlines()) if m else []


def asset_v(name):
    """Short content hash for cache-busting a public asset (?v=<hash>)."""
    try:
        return hashlib.md5((ROOT / "public" / name).read_bytes()).hexdigest()[:8]
    except OSError:
        return "1"


def inline(text):
    """Escape, then apply the inline markdown subset: links, bold, italic, code."""
    out = html.escape(text, quote=False)

    def _link(m):
        href = m.group(2)
        ext = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
        return f'<a href="{html.escape(href, quote=True)}"{ext}>{m.group(1)}</a>'
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\*\w])\*([^*]+)\*(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return out


def render_blocks(lines):
    """Render a list of body lines (headings, paragraphs, lists) to HTML.

    Used both for the top-level body and for the inside of directive blocks.
    Directives (`:::name ... :::`) are handled by the caller in render_body.
    """
    parts, para, li = [], [], []

    def flush_para():
        if para:
            parts.append(f"<p>{inline(' '.join(para).strip())}</p>")
            para.clear()

    def flush_li():
        if li:
            items = "".join(f"<li>{inline(x)}</li>" for x in li)
            parts.append(f"<ul>{items}</ul>")
            li.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_para(); flush_li(); continue
        if line.startswith("### "):
            flush_para(); flush_li()
            parts.append(heading("h3", line[4:].strip()))
        elif line.startswith("## "):
            flush_para(); flush_li()
            parts.append(heading("h2", line[3:].strip()))
        elif line.lstrip().startswith("- "):
            flush_para()
            li.append(line.lstrip()[2:].strip())
        else:
            flush_li()
            para.append(line.strip())
    flush_para(); flush_li()
    return "\n".join(parts)


def parse_attrs(s):
    return dict(re.findall(r'(\w+)="([^"]*)"', s))


def directive_html(name, attrs, inner_lines, ctx):
    """Render a `:::name ...:::` block. `ctx` carries page data (e.g. CTA copy)."""
    if name == "insight":
        tag = attrs.get("tag", "📌 Key Insight")
        return (f'<aside class="insight"><span class="insight-tag">{html.escape(tag)}</span>'
                f'<div class="insight-body">{render_blocks(inner_lines)}</div></aside>')
    if name == "figure":
        src = attrs.get("src", "").strip()
        if not src:
            return ""   # v1: no image supplied → omit the section cleanly (no [TBD])
        cap = attrs.get("caption", "")
        alt = attrs.get("alt", cap)
        figcap = f"<figcaption>{inline(cap)}</figcaption>" if cap else ""
        return (f'<figure class="lesson-figure"><img src="{html.escape(src, quote=True)}" '
                f'alt="{html.escape(alt, quote=True)}" loading="lazy" />{figcap}</figure>')
    if name == "cards":
        # Split inner into ### title -> body cards.
        cards, cur_t, cur_b = [], None, []
        for ln in inner_lines:
            if ln.startswith("### "):
                if cur_t is not None:
                    cards.append((cur_t, cur_b))
                cur_t, cur_b = ln[4:].strip(), []
            else:
                cur_b.append(ln)
        if cur_t is not None:
            cards.append((cur_t, cur_b))
        html_cards = "".join(
            f'<div class="summary-card"><h3>{inline(t)}</h3>{render_blocks(b)}</div>'
            for t, b in cards)
        return f'<div class="summary-cards">{html_cards}</div>'
    if name == "quote":
        return f'<blockquote class="pullquote">{render_blocks(inner_lines)}</blockquote>'
    if name == "flow":
        # A → B → C  (a horizontal transmission chain). Splits on → or ->.
        text = " ".join(l.strip() for l in inner_lines if l.strip())
        steps = [s.strip() for s in re.split(r"→|->", text) if s.strip()]
        arrow = '<span class="flow-arrow" aria-hidden="true">→</span>'
        chain = arrow.join(f'<span class="flow-step">{inline(s)}</span>' for s in steps)
        return f'<div class="flow">{chain}</div>'
    if name == "faq":
        cards = "".join(
            f'<div class="faq-item"><h3>{inline(q)}</h3><p>{inline(a)}</p></div>'
            for q, a in parse_faq(inner_lines))
        return f'<div class="faq">{cards}</div>'
    if name == "cheatsheet":
        # Each `### Title | anchor` starts a scannable card that deep-links to #anchor.
        entries = []
        for ln in inner_lines:
            if ln.startswith("### "):
                t = ln[4:].strip()
                title, anchor = (t.split("|", 1) + [""])[:2] if "|" in t else (t, "")
                entries.append([title.strip(), anchor.strip(), []])
            elif entries:
                entries[-1][2].append(ln)
        cards = ""
        for title, anchor, lines in entries:
            more = (f'<a class="cheat-more" href="#{anchor}">Full breakdown ↓</a>'
                    if anchor else "")
            dc = f' data-ccy="{anchor.upper()}"' if anchor else ""
            cards += (f'<div class="cheat-card"{dc}><h3>{inline(title)}</h3>'
                      f'{render_blocks(lines)}{more}</div>')
        return f'<div class="cheat-grid">{cards}</div>'
    if name == "pairpicker":
        return (
            '<div class="pairpicker" id="pairpicker">'
            '<div class="pp-controls"><span class="pp-lab">Compare a pair:</span>'
            '<select class="pp-select" id="pp-a" aria-label="First currency"></select>'
            '<span class="pp-vs">vs</span>'
            '<select class="pp-select" id="pp-b" aria-label="Second currency"></select></div>'
            '<div class="pp-result" id="pp-result"></div>'
            '<p class="pp-note">When one currency’s drivers are turning stronger and the '
            'other’s weaker, the pair has a clearer story — the '
            '<a href="/">strength meter</a> shows whether it’s actually showing up across the '
            'board. This is education, not a signal.</p></div>')
    if name == "cta":
        return ctx["cta"]
    # Unknown directive: render its contents plainly rather than dropping them.
    return render_blocks(inner_lines)


def render_body(body, ctx):
    """Walk the body line-by-line, peeling out `:::` directive blocks."""
    lines = body.splitlines()
    out, buf, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^:::(\w+)(.*)$", line.strip())
        if m:
            out.append(render_blocks(buf)); buf = []
            name = m.group(1)
            rest = m.group(2).strip()
            # self-closing single-line form, e.g. `:::cta:::`
            if rest.endswith(":::"):
                rest = rest[:-3].strip()
                out.append(directive_html(name, parse_attrs(rest), [], ctx))
                i += 1
                continue
            attrs = parse_attrs(rest)
            inner, i = [], i + 1
            while i < len(lines) and lines[i].strip() != ":::":
                inner.append(lines[i]); i += 1
            i += 1  # skip closing :::
            out.append(directive_html(name, attrs, inner, ctx))
        else:
            buf.append(line); i += 1
    out.append(render_blocks(buf))
    return "\n".join(p for p in out if p)


def fmt_date(iso):
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} {MONTHS[m]} {y}"
    except Exception:
        return iso


def reading_time(body):
    words = len(re.findall(r"\w+", body))
    return max(1, round(words / 200))


# ── the LAYOUT (fixed shell shared by every lesson) ─────────────────────────
def head_html(meta, faq=None):
    sec = sec_of(meta)
    sinfo = SECTIONS[sec]
    slug = meta["slug"]
    url = f"{SITE}/{sec}/{slug}"
    title = meta["title"]
    desc = meta.get("description", meta.get("dek", ""))
    # Social share card — a real PNG (X and most scrapers don't render SVG og:images).
    # Defaults to the section's branded cover; a file may override with a
    # `cover: /img/whatever.png` (or full URL) in frontmatter.
    cover = meta.get("cover", "").strip()
    og_img = (cover if cover.startswith("http") else f"{SITE}{cover}") if cover else f"{SITE}{sinfo['cover']}"
    og_alt = f"{sinfo['name']} — {title}"
    pub = meta.get("date", str(date.today()))
    ld_article = {
        '"@context"': '"https://schema.org"',
        '"@type"': '"Article"',
    }
    # Build JSON-LD by hand (stdlib json would reorder / is fine too, but keep tidy).
    import json
    article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "datePublished": pub,
        "dateModified": meta.get("updated", pub),
        "author": {"@type": "Organization", "name": "FXStrength", "url": SITE + "/"},
        "publisher": {
            "@type": "Organization", "name": "FXStrength",
            "logo": {"@type": "ImageObject", "url": og_img},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "image": og_img,
        "isAccessibleForFree": True,
    }
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "FXStrength", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": sinfo["name"],
             "item": f"{SITE}/{sec}/"},
            {"@type": "ListItem", "position": 3, "name": title, "item": url},
        ],
    }
    faq_ld = ""
    if faq:
        faqpage = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q,
                 "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in faq
            ],
        }
        faq_ld = f'\n  <script type="application/ld+json">{json.dumps(faqpage)}</script>'
    e = lambda s: html.escape(s, quote=True)
    sv, lv = asset_v("styles.css"), asset_v("lessons.css")
    return f"""  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{e(title)} — FXStrength</title>
  <meta name="description" content="{e(desc)}" />
  <meta name="robots" content="index, follow" />
  <meta name="theme-color" content="#0b0f17" />
  <link rel="canonical" href="{url}" />
  <meta property="og:site_name" content="FXStrength" />
  <meta property="og:title" content="{e(title)}" />
  <meta property="og:description" content="{e(desc)}" />
  <meta property="og:type" content="article" />
  <meta property="og:url" content="{url}" />
  <meta property="og:image" content="{og_img}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:type" content="image/png" />
  <meta property="og:image:alt" content="{e(og_alt)}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(desc)}" />
  <meta name="twitter:image" content="{og_img}" />
  <meta name="twitter:image:alt" content="{e(og_alt)}" />
  <link rel="stylesheet" href="/styles.css?v={sv}" />
  <link rel="stylesheet" href="/lessons.css?v={lv}" />
  <script>/* apply saved theme before paint (no flash) */
  try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('fxs_theme')||'dark');}}catch(e){{}}</script>
  <script defer data-domain="fxstrength.org" src="https://plausible.io/js/script.tagged-events.js"></script>
  <script>window.plausible=window.plausible||function(){{(window.plausible.q=window.plausible.q||[]).push(arguments)}}</script>
  <script type="application/ld+json">{json.dumps(article)}</script>
  <script type="application/ld+json">{json.dumps(breadcrumb)}</script>{faq_ld}"""


CTA_HTML = """    <aside class="lesson-cta" id="lesson-cta">
      <h2>New here?</h2>
      <p>Get <strong>Behind the Move</strong> — the free breakdown of
         <em>why</em> the market moved, before you trade it.</p>
      <form id="cta-form" class="capture-form" novalidate>
        <input type="email" id="cta-email" placeholder="you@email.com"
               autocomplete="email" required aria-label="Your email" />
        <button type="submit">Get the free report</button>
      </form>
      <p class="capture-note" id="cta-note">No spam. Unsubscribe anytime.</p>
    </aside>"""

# Brevo endpoint — same list as the homepage capture form (see public/app.js).
CTA_SCRIPT = """  <script>
  (function(){
    var EP='https://95e1cb32.sibforms.com/serve/MUIFAIKhyQh6CGkKVNSeY3PosPVQD4EVB-LtNRAK6boe5Ftk9MfOVfqm8jCWu3t7Vr6jgB3f5szihJ4r_0drvErPkuxB-uBanxXUJqsebdxRjpqi-AM3eH-VtDQaKSWbsWQ54ntlFxGz9vd3mItlg_naooEP1Dfz1PSdgaDhyVoGYkxqmzzpUVlVhE02yNKtBiplU09v5l7Lnq6J8w==';
    function track(g,p){try{window.plausible&&window.plausible(g,p?{props:p}:undefined);}catch(e){}}
    var f=document.getElementById('cta-form');if(!f)return;
    f.addEventListener('submit',function(ev){
      ev.preventDefault();
      var note=document.getElementById('cta-note');
      var email=document.getElementById('cta-email').value.trim();
      if(!/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)){note.textContent='Please enter a valid email.';return;}
      note.textContent='Adding you…';
      try{var fd=new FormData();fd.append('EMAIL',email);fd.append('email_address_check','');fd.append('locale','en');
        fetch(EP,{method:'POST',mode:'no-cors',body:fd});}catch(e){}
      track('Signup',{src:'lesson'});
      note.textContent="You're on the list — your first Behind the Move is on the way.";
      f.reset();
    });
    // Theme toggle — mirrors app.js (key fxs_theme).
    var tb=document.getElementById('theme-toggle');
    if(tb){tb.addEventListener('click',function(){
      var next=document.documentElement.getAttribute('data-theme')==='light'?'dark':'light';
      document.documentElement.setAttribute('data-theme',next);
      try{localStorage.setItem('fxs_theme',next);}catch(e){}
      tb.textContent=next==='light'?'☀':'☾';
    });
    try{tb.textContent=(localStorage.getItem('fxs_theme')||'dark')==='light'?'☀':'☾';}catch(e){}}
  })();
  </script>"""

LIGHTBOX_SCRIPT = """  <script>
  (function(){
    var imgs=document.querySelectorAll('.lesson-figure img');
    if(!imgs.length)return;
    var box=null;
    function close(){ if(box){ box.remove(); box=null; document.body.style.overflow=''; } }
    function open(src,alt){
      box=document.createElement('div'); box.className='lightbox';
      var im=document.createElement('img'); im.src=src; im.alt=alt||'';
      box.appendChild(im); document.body.appendChild(box);
      document.body.style.overflow='hidden';
      box.addEventListener('click',close);
    }
    imgs.forEach(function(im){
      im.setAttribute('tabindex','0'); im.setAttribute('role','button');
      im.setAttribute('aria-label','Enlarge image');
      im.addEventListener('click',function(){ open(im.currentSrc||im.src,im.alt); });
      im.addEventListener('keydown',function(e){
        if(e.key==='Enter'||e.key===' '){ e.preventDefault(); open(im.currentSrc||im.src,im.alt); }
      });
    });
    document.addEventListener('keydown',function(e){ if(e.key==='Escape') close(); });
  })();
  </script>"""

PICKER_SCRIPT = """  <script>
  (function(){
    var pp=document.getElementById('pairpicker'); if(!pp) return;
    var cards={}, order=[];
    document.querySelectorAll('.cheat-card[data-ccy]').forEach(function(c){
      var code=c.getAttribute('data-ccy'); cards[code]=c; order.push(code);
    });
    if(order.length<2) return;
    var a=document.getElementById('pp-a'), b=document.getElementById('pp-b'),
        out=document.getElementById('pp-result');
    function nameOf(code){ var m=cards[code].querySelector('h3').textContent.match(/([A-Za-z ]+)\\(/); return m?m[1].trim():code; }
    order.forEach(function(code){
      [a,b].forEach(function(sel){ var o=document.createElement('option'); o.value=code; o.textContent=code+' — '+nameOf(code); sel.appendChild(o); });
    });
    function render(){ out.innerHTML=''; [a.value,b.value].forEach(function(code){ if(cards[code]) out.appendChild(cards[code].cloneNode(true)); }); }
    a.value = cards['AUD']?'AUD':order[0];
    b.value = cards['CHF']?'CHF':order[1];
    a.addEventListener('change',render); b.addEventListener('change',render);
    render();
  })();
  </script>"""

DISCLAIMER = """      <p class="disclaimer">
        FXStrength provides market information for educational purposes only and is
        <strong>not financial advice</strong>. Nothing here is a recommendation to buy
        or sell. Trading foreign exchange and CFDs carries a high risk of loss.
      </p>"""


def topbar_html():
    links = "".join(f'      <a href="/{k}/">{v["name"]}</a>\n' for k, v in SECTIONS.items())
    return f"""  <header class="topbar">
    <a class="brand" href="/"><span class="logo">▚▚</span> FXStrength</a>
    <nav class="topbar-right lesson-nav">
{links}      <a href="/">Strength meter</a>
      <button class="refresh" id="theme-toggle" title="Light / dark"
              aria-label="Toggle light or dark theme">☾</button>
    </nav>
  </header>"""


def related_html(current, others):
    if not others:
        secname = SECTIONS[sec_of(current)]["name"]
        return (f'<section class="related"><h2>More reading</h2>'
                f'<p class="hint">This is where the library begins. More <em>{html.escape(secname)}</em> '
                f'articles land here as they publish — or '
                f'<a href="/">explore the live strength meter</a> in the meantime.</p></section>')
    cards = ""
    for o in others[:4]:
        osec = sec_of(o)
        cards += (f'<a class="related-card" href="/{osec}/{o["slug"]}">'
                  f'<span class="related-kicker">{html.escape(SECTIONS[osec]["name"])}</span>'
                  f'<span class="related-title">{html.escape(o["title"])}</span>'
                  f'<span class="related-dek">{html.escape(o.get("dek", ""))}</span></a>')
    return f'<section class="related"><h2>More reading</h2><div class="related-grid">{cards}</div></section>'


def render_lesson(meta, body, others):
    sec = sec_of(meta)
    sinfo = SECTIONS[sec]
    ctx = {"cta": CTA_HTML}
    article_body = render_body(body, ctx)
    faq = extract_faq(body)
    kicker = meta.get("kicker") or meta.get("newsletter_issue") or sinfo["name"]
    meta_line_bits = [fmt_date(meta.get("date", "")), f'{reading_time(body)} min read']
    if meta.get("confidence"):
        meta_line_bits.append(f'Confidence: {meta["confidence"]}')
    meta_line = " · ".join(b for b in meta_line_bits if b)
    crumb_last = (f"Issue #{meta['issue_no']}" if meta.get("issue_no")
                  else html.escape(meta["title"]))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{head_html(meta, faq)}
</head>
<body class="lesson-page">
{topbar_html()}
  <main class="lesson">
    <article>
      <nav class="crumbs" aria-label="Breadcrumb">
        <a href="/">FXStrength</a> <span>›</span>
        <a href="/{sec}/">{html.escape(sinfo['name'])}</a> <span>›</span>
        <span>{crumb_last}</span>
      </nav>
      <p class="kicker">{html.escape(kicker)}</p>
      <h1>{html.escape(meta['title'])}</h1>
      <p class="dek">{html.escape(meta.get('dek', ''))}</p>
      <p class="lesson-meta">{html.escape(meta_line)}</p>
      <div class="lesson-body">
{article_body}
      </div>
    </article>
{related_html(meta, others)}
  </main>
  <footer class="foot">
    <p class="foot-news">📬 More from <strong>{html.escape(sinfo['name'])}</strong> —
       <a href="/{sec}/">read the archive</a> or subscribe above.</p>
{DISCLAIMER}
    <p class="src">© FXStrength · <a href="/">fxstrength.org</a></p>
  </footer>
{CTA_SCRIPT}
{LIGHTBOX_SCRIPT}
{PICKER_SCRIPT}
</body>
</html>
"""


def render_index(sec, articles):
    sinfo = SECTIONS[sec]
    items = ""
    for m in articles:
        kick = (f'Issue #{m["issue_no"]} · ' if m.get("issue_no") else "") + fmt_date(m.get("date", ""))
        items += (f'<a class="lib-card" href="/{sec}/{m["slug"]}">'
                  f'<span class="lib-kicker">{html.escape(kick)}</span>'
                  f'<span class="lib-title">{html.escape(m["title"])}</span>'
                  f'<span class="lib-dek">{html.escape(m.get("dek",""))}</span></a>')
    if not items:
        items = '<p class="hint">The first article is on its way.</p>'
    desc = sinfo["index_desc"]
    cover = f'{SITE}{sinfo["cover"]}'
    sv, lv = asset_v("styles.css"), asset_v("lessons.css")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(sinfo["name"])} | FXStrength</title>
  <meta name="description" content="{html.escape(desc, quote=True)}" />
  <link rel="canonical" href="{SITE}/{sec}/" />
  <meta name="theme-color" content="#0b0f17" />
  <meta property="og:title" content="{html.escape(sinfo["name"])} — FXStrength" />
  <meta property="og:description" content="{html.escape(desc, quote=True)}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="{SITE}/{sec}/" />
  <meta property="og:image" content="{cover}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:image" content="{cover}" />
  <link rel="stylesheet" href="/styles.css?v={sv}" />
  <link rel="stylesheet" href="/lessons.css?v={lv}" />
  <script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('fxs_theme')||'dark');}}catch(e){{}}</script>
  <script defer data-domain="fxstrength.org" src="https://plausible.io/js/script.tagged-events.js"></script>
</head>
<body class="lesson-page">
{topbar_html()}
  <main class="lesson lib">
    <header class="lib-head">
      <p class="kicker">{html.escape(sinfo["name"])}</p>
      <h1>{html.escape(sinfo["index_h1"])}</h1>
      <p class="dek">{html.escape(sinfo["tagline"])}</p>
    </header>
    <div class="lib-grid">
{items}
    </div>
{CTA_HTML}
  </main>
  <footer class="foot">
{DISCLAIMER}
    <p class="src">© FXStrength · <a href="/">fxstrength.org</a></p>
  </footer>
{CTA_SCRIPT}
  <script>
  (function(){{var tb=document.getElementById('theme-toggle');if(!tb)return;
    tb.addEventListener('click',function(){{var n=document.documentElement.getAttribute('data-theme')==='light'?'dark':'light';
    document.documentElement.setAttribute('data-theme',n);try{{localStorage.setItem('fxs_theme',n);}}catch(e){{}}tb.textContent=n==='light'?'☀':'☾';}});
    try{{tb.textContent=(localStorage.getItem('fxs_theme')||'dark')==='light'?'☀':'☾';}}catch(e){{}}}})();
  </script>
</body>
</html>
"""


def main():
    files = sorted(p for p in LESSONS_DIR.glob("*.md") if p.stem.lower() != "readme")
    arts = []
    for f in files:
        meta, body = parse_frontmatter(f.read_text(encoding="utf-8"))
        if not meta.get("slug"):
            meta["slug"] = slugify(meta.get("title", f.stem))
        meta["_body"] = body
        arts.append(meta)

    # newest first (by date string; ISO sorts correctly)
    arts.sort(key=lambda m: m.get("date", ""), reverse=True)

    for m in arts:
        sec = sec_of(m)
        # Related: same-section articles first, then the rest (cross-section).
        same = [o for o in arts if o["slug"] != m["slug"] and sec_of(o) == sec]
        cross = [o for o in arts if o["slug"] != m["slug"] and sec_of(o) != sec]
        outdir = ROOT / "public" / sec
        outdir.mkdir(parents=True, exist_ok=True)
        # Flat `<slug>.html` — Cloudflare Pages serves it at the clean URL
        # `/<section>/<slug>` directly (200, no trailing-slash redirect).
        out = outdir / f"{m['slug']}.html"
        out.write_text(render_lesson(m, m["_body"], same + cross), encoding="utf-8")
        print(f"  wrote {out.relative_to(ROOT)}")

    for sec in SECTIONS:
        sec_arts = [m for m in arts if sec_of(m) == sec]
        if not sec_arts:
            continue
        outdir = ROOT / "public" / sec
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "index.html").write_text(render_index(sec, sec_arts), encoding="utf-8")
        print(f"  wrote {(outdir / 'index.html').relative_to(ROOT)}")

    print(f"Done — {len(arts)} article(s) across {len(SECTIONS)} sections.")


if __name__ == "__main__":
    sys.exit(main())

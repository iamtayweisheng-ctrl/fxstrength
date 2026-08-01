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

import html
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LESSONS_DIR = ROOT / "lessons"
OUT_DIR = ROOT / "public" / "behind-the-move"
SECTION = "behind-the-move"          # URL segment + brand ("Behind the Move")
SITE = "https://fxstrength.org"

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


def inline(text):
    """Escape, then apply the inline markdown subset: links, bold, italic, code."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                 lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
                 out)
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
            t = line[4:].strip()
            parts.append(f'<h3 id="{slugify(t)}">{inline(t)}</h3>')
        elif line.startswith("## "):
            flush_para(); flush_li()
            t = line[3:].strip()
            parts.append(f'<h2 id="{slugify(t)}">{inline(t)}</h2>')
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
        return (f'<aside class="insight"><span class="insight-tag">📌 Key Insight</span>'
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
def head_html(meta):
    slug = meta["slug"]
    url = f"{SITE}/{SECTION}/{slug}"
    title = meta["title"]
    desc = meta.get("description", meta.get("dek", ""))
    og_img = f"{SITE}/og.svg"
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
            {"@type": "ListItem", "position": 2, "name": "Behind the Move",
             "item": f"{SITE}/{SECTION}/"},
            {"@type": "ListItem", "position": 3, "name": title, "item": url},
        ],
    }
    e = lambda s: html.escape(s, quote=True)
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
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{e(title)}" />
  <meta name="twitter:description" content="{e(desc)}" />
  <meta name="twitter:image" content="{og_img}" />
  <link rel="stylesheet" href="/styles.css" />
  <link rel="stylesheet" href="/lessons.css" />
  <script>/* apply saved theme before paint (no flash) */
  try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('fxs_theme')||'dark');}}catch(e){{}}</script>
  <script defer data-domain="fxstrength.org" src="https://plausible.io/js/script.tagged-events.js"></script>
  <script>window.plausible=window.plausible||function(){{(window.plausible.q=window.plausible.q||[]).push(arguments)}}</script>
  <script type="application/ld+json">{json.dumps(article)}</script>
  <script type="application/ld+json">{json.dumps(breadcrumb)}</script>"""


CTA_HTML = """    <aside class="lesson-cta" id="lesson-cta">
      <h2>New here?</h2>
      <p>Get <strong>Behind the Move</strong> — the weekly report that explains
         <em>why</em> the market moved, before you trade it.</p>
      <form id="cta-form" class="capture-form" novalidate>
        <input type="email" id="cta-email" placeholder="you@email.com"
               autocomplete="email" required aria-label="Your email" />
        <button type="submit">Get the free report</button>
      </form>
      <p class="capture-note" id="cta-note">One email a week. No spam. Unsubscribe anytime.</p>
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

DISCLAIMER = """      <p class="disclaimer">
        FXStrength provides market information for educational purposes only and is
        <strong>not financial advice</strong>. Nothing here is a recommendation to buy
        or sell. Trading foreign exchange and CFDs carries a high risk of loss.
      </p>"""


def topbar_html():
    return f"""  <header class="topbar">
    <a class="brand" href="/"><span class="logo">▚▚</span> FXStrength</a>
    <nav class="topbar-right lesson-nav">
      <a href="/{SECTION}/">Behind the Move</a>
      <a href="/">Strength meter</a>
      <button class="refresh" id="theme-toggle" title="Light / dark"
              aria-label="Toggle light or dark theme">☾</button>
    </nav>
  </header>"""


def related_html(current, others):
    if not others:
        return (f'<section class="related"><h2>More lessons</h2>'
                f'<p class="hint">This is where the library begins. New <em>Behind the Move</em> '
                f'lessons land here every week — or '
                f'<a href="/">explore the live strength meter</a> in the meantime.</p></section>')
    cards = ""
    for o in others[:4]:
        cards += (f'<a class="related-card" href="/{SECTION}/{o["slug"]}">'
                  f'<span class="related-kicker">Behind the Move</span>'
                  f'<span class="related-title">{html.escape(o["title"])}</span>'
                  f'<span class="related-dek">{html.escape(o.get("dek", ""))}</span></a>')
    return f'<section class="related"><h2>More lessons</h2><div class="related-grid">{cards}</div></section>'


def render_lesson(meta, body, others):
    ctx = {"cta": CTA_HTML}
    article_body = render_body(body, ctx)
    kicker = meta.get("newsletter_issue", "Behind the Move")
    meta_line_bits = [fmt_date(meta.get("date", ""))]
    meta_line_bits.append(f'{reading_time(body)} min read')
    if meta.get("confidence"):
        meta_line_bits.append(f'Confidence: {meta["confidence"]}')
    meta_line = " · ".join(b for b in meta_line_bits if b)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
{head_html(meta)}
</head>
<body class="lesson-page">
{topbar_html()}
  <main class="lesson">
    <article>
      <nav class="crumbs" aria-label="Breadcrumb">
        <a href="/">FXStrength</a> <span>›</span>
        <a href="/{SECTION}/">Behind the Move</a> <span>›</span>
        <span>Issue #{meta.get('issue_no', '')}</span>
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
    <p class="foot-news">📬 <strong>Behind the Move</strong> lands every week —
       <a href="/{SECTION}/">read the archive</a> or subscribe above.</p>
{DISCLAIMER}
    <p class="src">© FXStrength · <a href="/">fxstrength.org</a></p>
  </footer>
{CTA_SCRIPT}
</body>
</html>
"""


def render_index(lessons):
    items = ""
    for m in lessons:
        items += (f'<a class="lib-card" href="/{SECTION}/{m["slug"]}">'
                  f'<span class="lib-kicker">Issue #{m.get("issue_no","")} · {fmt_date(m.get("date",""))}</span>'
                  f'<span class="lib-title">{html.escape(m["title"])}</span>'
                  f'<span class="lib-dek">{html.escape(m.get("dek",""))}</span></a>')
    if not items:
        items = '<p class="hint">The first lesson is on its way.</p>'
    desc = ("Behind the Move — weekly deep-dives that explain why currencies moved, "
            "in plain English. Learn to read the market, not just the headlines.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Behind the Move — Why the Market Moved | FXStrength</title>
  <meta name="description" content="{html.escape(desc, quote=True)}" />
  <link rel="canonical" href="{SITE}/{SECTION}/" />
  <meta name="theme-color" content="#0b0f17" />
  <meta property="og:title" content="Behind the Move — FXStrength" />
  <meta property="og:description" content="{html.escape(desc, quote=True)}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="{SITE}/{SECTION}/" />
  <meta property="og:image" content="{SITE}/og.svg" />
  <link rel="stylesheet" href="/styles.css" />
  <link rel="stylesheet" href="/lessons.css" />
  <script>try{{document.documentElement.setAttribute('data-theme',localStorage.getItem('fxs_theme')||'dark');}}catch(e){{}}</script>
  <script defer data-domain="fxstrength.org" src="https://plausible.io/js/script.tagged-events.js"></script>
</head>
<body class="lesson-page">
{topbar_html()}
  <main class="lesson lib">
    <header class="lib-head">
      <p class="kicker">Behind the Move</p>
      <h1>Why the market moved — explained</h1>
      <p class="dek">{html.escape(desc)}</p>
    </header>
    <div class="lib-grid">
{items}
    </div>
  </main>
  <footer class="foot">
{DISCLAIMER}
    <p class="src">© FXStrength · <a href="/">fxstrength.org</a></p>
  </footer>
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
    lessons = []
    for f in files:
        meta, body = parse_frontmatter(f.read_text(encoding="utf-8"))
        if not meta.get("slug"):
            meta["slug"] = slugify(meta.get("title", f.stem))
        meta["_body"] = body
        lessons.append(meta)

    # newest first (by date string; ISO sorts correctly)
    lessons.sort(key=lambda m: m.get("date", ""), reverse=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for m in lessons:
        others = [o for o in lessons if o["slug"] != m["slug"]]
        out = OUT_DIR / m["slug"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_lesson(m, m["_body"], others), encoding="utf-8")
        print(f"  wrote {out.relative_to(ROOT)}")

    (OUT_DIR / "index.html").write_text(render_index(lessons), encoding="utf-8")
    print(f"  wrote {(OUT_DIR / 'index.html').relative_to(ROOT)}")
    print(f"Done — {len(lessons)} lesson(s).")


if __name__ == "__main__":
    sys.exit(main())

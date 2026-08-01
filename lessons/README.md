# Lessons — "Behind the Move" deep-dives

**Adding a lesson = write ONE file here, then run the build.** That single-file-add
is what lets the weekly pipeline be automated later.

```bash
python build_lessons.py     # renders lessons/*.md → public/behind-the-move/**
git add lessons public/behind-the-move && git commit && git push
```

Cloudflare Pages serves `public/` directly (no build step on their side), so the
generated HTML is committed. Live URL: `https://fxstrength.org/behind-the-move/<slug>`.

## What's FIXED (in `build_lessons.py`, the layout — you don't touch per lesson)
Site header/nav · theme toggle · the soft self-selecting signup **CTA** · related-lessons
block · footer · `<head>` meta + Article/Breadcrumb JSON-LD · all styling (`public/lessons.css`).

## What's PER-LESSON (this file)
Frontmatter metadata + the body content.

### Frontmatter (all scalar `key: value`)
| key | notes |
|-----|-------|
| `title` | H1, question-style (SEO/AEO). |
| `dek` | one-line sub-headline. |
| `slug` | URL slug (optional; derived from title if omitted). |
| `date` | `YYYY-MM-DD`. |
| `issue_no`, `lesson_no` | integers. |
| `description` | meta description. |
| `summary` | one-paragraph TL;DR (not yet rendered on page; kept for future use / snippets). |
| `newsletter_issue` | kicker line, e.g. `Behind the Move · Issue #001 · Week 31, 2026`. |
| `confidence` | `High` / `Medium` / `Low` (per the editorial constitution). |

### Body (markdown subset + directives)
- Text **before the first `##`** = the intro.
- `## Heading` / `### Heading` — section headings (auto-anchored).
- `**bold**`, `*italic*`, `[link](url)`, `` `code` ``, and `- ` bullet lists.
- Standard story order: **What Happened · Why Expectations Changed · What Price Is
  Saying · FXStrength Perspective · The Lesson · Key Takeaways**.

Directive blocks:
```
:::insight
📌 Key-Insight pull-quote. **Bold** works inside.
:::

:::cta:::                         ← place the signup box ONCE, mid/late in the page

:::figure src="/img/foo.png" alt="…" caption="…"
:::                                ← empty src="" ⇒ the figure is OMITTED (clean text-v1)

:::cards
### What You Learned
…
### What Price Is Saying
…
### How FXStrength Helps
…
:::                                ← end-summary cards
```

## Pre-publish gates (per the build brief)
1. No production-notes / "suggested visuals" block in the body (reader content only).
2. Figures: supply a real `src`, or leave `src=""` to omit — never ship a placeholder.
3. No `[TBD]` / "likely" numbers on a live page — fill real values or remove.
4. Facts verified; keep the "What Price Is Saying" section **educational** (what a move
   *tells us*), never entries/levels/calls.

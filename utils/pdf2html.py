#!/usr/bin/env python3
"""Convert slide-deck PDFs into HTML pages.

For each NAME.pdf this writes NAME.html plus NAME/slide-NN.jpg: every slide
is rendered as an image (so it looks like the original), and the slide's
text goes in the image's alt text so the page stays searchable and readable
by screen readers.

Requires PyMuPDF (pip install pymupdf).

Usage: python3 utils/pdf2html.py [NAME.pdf ...]   (default: all *.pdf here)
"""

import functools
import glob
import html
import os
import re
import sys
import unicodedata

import pymupdf

SLIDE_WIDTH = 1200  # pixels; sharp at the 960px page width, modest size
JPEG_QUALITY = 72
STYLESHEET = "slides.css"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | The Great Transformation</title>
  <link rel="stylesheet" href="{stylesheet}">
</head>
<body>
  <header>
    <p class="home"><a href="index.html">&larr; The Great Transformation</a></p>
    <h1>{title}</h1>
    <p><a href="{pdf}">Download PDF</a> &middot; {count} slides</p>
  </header>
  <main>
{slides}
  </main>
</body>
</html>
"""

SLIDE = """    <figure id="slide-{n}">
      <img src="{src}" width="{w}" height="{h}" alt="{alt}"{lazy}>
      <figcaption><a href="#slide-{n}">{n}</a></figcaption>
    </figure>"""


def is_bullet(ch):
    """True for bullet glyphs: symbols (◼, ⬧, ...), the private-use
    characters Keynote/PowerPoint symbol fonts produce, and • ◦ › –."""
    return (unicodedata.category(ch) in ("So", "Sm", "Co")
            or ch in "•◦‣›»–") and ch not in "+=<>"


def line_text(line):
    """A line's text (minus any leading bullet glyph), its bullet as
    (glyph, x) or "" if none, and candidate x positions where the text
    column starts.

    Some slides were exported with wide letter tracking
    ('B o r n  in  T r ie r'); for those, keep only the spaces that span a
    word-sized gap."""
    chars = [c for span in line["spans"] for c in span["chars"]]
    size = max(span["size"] for span in line["spans"])
    bullet = ""
    while chars and is_bullet(chars[0]["c"]):
        bullet = bullet or (chars[0]["c"], chars[0]["bbox"][0])
        chars.pop(0)
    # The text column starts after the bullet and the tab that follows it,
    # but the tab's extracted box is unreliable: wrapped lines may line up
    # with either its start or the first letter. Keep both candidates.
    xs = [chars[0]["bbox"][0]] if chars else []
    while chars and chars[0]["c"].isspace():
        chars.pop(0)
    if not chars:
        return "", bullet, xs
    xs.append(chars[0]["bbox"][0])

    gaps, prev_x1, after_space = [], None, False
    for c in chars:
        if c["c"].isspace():
            after_space = True
        else:
            if prev_x1 is not None and after_space:
                gaps.append((c["bbox"][0] - prev_x1) / size)
            prev_x1, after_space = c["bbox"][2], False
    # Letter-spaced lines are mostly 1-2 character "words" separated by
    # narrow gaps, with real word breaks noticeably wider.
    tokens = "".join(c["c"] for c in chars).split()
    letter_spaced = (len(tokens) >= 4
                     and sum(len(t) <= 2 for t in tokens) > 0.6 * len(tokens)
                     and sorted(gaps)[len(gaps) // 2] < 0.21)

    out, gap, started, after_space = [], iter(gaps), False, False
    for c in chars:
        if c["c"].isspace():
            after_space = True
            continue
        if started and after_space:
            if not letter_spaced or next(gap) > 0.35:
                out.append(" ")
        out.append(c["c"])
        started, after_space = True, False
    return "".join(out), bullet, xs


def same_row(a, b):
    """True if two line boxes mostly overlap vertically."""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap > 0.5 * min(a[3] - a[1], b[3] - b[1])


def reading_order(blocks):
    """Sort blocks top to bottom, except that side-by-side blocks (columns)
    are read left to right."""
    def compare(a, b):
        (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["bbox"], b["bbox"]
        if same_row(a["bbox"], b["bbox"]):
            if ax1 <= bx0 + 2:
                return -1
            if bx1 <= ax0 + 2:
                return 1
        return (ay0, ax0) > (by0, bx0) or -((ay0, ax0) < (by0, bx0))
    return sorted(blocks, key=functools.cmp_to_key(compare))


def slide_items(page):
    """The slide's text as a list of items (title, bullets, paragraphs) in
    reading order, with wrapped lines rejoined."""
    items = []  # each: [text, text_xs, has_bullet, last_bbox, size]
    pending_bullet = None  # a bullet glyph extracted as its own line
    for block in reading_order(page.get_text("rawdict")["blocks"]):
        for line in block.get("lines", []):
            text, bullet, xs = line_text(line)
            if not text:
                if bullet:
                    pending_bullet = line["bbox"]
                continue
            if pending_bullet and same_row(line["bbox"], pending_bullet):
                bullet = ("•", pending_bullet[0])
            pending_bullet = None
            # A dash lined up with the text column above is a dash in the
            # text ('Roughly 1000 / – 1300 CE'), not a sub-bullet.
            if (bullet and bullet[0] == "–" and items
                    and any(abs(bullet[1] - x) < 4 for x in items[-1][1])):
                text, xs, bullet = "– " + text, [bullet[1]], ""
            bbox = line["bbox"]
            size = line["spans"][0]["size"]
            if items:
                prev = items[-1]
                pbox = prev[3]
                if not bullet and same_row(bbox, pbox):
                    # One line split into separate pieces.
                    sep = "" if bbox[0] - pbox[2] < 0.2 * size else " "
                    prev[0] += sep + text
                    prev[3] = (pbox[0], min(bbox[1], pbox[1]), bbox[2],
                               max(bbox[3], pbox[3]))
                    continue
                # A wrapped line: lined up with the text above, no bullet of
                # its own, and either the item above is a bullet (so a new
                # item would have one too), or it continues mid-sentence.
                aligned = any(abs(xs[-1] - x) < 4 for x in prev[1])
                continues = (prev[2] or text[0].islower()
                             or re.search(r"[-–—,]$", prev[0]))
                # Centered text doesn't line up, so also accept a lowercase
                # line directly below one in the same size type, or any such
                # line in title-sized type.
                below = (abs(size - prev[4]) < 1
                         and -0.5 * size <= bbox[1] - pbox[3] < 0.6 * size)
                title = below and size >= 30 and not re.search(
                    r"[.!?:]$", prev[0])
                if not bullet and (title or continues and (
                        aligned or (below and text[0].islower()))):
                    sep = "" if re.search(r"\w-$", prev[0]) else " "
                    prev[0] += sep + text
                    prev[3] = bbox
                    continue
            items.append([text, xs, bullet, bbox, size])
    return [item[0] for item in items]


def alt_text(items):
    """Join items into readable alt text; items without closing punctuation
    get a period so screen readers pause between them."""
    parts = []
    for item in items:
        if parts and not re.search(r"[.!?:;,…–—\"”’)]$", parts[-1]):
            parts[-1] += "."
        parts.append(item)
    return " ".join(parts)


def convert(pdf_path):
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc = pymupdf.open(pdf_path)
    title = (doc.metadata.get("title") or "").strip() or name
    os.makedirs(name, exist_ok=True)
    for old in glob.glob(os.path.join(name, "slide-*.jpg")):
        os.remove(old)

    slides = []
    for i, page in enumerate(doc, start=1):
        zoom = SLIDE_WIDTH / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        src = f"{name}/slide-{i:02d}.jpg"
        with open(src, "wb") as f:
            f.write(pix.tobytes("jpg", jpg_quality=JPEG_QUALITY))
        alt = alt_text(slide_items(page)) or (title if i == 1 else f"Slide {i}")
        slides.append(SLIDE.format(
            n=i, src=src, w=pix.width, h=pix.height,
            alt=html.escape(alt, quote=True),
            lazy="" if i == 1 else ' loading="lazy"'))

    with open(f"{name}.html", "w", encoding="utf-8") as f:
        f.write(PAGE.format(
            title=html.escape(title), stylesheet=STYLESHEET,
            pdf=f"{name}.pdf", count=len(slides), slides="\n".join(slides)))
    print(f"{name}.html: {len(slides)} slides")


def main():
    pdfs = sys.argv[1:] or sorted(glob.glob("*.pdf"))
    for pdf in pdfs:
        convert(pdf)


if __name__ == "__main__":
    main()

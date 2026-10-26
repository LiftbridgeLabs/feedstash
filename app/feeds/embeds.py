"""Feed HTML extras that survive sanitizing: video embeds as links, and runs of pictures as galleries. No I/O.

Readers never run a feed's iframes (feedparser drops them, and the web app and the phone show articles without
scripts), so an embedded video used to vanish. `video_links` runs on the raw HTML first and turns YouTube and Vimeo
players into a thumbnail and a link to the video. `galleries` runs on the sanitized HTML and wraps two or more pictures
in a row in `<div class="fs-gallery">`, which the readers show as a strip to swipe through.
"""

import html
import re

_IFRAME_RE = re.compile(r"<iframe\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1[^>]*>(?:[^<]*</iframe\s*>)?", re.I | re.S)
_YOUTUBE_RE = re.compile(
    r"^(?:https?:)?//(?:www\.)?(?:youtube\.com|youtube-nocookie\.com)/embed/([A-Za-z0-9_-]{11})(?:[?#/]|$)", re.I
)
_VIMEO_RE = re.compile(r"^(?:https?:)?//player\.vimeo\.com/video/(\d{1,12})(?:[?#/]|$)", re.I)


def video_links(raw: str) -> str:
    """YouTube and Vimeo players as links readers can open. Other iframes are left for the sanitizer to drop."""
    if "<iframe" not in raw.lower():
        return raw

    def replace(match: re.Match) -> str:
        src = html.unescape(match.group(2)).strip()
        if youtube := _YOUTUBE_RE.match(src):
            watch = f"https://www.youtube.com/watch?v={youtube.group(1)}"
            thumb = f"https://i.ytimg.com/vi/{youtube.group(1)}/hqdefault.jpg"
            return (f'<p class="fs-video"><a href="{watch}"><img src="{thumb}" alt="Video on YouTube"></a><br>'
                    f'<a href="{watch}">▶ Watch on YouTube</a></p>')
        if vimeo := _VIMEO_RE.match(src):
            return f'<p class="fs-video"><a href="https://vimeo.com/{vimeo.group(1)}">▶ Watch on Vimeo</a></p>'
        return match.group(0)

    return _IFRAME_RE.sub(replace, raw)


_PICTURE = r"(?:<a\b[^>]*>\s*<img\b[^>]*>\s*</a>|<img\b[^>]*>)"
# One picture: bare, in a paragraph of its own, or in a figure (with or without a caption).
_UNIT = (rf"(?:<p>\s*{_PICTURE}\s*</p>|<figure>\s*{_PICTURE}\s*(?:<figcaption>(?:(?!</figure>).){{0,500}}?</figcaption>\s*)?</figure>"
         rf"|{_PICTURE})")
_GAP = r"(?:\s|<br\s*/?>)*"
_RUN_RE = re.compile(rf"{_UNIT}(?:{_GAP}{_UNIT})+", re.I | re.S)
_UNIT_RE = re.compile(_UNIT, re.I | re.S)


def galleries(clean: str) -> str:
    """Two or more pictures in a row, with nothing but space or line breaks between, as one gallery."""
    if clean.lower().count("<img") < 2:
        return clean
    return _RUN_RE.sub(lambda run: f'<div class="fs-gallery">{"".join(_UNIT_RE.findall(run.group(0)))}</div>', clean)

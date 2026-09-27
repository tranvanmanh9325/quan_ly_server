"""
web_article_extractor.py — Clean Web Article Content & Metadata Extractor.

Extracts sanitized, readable article content and structured metadata from arbitrary
web pages, blogs, and news sites (VnExpress, Dan Tri, Tuoi Tre, Medium, Dev.to, Wikipedia):
- Lightweight HTTP retrieval via httpx.AsyncClient (< 5MB RAM overhead).
- Native DOM sanitization pipeline removing <script>, <style>, <nav>, <footer>, <aside>,
  ads, popups, and tracking banners using Python's standard html.parser.
- Markdown conversion preserving semantic structure (Headings, Paragraphs, Lists, Blockquotes, Code, Tables).
- Autonomous fallback to BrowserAgentService for client-rendered SPA / JS-heavy pages.
"""

from __future__ import annotations

from html.parser import HTMLParser
import html
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# Elements to completely strip along with all their inner contents
FORBIDDEN_TAGS: Set[str] = {
    "script", "style", "nav", "footer", "aside", "header",
    "noscript", "iframe", "svg", "canvas", "audio", "video",
    "template", "form", "button", "select", "textarea", "input",
    "dialog", "menu",
}

# Regex pattern matching intrusive ad / tracking / popup / social class and id attributes
NOISE_PATTERN = re.compile(
    r"\b(ad|ads|advert|advertisement|banner|popup|modal|cookie|consent|"
    r"social-share|share-box|sidebar|comment|comments|tracking|widget|"
    r"newsletter|subscribe|promo|promotions)\b",
    re.IGNORECASE,
)

# Standard desktop User-Agent header
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}


class ArticleNode:
    """Represents a sanitized node in the simplified DOM tree."""
    def __init__(self, tag: str, attrs: Dict[str, str]):
        self.tag = tag.lower()
        self.attrs = attrs
        self.children: List[Any] = []  # Can contain ArticleNode or str
        self.parent: Optional[ArticleNode] = None

    def add_child(self, child: Any) -> None:
        if isinstance(child, ArticleNode):
            child.parent = self
        self.children.append(child)

    def get_text(self) -> str:
        """Recursively extracts plain text from this node and its children."""
        parts = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif isinstance(child, ArticleNode):
                parts.append(child.get_text())
        return " ".join("".join(parts).split())


class CleanArticleParser(HTMLParser):
    """
    Sanitizing streaming HTML parser based on standard Python html.parser.
    Constructs a clean semantic representation while stripping noisy elements.
    """
    def __init__(self):
        super().__init__()
        self.title: str = ""
        self.author: str = ""
        self.publish_date: str = ""
        self.meta_tags: Dict[str, str] = {}
        
        self.root = ArticleNode("root", {})
        self.current_node = self.root
        self.ignored_stack: List[str] = []
        self._in_title_tag = False
        self._title_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        # Collect meta tags for metadata extraction
        if tag_lower == "meta":
            prop = attr_dict.get("property", "") or attr_dict.get("name", "")
            content = attr_dict.get("content", "")
            if prop and content:
                self.meta_tags[prop.lower()] = content.strip()
            return

        if tag_lower == "title":
            self._in_title_tag = True
            return

        # If currently inside an ignored subtree, increment stack
        if self.ignored_stack:
            self.ignored_stack.append(tag_lower)
            return

        # Check if tag is strictly forbidden
        if tag_lower in FORBIDDEN_TAGS:
            self.ignored_stack.append(tag_lower)
            return

        # Check if class or id contains noise keywords
        class_str = attr_dict.get("class", "")
        id_str = attr_dict.get("id", "")
        if NOISE_PATTERN.search(class_str) or NOISE_PATTERN.search(id_str):
            # Exclude false positives like "post-body", "article-content"
            combined = f"{class_str} {id_str}".lower()
            if not ("article" in combined or "content" in combined or "entry" in combined or "post" in combined):
                self.ignored_stack.append(tag_lower)
                return

        node = ArticleNode(tag_lower, attr_dict)
        self.current_node.add_child(node)
        self.current_node = node

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower == "title":
            self._in_title_tag = False
            if not self.title and self._title_buffer:
                self.title = " ".join("".join(self._title_buffer).split())
            return

        if self.ignored_stack:
            self.ignored_stack.pop()
            return

        if self.current_node.parent and self.current_node.tag == tag_lower:
            self.current_node = self.current_node.parent

    def handle_data(self, data: str) -> None:
        if self._in_title_tag:
            self._title_buffer.append(data)
            return

        if self.ignored_stack:
            return

        text = html.unescape(data)
        if text:
            self.current_node.add_child(text)


def node_to_markdown(node: ArticleNode, depth: int = 0) -> str:
    """
    Recursively renders an ArticleNode to sanitized Markdown text.
    """
    tag = node.tag
    rendered_children = []

    for child in node.children:
        if isinstance(child, str):
            rendered_children.append(child)
        elif isinstance(child, ArticleNode):
            rendered_children.append(node_to_markdown(child, depth + 1))

    inner = "".join(rendered_children).strip()
    if not inner and tag not in ("hr", "br"):
        return ""

    if tag == "h1":
        return f"\n\n# {inner}\n\n"
    if tag == "h2":
        return f"\n\n## {inner}\n\n"
    if tag == "h3":
        return f"\n\n### {inner}\n\n"
    if tag in ("h4", "h5", "h6"):
        return f"\n\n#### {inner}\n\n"
    if tag == "p":
        return f"\n\n{inner}\n\n"
    if tag == "blockquote":
        lines = inner.splitlines()
        quoted = "\n".join(f"> {line}" for line in lines if line.strip())
        return f"\n\n{quoted}\n\n"
    if tag in ("ul", "ol"):
        return f"\n\n{inner}\n\n"
    if tag == "li":
        return f"\n* {inner}"
    if tag == "pre" or (tag == "code" and "\n" in inner):
        # Strip backticks if already applied by child code tag
        clean_code = inner.strip("`").strip()
        return f"\n\n```\n{clean_code}\n```\n\n"
    if tag == "code":
        # If inside a <pre> block, do not wrap with inline backticks
        if node.parent and node.parent.tag == "pre":
            return inner
        return f" `{inner}` "
    if tag in ("b", "strong"):
        return f" **{inner}** "
    if tag in ("i", "em"):
        return f" *{inner}* "
    if tag == "a":
        href = node.attrs.get("href", "").strip()
        if href and not href.startswith(("#", "javascript:", "data:", "mailto:")):
            return f" [{inner}]({href}) "
        return inner
    if tag == "tr":
        cols = [c.strip() for c in inner.split("\t") if c.strip()]
        if cols:
            return "| " + " | ".join(cols) + " |\n"
        return f"{inner}\n"
    if tag in ("td", "th"):
        return f"{inner}\t"
    if tag == "table":
        return f"\n\n{inner}\n\n"
    if tag == "br":
        return "\n"
    if tag == "hr":
        return "\n\n---\n\n"

    return inner


def select_best_article_content(root: ArticleNode) -> str:
    """
    Finds the main content subtree (<article>, <main>, or highest text density container)
    and converts it to clean Markdown.
    """
    # 1. Check for explicit semantic containers: <article> or <main>
    candidate_nodes: List[ArticleNode] = []

    def find_candidates(n: ArticleNode):
        if n.tag in ("article", "main") or n.attrs.get("role") == "main":
            candidate_nodes.append(n)
        for c in n.children:
            if isinstance(c, ArticleNode):
                find_candidates(c)

    find_candidates(root)

    best_node: Optional[ArticleNode] = None
    if candidate_nodes:
        # Choose candidate with the most textual content
        best_node = max(candidate_nodes, key=lambda n: len(n.get_text()))

    # If no semantic container or candidate has very little text, search for densest div
    if not best_node or len(best_node.get_text()) < 100:
        div_candidates: List[Tuple[ArticleNode, int, int]] = []  # (node, text_len, p_count)

        def score_nodes(n: ArticleNode):
            if n.tag in ("div", "section"):
                txt = n.get_text()
                p_count = sum(1 for c in n.children if isinstance(c, ArticleNode) and c.tag == "p")
                if len(txt) > 100 and p_count >= 1:
                    div_candidates.append((n, len(txt), p_count))
            for c in n.children:
                if isinstance(c, ArticleNode):
                    score_nodes(c)

        score_nodes(root)

        if div_candidates:
            # Score by text length with bonus for paragraph tags
            div_candidates.sort(key=lambda item: item[1] + (item[2] * 200), reverse=True)
            best_node = div_candidates[0][0]
        else:
            best_node = root

    raw_md = node_to_markdown(best_node)

    # Clean whitespace and multiple blank lines
    cleaned_md = re.sub(r"[ \t]+", " ", raw_md)
    cleaned_md = re.sub(r"\n{3,}", "\n\n", cleaned_md)
    return cleaned_md.strip()


class WebArticleExtractor:
    """
    Autonomous Web Article and News Content Extractor with HTML sanitization
    and BrowserAgent fallback for SPA/JavaScript-rendered sites.
    """

    def __init__(self, request_timeout: float = 15.0):
        self.request_timeout = request_timeout

    async def _fetch_html_direct(self, url: str) -> Tuple[str, Dict[str, str]]:
        """Fetches raw HTML via httpx with modern desktop headers and auto-encoding."""
        timeout_cfg = httpx.Timeout(self.request_timeout, connect=10.0)
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout_cfg, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text, dict(resp.headers)

    async def _fetch_html_via_browser_agent(self, url: str) -> Optional[str]:
        """
        Fallback renderer using BrowserAgentService (Playwright headless Chromium)
        for Single-Page Applications (SPAs) or JS-protected sites.
        """
        try:
            from app.services.browser_agent import BrowserAgentService
            agent = BrowserAgentService()
            # If the service provides a render or page-content helper
            if hasattr(agent, "get_page_content"):
                return await agent.get_page_content(url)
            elif hasattr(agent, "_get_or_create_context"):
                context = await agent._get_or_create_context()
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    content = await page.content()
                    return content
                finally:
                    await page.close()
        except Exception as exc:
            logger.debug("[WebArticle] BrowserAgent fallback unavailable: %s", exc)
        return None

    async def extract_clean_web_article(self, url: str) -> Dict[str, Any]:
        """
        Main entry point for extracting clean article content from an arbitrary web URL.
        Returns a dictionary with status, title, author, publish_date, word_count, reading_time_min,
        and clean Markdown content.
        """
        if not url or not url.strip():
            return {
                "status": "error",
                "message": "URL không được để trống.",
            }

        url = url.strip()
        start_time = time.time()
        source = "http_direct"
        raw_html: str = ""

        try:
            # Tier 1: Fast direct HTTP fetch (< 5MB RAM overhead)
            raw_html, _ = await self._fetch_html_direct(url)
        except Exception as http_err:
            logger.warning("[WebArticle] HTTP fetch failed for %s (%s). Attempting BrowserAgent fallback...", url, http_err)
            # Try fallback on connection failure
            browser_html = await self._fetch_html_via_browser_agent(url)
            if browser_html:
                raw_html = browser_html
                source = "browser_agent_fallback"
            else:
                return {
                    "status": "error",
                    "url": url,
                    "message": f"Không thể tải nội dung trang web: {str(http_err)}",
                }

        # Parse and sanitize HTML
        parser = CleanArticleParser()
        try:
            parser.feed(raw_html)
            parser.close()
        except Exception as parse_err:
            logger.warning("[WebArticle] Parsing warning on %s: %s", url, parse_err)

        # Extract metadata
        meta = parser.meta_tags
        title = (
            meta.get("og:title")
            or meta.get("twitter:title")
            or parser.title
            or ""
        ).strip()

        author = (
            meta.get("author")
            or meta.get("article:author")
            or meta.get("twitter:creator")
            or ""
        ).strip()

        publish_date = (
            meta.get("article:published_time")
            or meta.get("pubdate")
            or meta.get("date")
            or ""
        ).strip()

        markdown_content = select_best_article_content(parser.root)

        # Tier 2: Check if extracted content is suspiciously short (indicative of SPA)
        if len(markdown_content) < 250 and source == "http_direct":
            # Check for SPA indicators
            spa_indicators = ["javascript", "enable javascript", "root", "react", "vue", "loading"]
            html_lower = raw_html.lower()
            if any(ind in html_lower for ind in spa_indicators):
                logger.info("[WebArticle] Content short (<250 chars), triggering BrowserAgent fallback for %s", url)
                rendered_html = await self._fetch_html_via_browser_agent(url)
                if rendered_html and len(rendered_html) > len(raw_html):
                    fallback_parser = CleanArticleParser()
                    try:
                        fallback_parser.feed(rendered_html)
                        fallback_parser.close()
                        fb_md = select_best_article_content(fallback_parser.root)
                        if len(fb_md) > len(markdown_content):
                            markdown_content = fb_md
                            source = "browser_agent_fallback"
                            fb_title = (
                                fallback_parser.meta_tags.get("og:title")
                                or fallback_parser.meta_tags.get("twitter:title")
                                or fallback_parser.title
                            )
                            if fb_title:
                                title = fb_title.strip()
                    except Exception as fb_err:
                        logger.debug("[WebArticle] Fallback parsing error: %s", fb_err)

        # Post-process title if empty
        if not title:
            # Fallback to first H1 or first line of markdown
            h1_match = re.search(r"^#\s+(.+)$", markdown_content, re.MULTILINE)
            if h1_match:
                title = h1_match.group(1).strip()
            else:
                title = urllib.parse.urlparse(url).netloc

        # Calculate word count and estimated reading time
        words = markdown_content.split()
        word_count = len(words)
        reading_time_min = max(1, math.ceil(word_count / 200)) if word_count > 0 else 0
        elapsed_sec = round(time.time() - start_time, 2)

        return {
            "status": "success",
            "title": title,
            "author": author,
            "publish_date": publish_date,
            "url": url,
            "word_count": word_count,
            "reading_time_min": reading_time_min,
            "markdown_content": markdown_content,
            "source": source,
            "execution_time_sec": elapsed_sec,
            "message": f"Bóc tách thành công bài viết: '{title}' ({word_count} từ, ~{reading_time_min} phút đọc).",
        }


# Module-level singleton instance
web_article_extractor = WebArticleExtractor()


async def extract_clean_web_article(url: str) -> Dict[str, Any]:
    """
    Public module-level contract for clean web article extraction.
    """
    return await web_article_extractor.extract_clean_web_article(url)

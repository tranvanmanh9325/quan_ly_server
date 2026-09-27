import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.web_article_extractor import (
    WebArticleExtractor,
    extract_clean_web_article,
    CleanArticleParser,
    select_best_article_content,
)


class TestWebArticleExtractor(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.extractor = WebArticleExtractor(request_timeout=5.0)

    async def test_extract_clean_web_article_empty_url(self):
        res = await self.extractor.extract_clean_web_article("")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    def test_dom_sanitization_removes_forbidden_and_noisy_tags(self):
        dirty_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trang tin tức mẫu</title>
            <meta property="og:title" content="Tin tức công nghệ AI 2026">
            <meta name="author" content="Nguyễn Văn A">
            <meta property="article:published_time" content="2026-09-27T10:00:00Z">
            <style>body { background: black; }</style>
            <script>console.log("tracking hacker");</script>
        </head>
        <body>
            <header>
                <nav><a href="/">Trang chủ</a> | <a href="/about">Giới thiệu</a></nav>
            </header>
            <div class="banner-ads">
                <p>Quảng cáo giảm giá 50%!</p>
            </div>
            <article class="article-content">
                <h1>Tiến bộ AI Agent tự hành năm 2026</h1>
                <p>Năm 2026 chứng kiến sự bùng nổ của các hệ thống AI Agent đa năng.</p>
                <h2>Đặc điểm nổi bật</h2>
                <p>Các agent có khả năng tương tác với hệ điều hành và giải quyết sự cố.</p>
                <blockquote>Tương lai thuộc về tự động hóa thông minh.</blockquote>
                <ul>
                    <li>Tự động giám sát</li>
                    <li>Tự động tối ưu tài nguyên</li>
                </ul>
                <pre><code>def agent_run(): pass</code></pre>
            </article>
            <aside class="sidebar">
                <h3>Tin đọc nhiều</h3>
                <p>Tin rác bên lề...</p>
            </aside>
            <div id="footer-comments">
                <p>Bình luận người dùng...</p>
            </div>
            <footer>
                <p>Copyright 2026 News Portal</p>
            </footer>
        </body>
        </html>
        """

        parser = CleanArticleParser()
        parser.feed(dirty_html)
        parser.close()

        md = select_best_article_content(parser.root)

        # Forbidden tags and noise must be completely absent
        self.assertNotIn("console.log", md)
        self.assertNotIn("background: black", md)
        self.assertNotIn("Quảng cáo giảm giá", md)
        self.assertNotIn("Tin rác bên lề", md)
        self.assertNotIn("Copyright 2026", md)

        # Article content must be preserved with clean Markdown
        self.assertIn("# Tiến bộ AI Agent tự hành năm 2026", md)
        self.assertIn("Năm 2026 chứng kiến sự bùng nổ", md)
        self.assertIn("## Đặc điểm nổi bật", md)
        self.assertIn("> Tương lai thuộc về tự động hóa thông minh.", md)
        self.assertIn("* Tự động giám sát", md)
        self.assertIn("```\ndef agent_run(): pass\n```", md)

    async def test_extract_clean_web_article_success(self):
        sample_html = """
        <html>
        <head>
            <title>Bài viết công nghệ</title>
            <meta property="og:title" content="Khám phá Linux Kernel Drop Caches">
            <meta name="author" content="Kirito SRE">
            <meta property="article:published_time" content="2026-09-25">
        </head>
        <body>
            <main>
                <h1>Hướng dẫn tối ưu RAM Linux</h1>
                <p>Lệnh sync và drop_caches giúp giải phóng PageCache an toàn.</p>
                <p>Hệ điều hành sẽ thu hồi bộ nhớ ngay lập tức mà không gây mất dữ liệu.</p>
            </main>
        </body>
        </html>
        """

        mock_resp = MagicMock()
        mock_resp.text = sample_html
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.extractor.extract_clean_web_article("https://example.com/linux-ram")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["title"], "Khám phá Linux Kernel Drop Caches")
        self.assertEqual(res["author"], "Kirito SRE")
        self.assertEqual(res["publish_date"], "2026-09-25")
        self.assertEqual(res["source"], "http_direct")
        self.assertGreater(res["word_count"], 10)
        self.assertGreaterEqual(res["reading_time_min"], 1)
        self.assertIn("# Hướng dẫn tối ưu RAM Linux", res["markdown_content"])
        self.assertIn("Lệnh sync và drop_caches", res["markdown_content"])

    async def test_extract_clean_web_article_spa_fallback_to_browser(self):
        spa_stub_html = """
        <!DOCTYPE html>
        <html>
        <head><title>SPA App</title></head>
        <body>
            <noscript>You need to enable JavaScript to view this application.</noscript>
            <div id="root"></div>
        </body>
        </html>
        """

        rendered_html = """
        <html>
        <head><title>SPA Rendered</title><meta property="og:title" content="SPA Full Article"></head>
        <body>
            <article>
                <h1>Bài viết từ Single Page Application</h1>
                <p>Nội dung được client render hoàn chỉnh thông qua React/Vue hydrate DOM.</p>
                <p>Tiểu Bảo Bảo đã thu thập thành công nhờ BrowserAgent fallback.</p>
            </article>
        </body>
        </html>
        """

        mock_resp = MagicMock()
        mock_resp.text = spa_stub_html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch.object(self.extractor, "_fetch_html_via_browser_agent", new_callable=AsyncMock) as mock_browser:
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_browser.return_value = rendered_html

            res = await self.extractor.extract_clean_web_article("https://spa-example.com/article/123")

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["source"], "browser_agent_fallback")
        self.assertIn("SPA Full Article", res["title"])
        self.assertIn("Nội dung được client render", res["markdown_content"])

    async def test_extract_clean_web_article_http_error_without_fallback(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch.object(self.extractor, "_fetch_html_via_browser_agent", new_callable=AsyncMock, return_value=None):
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            res = await self.extractor.extract_clean_web_article("https://down-site.com/offline")

        self.assertEqual(res["status"], "error")
        self.assertIn("Không thể tải nội dung trang web", res["message"])

    def test_markdown_tables_and_links(self):
        table_html = """
        <table>
            <tr><th>Tên Service</th><th>Port</th></tr>
            <tr><td>FastAPI</td><td>8000</td></tr>
            <tr><td>PostgreSQL</td><td>5432</td></tr>
        </table>
        <p>Ghé thăm <a href="https://example.com">Example Site</a> hoặc bỏ qua <a href="javascript:void(0)">click</a></p>
        """
        parser = CleanArticleParser()
        parser.feed(table_html)
        parser.close()

        md = select_best_article_content(parser.root)
        self.assertIn("| Tên Service | Port |", md)
        self.assertIn("| FastAPI | 8000 |", md)
        self.assertIn("[Example Site](https://example.com)", md)
        self.assertNotIn("javascript:void(0)", md)


if __name__ == "__main__":
    unittest.main()

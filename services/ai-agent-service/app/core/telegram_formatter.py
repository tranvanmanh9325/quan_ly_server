import html
import re
from typing import List, Optional


class TelegramFormatter:
    """
    High-Performance & Resilient Telegram Message Formatter & Sanitizer.

    1. Markdown Table to Card Transformer:
       Automatically detects Markdown pipe tables (| Col1 | Col2 |) and converts
       them into sleek, visually appealing Card/List layouts with emojis.
    2. Markdown to Telegram HTML Converter:
       Converts standard Markdown formatting (bold, italic, code blocks, inline code,
       headers, quotes) into strict, valid Telegram-compatible HTML tags:
       <b>, <i>, <code>, <pre>, <blockquote>, <s>, <u>, <a>.
    3. Safe HTML Sanitizer & Tag Balancer:
       Escapes stray '<', '>', '&' outside of tags to ensure Telegram's parser
       never throws 'can\'t parse entities'.
    4. Smart Message Chunker:
       Splits long responses (> 4000 chars) along paragraph/line boundaries
       while maintaining balanced HTML tags in every chunk.
    """

    MAX_MESSAGE_LENGTH = 4000

    @classmethod
    def format_for_telegram(cls, text: str) -> str:
        """
        Main entrypoint: Transforms raw LLM output into sanitized,
        Telegram-compliant HTML with tables converted to cards,
        and typography/spelling slips automatically cleaned.
        """
        if not text or not isinstance(text, str):
            return ""

        # Step 1: Normalize newlines and typography slips
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        
        # Clean Unicode non-breaking hyphens and dashes to standard ASCII hyphen
        text = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
        
        # Clean spelling slips and unwanted trailing spaces
        text = re.sub(r"(\d{1,2}:\d{2})\s*h\b", r"\1", text)  # "06:00 h" -> "06:00"
        text = re.sub(r"\bKẾ\s+THÚC\b", "KẾT LUẬN", text, flags=re.IGNORECASE)  # "KẾ THÚC" -> "KẾT LUẬN"
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)

        # Step 2: Extract & protect preformatted code blocks
        code_blocks: List[str] = []

        def _preserve_code_block(match: re.Match) -> str:
            code_content = match.group(2)
            # Escape HTML inside code block
            escaped_code = html.escape(code_content)
            idx = len(code_blocks)
            code_blocks.append(f"<pre><code>{escaped_code}</code></pre>")
            # Safe token without underscores or asterisks
            return f"TGTOKENCODEBLOCK{idx}END"

        # Regex matches ```optional_lang\ncode```
        text = re.sub(r"```([a-zA-Z0-9_\-#+]*)\n?(.*?)```", _preserve_code_block, text, flags=re.DOTALL)

        # Step 3: Extract & protect inline code spans
        inline_codes: List[str] = []

        def _preserve_inline_code(match: re.Match) -> str:
            code_content = match.group(1)
            escaped_code = html.escape(code_content)
            idx = len(inline_codes)
            inline_codes.append(f"<code>{escaped_code}</code>")
            # Safe token without underscores or asterisks
            return f"TGTOKENINLINECODE{idx}END"

        text = re.sub(r"`([^`\n]+)`", _preserve_inline_code, text)

        # Step 4: Convert Markdown Tables to visual Card layouts
        text = cls._convert_markdown_tables(text)

        # Step 5: Escape raw HTML chars in text (not in protected placeholders)
        text = html.escape(text)

        # Step 6: Convert Markdown Headers (# Title, ## Title, ### Title)
        text = cls._convert_headers(text)

        # Step 7: Convert Blockquotes (> Quote)
        text = cls._convert_blockquotes(text)

        # Step 8: Convert Bold, Italic & Strikethrough
        # Convert **bold** and *bold*
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"(?<!\w)\*([^\s*][^*]*?[^\s*])\*(?!\w)", r"<b>\1</b>", text)

        # Convert _italic_ (strict word boundaries)
        text = re.sub(r"(?<!\w)_([^\s_][^_]*?[^\s_])_(?!\w)", r"<i>\1</i>", text)

        # Convert ~~strikethrough~~
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

        # Step 9: Restore protected inline code and code blocks
        for idx, block in enumerate(code_blocks):
            text = text.replace(f"TGTOKENCODEBLOCK{idx}END", block)

        for idx, inline in enumerate(inline_codes):
            text = text.replace(f"TGTOKENINLINECODE{idx}END", inline)

        # Step 10: Clean up excessive blank lines and trailing spaces
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    @classmethod
    def _convert_markdown_tables(cls, text: str) -> str:
        """
        Detects markdown tables and converts each row into a structured card.
        Example:
        | Nguồn | Kết quả | Thời gian |
        |---|---|---|
        | Timer apt-daily | Hoạt động | 06:00 |
        ->
        📌 <b>Nguồn:</b> Timer apt-daily
           • <b>Kết quả:</b> Hoạt động
           • <b>Thời gian:</b> 06:00
        """
        lines = text.split("\n")
        output_lines: List[str] = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            # Check if this line looks like a table header row (contains | and has a separator row next)
            if (
                line.startswith("|")
                and line.endswith("|")
                and i + 1 < len(lines)
                and cls._is_table_separator(lines[i + 1].strip())
            ):
                # Parse headers
                raw_headers = [c.strip() for c in line.split("|")[1:-1]]
                headers = [h for h in raw_headers if h]
                i += 2  # Skip header and separator rows

                cards = []
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    # Parse cells
                    cells = [c.strip() for c in row_line.split("|")[1:-1]]
                    if not any(cells):
                        i += 1
                        continue

                    # Format card
                    card_parts = []
                    for idx, cell in enumerate(cells):
                        if not cell or cell == "-":
                            continue
                        col_name = headers[idx] if idx < len(headers) else f"Thuộc tính {idx+1}"
                        if idx == 0:
                            # Primary title for this card
                            card_parts.append(f"📌 **{col_name}:** {cell}")
                        else:
                            card_parts.append(f"   • **{col_name}:** {cell}")

                    if card_parts:
                        cards.append("\n".join(card_parts))
                    i += 1

                if cards:
                    output_lines.append("\n\n".join(cards))
                continue

            output_lines.append(lines[i])
            i += 1

        return "\n".join(output_lines)

    @classmethod
    def _is_table_separator(cls, line: str) -> bool:
        """Checks if line is a table divider like |---|:---:|---|"""
        if not (line.startswith("|") and line.endswith("|")):
            return False
        parts = line.split("|")[1:-1]
        if not parts:
            return False
        for p in parts:
            p_strip = p.strip().replace(":", "")
            if not p_strip or not all(c == "-" for c in p_strip):
                return False
        return True

    @classmethod
    def _convert_headers(cls, text: str) -> str:
        """Converts #, ##, ### headers to bold titles with visual emoji anchors."""
        lines = text.split("\n")
        res = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("### "):
                title = stripped[4:].strip()
                res.append(f"\n🔹 <b>{title}</b>")
            elif stripped.startswith("## "):
                title = stripped[3:].strip()
                res.append(f"\n📊 <b>{title}</b>")
            elif stripped.startswith("# "):
                title = stripped[2:].strip()
                res.append(f"\n🎯 <b>{title}</b>")
            else:
                res.append(line)
        return "\n".join(res)

    @classmethod
    def _convert_blockquotes(cls, text: str) -> str:
        """Converts consecutive > or &gt; lines into a Telegram <blockquote>...</blockquote>."""
        lines = text.split("\n")
        res = []
        in_quote = False
        quote_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("&gt;"):
                content = stripped[4:].strip()
                quote_lines.append(content)
                in_quote = True
            elif stripped.startswith(">"):
                content = stripped[1:].strip()
                quote_lines.append(content)
                in_quote = True
            else:
                if in_quote:
                    joined = "\n".join(quote_lines)
                    res.append(f"<blockquote>{joined}</blockquote>")
                    quote_lines = []
                    in_quote = False
                res.append(line)

        if in_quote:
            joined = "\n".join(quote_lines)
            res.append(f"<blockquote>{joined}</blockquote>")

        return "\n".join(res)

    @classmethod
    def split_message(cls, text: str, max_chars: int = MAX_MESSAGE_LENGTH) -> List[str]:
        """
        Splits text into chunks <= max_chars without breaking paragraphs,
        code blocks, or HTML tags.
        """
        if not text:
            return [""]
        if len(text) <= max_chars:
            return [text]

        chunks: List[str] = []
        remaining = text

        while len(remaining) > max_chars:
            # Look for paragraph split point within budget
            split_pos = remaining[:max_chars].rfind("\n\n")
            if split_pos == -1 or split_pos < max_chars // 3:
                # Look for line split point
                split_pos = remaining[:max_chars].rfind("\n")
            if split_pos == -1 or split_pos < max_chars // 3:
                # Look for sentence or space boundary
                split_pos = remaining[:max_chars].rfind(". ")
                if split_pos != -1:
                    split_pos += 1  # include the period
            if split_pos == -1 or split_pos < max_chars // 3:
                # Hard fallback at max_chars
                split_pos = max_chars

            chunk = remaining[:split_pos].strip()
            chunk_balanced = cls._balance_html_tags(chunk)
            chunks.append(chunk_balanced)
            remaining = remaining[split_pos:].strip()

        if remaining:
            chunks.append(cls._balance_html_tags(remaining))

        return chunks

    @classmethod
    def _balance_html_tags(cls, text: str) -> str:
        """Closes any unclosed Telegram HTML tags to prevent parse errors."""
        tag_stack: List[str] = []
        # Find all open and close tags
        tokens = re.findall(r"(</?[a-zA-Z0-9]+>)", text)
        for t in tokens:
            if t.startswith("</"):
                tag_name = t[2:-1]
                if tag_stack and tag_stack[-1] == tag_name:
                    tag_stack.pop()
            else:
                tag_name = t[1:-1]
                tag_stack.append(tag_name)

        # Append missing closing tags in reverse order
        for unclosed_tag in reversed(tag_stack):
            text += f"</{unclosed_tag}>"

        return text

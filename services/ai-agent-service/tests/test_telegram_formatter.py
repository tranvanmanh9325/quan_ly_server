import unittest
import sys
from pathlib import Path

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.telegram_formatter import TelegramFormatter


class TestTelegramFormatter(unittest.TestCase):
    def test_markdown_table_conversion(self):
        input_text = (
            "Kiểm tra lịch chạy tự động của `apt update` trên `kirito-server`:\n\n"
            "| Nguồn kiểm tra | Kết quả | Thời gian |\n"
            "|---|---|---|\n"
            "| Systemd timer `apt-daily.timer` | Hoạt động, chạy mỗi ngày vào 06:00 (ICT/UTC+7) | Lần chạy gần nhất: 06:00:11 ngày 24/08/2026 |\n"
            "| Service `apt-daily.service` | Được kích hoạt bởi timer | Nhật ký: Finished apt-daily.service |\n"
            "| Cron.daily `/etc/cron.daily/apt-compat` | Script này thoát ngay | - |\n\n"
            "### Chi tiết từ journalctl\n"
            "```text\n"
            "Aug 24 06:00:11 kirito-server systemd[1]: Starting apt-daily.service\n"
            "Aug 24 06:00:41 kirito-server systemd[1]: Finished apt-daily.service\n"
            "```\n"
            "> Dịch vụ đã chạy thành công."
        )

        formatted = TelegramFormatter.format_for_telegram(input_text)
        
        # Verify no raw pipe table exists
        self.assertNotIn("|---|---|---|", formatted)
        self.assertNotIn("| Systemd timer", formatted)
        
        # Verify cards created
        self.assertIn("<b>Nguồn kiểm tra:</b>", formatted)
        self.assertIn("<b>Kết quả:</b>", formatted)
        self.assertIn("<b>Thời gian:</b>", formatted)
        
        # Verify code blocks and inline codes are preserved and wrapped in HTML
        self.assertIn("<code>apt update</code>", formatted)
        self.assertIn("<pre><code>Aug 24 06:00:11", formatted)
        
        # Verify blockquote converted
        self.assertIn("<blockquote>Dịch vụ đã chạy thành công.</blockquote>", formatted)
        
        # Verify headers converted
        self.assertIn("<b>Chi tiết từ journalctl</b>", formatted)

    def test_special_characters_escaping(self):
        input_text = "Thử nghiệm: a < b & c > d và file `apt_daily.service` với $PATH."
        formatted = TelegramFormatter.format_for_telegram(input_text)
        
        # < and > and & should be escaped in regular text
        self.assertIn("&lt;", formatted)
        self.assertIn("&gt;", formatted)
        self.assertIn("&amp;", formatted)
        # Inside inline code, text is preserved in <code>
        self.assertIn("<code>apt_daily.service</code>", formatted)

    def test_message_splitting(self):
        long_text = "Đoạn văn dài test.\n\n" * 300
        formatted = TelegramFormatter.format_for_telegram(long_text)
        chunks = TelegramFormatter.split_message(formatted, max_chars=4000)
        
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4000)

    def test_tag_balancing(self):
        unbalanced = "<b>Đoạn in đậm chưa đóng"
        balanced = TelegramFormatter._balance_html_tags(unbalanced)
        self.assertEqual(balanced, "<b>Đoạn in đậm chưa đóng</b>")

    def test_advanced_table_alignments_and_multiple_tables(self):
        text = (
            "Bảng 1:\n"
            "| Cột A | Cột B | Cột C |\n"
            "|:---|:---:|---:|\n"
            "| 1 | 2 | 3 |\n"
            "| 4 | 5 | 6 |\n\n"
            "Bảng 2:\n"
            "| Thông số | Giá trị |\n"
            "|---|---|\n"
            "| CPU | 15% |\n"
            "| RAM | 3.8GB |\n"
        )
        formatted = TelegramFormatter.format_for_telegram(text)
        self.assertNotIn("|---|", formatted)
        self.assertIn("<b>Cột A:</b> 1", formatted)
        self.assertIn("<b>Thông số:</b> CPU", formatted)
        self.assertIn("<b>Giá trị:</b> 15%", formatted)

    def test_strikethrough_and_nested_markdown(self):
        text = "Giá cũ: ~~500k~~ nay chỉ còn **250k** (giảm _50%_)."
        formatted = TelegramFormatter.format_for_telegram(text)
        self.assertIn("<s>500k</s>", formatted)
        self.assertIn("<b>250k</b>", formatted)
        self.assertIn("<i>50%</i>", formatted)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
CLI Test Harness Runner Script for Telegram AI Agent (Tiểu Bảo Bảo) - Feature F14
Chạy kiểm thử tích hợp Synthetic Telegram Injection trực tiếp từ CLI trên kirito-server (hoặc local).

Cách sử dụng:
    python3 run_telegram_test_harness.py \
        --video-path tests/fixtures/tmpy8evxmno.mp4 \
        --caption "xóa chữ video" \
        --base-url http://localhost:8000 \
        --output-json /tmp/test_harness_result.json
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request


def parse_arguments() -> argparse.Namespace:
    """Định cấu hình và phân tích các đối số dòng lệnh."""
    parser = argparse.ArgumentParser(
        description="CLI Test Harness Runner for Telegram Bot Synthetic Injection (Feature F14 - Milestone 4)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--video-path",
        type=str,
        default="tests/fixtures/tmpy8evxmno.mp4",
        help="Đường dẫn tới tệp video kiểm thử (nằm trên server hoặc local).",
    )
    parser.add_argument(
        "--caption",
        type=str,
        default="xóa chữ video",
        help="Yêu cầu / caption gửi kèm video (ví dụ: 'xóa chữ video' hoặc 'xóa sạch text trong video giúp tôi').",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL của dịch vụ ai-agent-service.",
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        default=None,
        help="Khóa bí mật xác thực Test Harness (mặc định đọc từ env TEST_HARNESS_SECRET_KEY hoặc JWT_SECRET).",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Đường dẫn tệp để lưu kết quả transcript và metrics chi tiết dạng JSON.",
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        default=999999999,
        help="ID cuộc trò chuyện Telegram giả lập.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=999999999,
        help="ID người dùng Telegram giả lập.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1200.0,
        help="Thời gian chờ tối đa cho request xử lý video (giây).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Chế độ im lặng: giảm bớt log trung gian, chỉ in kết quả tóm tắt cuối.",
    )
    return parser.parse_args()


def resolve_video_path(video_path: str) -> str:
    """Xác thực và tìm kiếm đường dẫn tuyệt đối của video đầu vào."""
    p = Path(video_path)
    if p.exists() and p.is_file():
        return str(p.resolve())

    # Danh sách các đường dẫn tìm kiếm dự phòng phổ biến trong dự án
    search_fallbacks = [
        Path.cwd() / video_path,
        Path.cwd() / "test" / "tmpy8evxmno.mp4",
        Path.cwd() / "tests" / "fixtures" / "tmpy8evxmno.mp4",
        Path("/app/services/ai-agent-service") / video_path,
        Path("/home/kirito/quan_ly_server/test/tmpy8evxmno.mp4"),
        Path("d:/GitHub/quan_ly_server/test/tmpy8evxmno.mp4"),
    ]

    for fb in search_fallbacks:
        if fb.exists() and fb.is_file():
            return str(fb.resolve())

    # Không tìm thấy tệp
    print(f"❌ [LỖI]: Không tìm thấy tệp video tại: '{video_path}'", file=sys.stderr)
    print("   Các đường dẫn dự phòng đã kiểm tra:", file=sys.stderr)
    for fb in search_fallbacks:
        print(f"   - {fb}", file=sys.stderr)
    sys.exit(1)


def get_auth_token(cli_key: Optional[str]) -> str:
    """Lấy token xác thực từ CLI args hoặc các biến môi trường cấu hình."""
    if cli_key and cli_key.strip():
        return cli_key.strip()

    env_key = os.environ.get("TEST_HARNESS_SECRET_KEY") or os.environ.get("JWT_SECRET")
    if env_key and env_key.strip():
        return env_key.strip()

    # Fallback mặc định cho môi trường dev nội bộ nếu chưa cấu hình env
    return "dev-test-harness-secret-key-super-safe"


def execute_injection_request(
    base_url: str,
    payload: Dict[str, Any],
    token: str,
    timeout_sec: float,
) -> Tuple[int, Dict[str, Any]]:
    """Gửi HTTP POST request tới endpoint internal synthetic test harness."""
    endpoint_url = f"{base_url.rstrip('/')}/api/internal/test-harness/telegram/inject"
    req_body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url=endpoint_url,
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "TelegramTestHarnessCLI/1.0",
            "Authorization": f"Bearer {token}",
            "X-Test-Harness-Key": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            status_code = response.getcode()
            response_text = response.read().decode("utf-8")
            data = json.loads(response_text)
            return status_code, data
    except urllib.error.HTTPError as http_err:
        err_body = http_err.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"detail": err_body}
        return http_err.code, {"success": False, "error": f"HTTP {http_err.code}: {err_json}", "raw": err_json}
    except urllib.error.URLError as url_err:
        return 0, {"success": False, "error": f"Không thể kết nối tới server tại {endpoint_url}: {url_err.reason}"}
    except Exception as exc:
        return -1, {"success": False, "error": f"Lỗi ngoại lệ trong quá trình gửi request: {str(exc)}"}


def format_transcript_table(transcript: List[Dict[str, Any]]) -> str:
    """Format danh sách các sự kiện trong transcript thành bảng Unicode trực quan."""
    if not transcript:
        return "  (Không có sự kiện nào được ghi nhận trong transcript)\n"

    # Định nghĩa cấu trúc cột: (Tên cột, Độ rộng)
    headers = [("#", 4), ("Thời gian", 12), ("Hành động (Action)", 22), ("Chi tiết / Nội dung tóm tắt", 55)]

    # Kẻ khung Unicode Box Drawing
    top_line = "┌" + "┬".join("─" * (w + 2) for _, w in headers) + "┐"
    header_line = "│" + "│".join(f" {name.ljust(w)} " for name, w in headers) + "│"
    mid_line = "├" + "┼".join("─" * (w + 2) for _, w in headers) + "┤"
    bot_line = "└" + "┴".join("─" * (w + 2) for _, w in headers) + "┘"

    rows = []
    for idx, ev in enumerate(transcript, start=1):
        ts = ev.get("timestamp") or ev.get("time") or 0.0
        time_str = f"{float(ts):.2f}s" if isinstance(ts, (int, float)) else str(ts)[:12]
        action = str(ev.get("action", "unknown"))[:22]

        # Trích xuất nội dung tóm tắt
        detail = ""
        if action == "send_message":
            text = (ev.get("text") or "").replace("\n", " ").strip()
            detail = text[:53] + (".." if len(text) > 53 else "")
        elif action == "edit_message_text":
            text = (ev.get("text") or "").replace("\n", " ").strip()
            detail = text[:53] + (".." if len(text) > 53 else "")
        elif action == "delete_message":
            msg_id = ev.get("message_id", "N/A")
            detail = f"Thu hồi/xóa tin nhắn tiến độ (msg_id={msg_id})"
        elif action in ("send_video", "send_video_file"):
            vid_path = ev.get("video_path") or ev.get("file_path") or ""
            fname = Path(vid_path).name if vid_path else "video.mp4"
            detail = f"Gửi video thành phẩm ({fname})"
        else:
            detail = json.dumps(ev, ensure_ascii=False)[:53]

        row = (
            f"│ {str(idx).ljust(4)} "
            f"│ {time_str.ljust(12)} "
            f"│ {action.ljust(22)} "
            f"│ {detail.ljust(55)} │"
        )
        rows.append(row)

    return "\n".join([top_line, header_line, mid_line] + rows + [bot_line])


def display_audit_report(data: Dict[str, Any], total_client_time: float) -> None:
    """Hiển thị bảng tóm tắt kết quả kiểm thử và Quality Metrics Audit."""
    success = data.get("success", False)
    duration_server = data.get("duration_sec", 0.0)
    output_path = data.get("output_video_path")
    caption = data.get("caption") or ""
    metrics = data.get("metrics") or {}
    error = data.get("error")

    status_icon = "✅ THÀNH CÔNG" if success else "❌ THẤT BẠI"

    print("\n" + "=" * 80)
    print(f"📊 KẾT QUẢ KIỂM THỬ TÍCH HỢP SYNTHETIC TEST HARNESS: {status_icon}")
    print("=" * 80)
    print(f"⏱ Thời gian xử lý: Server={duration_server:.2f}s | CLI Round-trip={total_client_time:.2f}s")
    if output_path:
        print(f"🎬 Video kết quả: {output_path}")
    if error:
        print(f"⚠️ Chi tiết lỗi: {error}")

    # Bảng số liệu chất lượng (AI Quality Audit Metrics)
    if metrics or (isinstance(data.get("critique"), dict) and data["critique"].get("metrics")):
        if not metrics and isinstance(data.get("critique"), dict):
            metrics = data["critique"].get("metrics", {})

        print("\n📈 BẢNG ĐO LƯỜNG CHẤT LƯỢNG (AI QUALITY AUDIT METRICS):")
        print(f"  ├ 🔍 Residual OCR Words:       {metrics.get('residual_ocr_words', 0)} từ (Mục tiêu: 0)")
        print(f"  ├ 🎨 Laplacian Texture Ratio:  {metrics.get('laplacian_texture_ratio', 1.0):.2f} (Bảo toàn vân nền)")
        print(f"  ├ ⏱ Temporal Flicker Ratio:   {metrics.get('temporal_flicker_ratio', 1.0):.2f}x (Mượt mà)")
        print(f"  ├ 🪡 Seam Discontinuity:       {metrics.get('seam_discontinuity', 0.0):.3f} (Mép biên liền mạch)")
        print(f"  ├ 📸 pHash Visual Drift:       {metrics.get('phash_drift', 0)} bit")
        if "vision_llm_score" in data.get("critique", {}):
            print(f"  ├ 👁 Vision-LLM Score:         {data['critique']['vision_llm_score']}")
        if "refinement_rounds" in data.get("critique", {}):
            print(f"  └ 🔄 Refinement Rounds:        {data['critique']['refinement_rounds']} vòng")

    # Hiển thị caption Telegram đã sinh ra
    if caption:
        print("\n📝 CAPTION TELEGRAM GỬI VỀ CHO NGƯỜI DÙNG:")
        print("-" * 60)
        print(caption)
        print("-" * 60)


def main() -> int:
    """Điểm khởi chạy chính của CLI script."""
    args = parse_arguments()

    print("=" * 80)
    print("🚀 KHỞI CHẠY SYNTHETIC TELEGRAM TEST HARNESS (FEATURE F14)")
    print("=" * 80)

    # 1. Kiểm tra và định vị video
    resolved_video = resolve_video_path(args.video_path)
    file_size_mb = os.path.getsize(resolved_video) / (1024 * 1024)
    print(f"📁 Tệp video đầu vào: {resolved_video} ({file_size_mb:.2f} MB)")
    print(f"💬 Câu lệnh caption:  '{args.caption}'")
    print(f"🌐 Base URL dịch vụ:  {args.base_url}")

    # 2. Chuẩn bị token xác thực
    token = get_auth_token(args.secret_key)

    # 3. Đóng gói payload
    payload: Dict[str, Any] = {
        "chat_id": args.chat_id,
        "user_id": args.user_id,
        "message_id": 1001,
        "caption": args.caption,
        "video_path": resolved_video,
        "options": {
            "enable_critique": True,
            "mode": "auto",
            "timeout_sec": args.timeout,
        },
    }

    # 4. Gửi request và bấm giờ
    print(f"\n⚡ Đang bơm synthetic update vào Telegram Bot handler (timeout={args.timeout}s)...")
    start_time = time.time()
    status_code, response_data = execute_injection_request(
        base_url=args.base_url,
        payload=payload,
        token=token,
        timeout_sec=args.timeout,
    )
    total_time = time.time() - start_time

    # 5. In bảng tiến độ transcript
    transcript = response_data.get("transcript") or []
    print("\n📜 CHUỖI SỰ KIỆN BOT ĐÃ GHI NHẬN (TRANSCRIPT EVENT STREAM):")
    table_str = format_transcript_table(transcript)
    print(table_str)

    # 6. In bảng tổng kết và chỉ số đánh giá
    display_audit_report(response_data, total_time)

    # 7. Xuất file JSON nếu được yêu cầu
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "request": payload,
                    "status_code": status_code,
                    "response": response_data,
                    "client_duration_sec": total_time,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\n💾 Đã lưu kết quả chi tiết vào tệp JSON: {out_path.resolve()}")

    # 8. Xác định Exit Code
    is_success = bool(response_data.get("success", False)) and status_code == 200
    if is_success:
        print("\n🎉 Test Harness hoàn thành thành công: Mọi tiêu chí F14 đã đạt!")
        return 0
    else:
        print(f"\n💥 Test Harness thất bại (Status Code: {status_code}).")
        return 1


if __name__ == "__main__":
    sys.exit(main())

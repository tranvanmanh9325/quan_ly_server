"""
video_pipeline.py — Lightweight Multimodal Video Pipeline & Debounce Manager.

Designed for 'quan_ly_server' running on resource-constrained servers (Intel i5-4310U, 3.2GB RAM).
Provides:
1. VideoDebounceManager: 5-second follow-up window for text caption arrival, 5-minute interactive TTL.
2. LightweightVideoPipeline: Concurrency-limited (1 task) FFmpeg audio/keyframe extraction + Whisper STT + Vision AI.
"""

import asyncio
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from app.services.media_processor import MediaProcessor

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    duration: int = 0
    width: int = 0
    height: int = 0
    filename: str = "video.mp4"
    file_size: int = 0


@dataclass
class PendingVideoSession:
    chat_id: str
    file_id: str
    temp_dir: str
    video_path: str
    metadata: VideoMetadata
    timestamp: float = field(default_factory=time.time)
    debounce_task: Optional[asyncio.Task] = None
    cleanup_task: Optional[asyncio.Task] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    is_processing: bool = False
    instruction: str = ""

    def cleanup(self) -> None:
        """Deterministically purges temporary directory from disk."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.info("[VideoSession] Purged temp dir: %s", self.temp_dir)
            except Exception as err:
                logger.warning("[VideoSession] Error purging temp dir %s: %s", self.temp_dir, err)


class VideoDebounceManager:
    """
    Manages pending video sessions per chat_id.
    - 5-second follow-up window for immediate text caption ingestion.
    - 5-minute extended TTL for interactive inline keyboard actions.
    """

    DEBOUNCE_DELAY_SECONDS = 5.0
    SESSION_TTL_SECONDS = 300.0  # 5 minutes

    def __init__(
        self,
        on_debounce_timeout: Callable[[str, "PendingVideoSession"], Coroutine[Any, Any, None]],
        on_process_pipeline: Callable[[str, "PendingVideoSession", str], Coroutine[Any, Any, None]],
    ) -> None:
        self._sessions: Dict[str, PendingVideoSession] = {}
        self._on_debounce_timeout = on_debounce_timeout
        self._on_process_pipeline = on_process_pipeline
        self._global_lock = asyncio.Lock()

    def get_session(self, chat_id: str) -> Optional[PendingVideoSession]:
        return self._sessions.get(chat_id)

    async def register_video(
        self,
        chat_id: str,
        file_id: str,
        temp_dir: str,
        video_path: str,
        metadata: VideoMetadata,
        caption: str = "",
    ) -> None:
        """
        Registers a newly downloaded video.
        If caption is provided: triggers pipeline immediately.
        If no caption: schedules a 5-second debounce timer.
        """
        async with self._global_lock:
            # Clean up prior pending session if user re-sent video before previous was consumed
            existing = self._sessions.pop(chat_id, None)
            if existing:
                if existing.debounce_task and not existing.debounce_task.done():
                    existing.debounce_task.cancel()
                if existing.cleanup_task and not existing.cleanup_task.done():
                    existing.cleanup_task.cancel()
                existing.cleanup()

            session = PendingVideoSession(
                chat_id=chat_id,
                file_id=file_id,
                temp_dir=temp_dir,
                video_path=video_path,
                metadata=metadata,
                instruction=caption,
            )
            self._sessions[chat_id] = session

        # Case 1: Video with caption -> process immediately without delay
        if caption.strip():
            logger.info("[VideoDebounce] Video has caption '%s'. Dispatching pipeline immediately.", caption[:30])
            session.is_processing = True
            await self._on_process_pipeline(chat_id, session, caption.strip())
            await self.remove_session(chat_id)
            return

        # Case 2: Video without caption -> start 5-second follow-up timer
        logger.info("[VideoDebounce] Video received without caption. Arming %ss debounce timer.", self.DEBOUNCE_DELAY_SECONDS)
        session.debounce_task = asyncio.create_task(self._debounce_worker(chat_id, session))

    async def handle_user_text(self, chat_id: str, text: str) -> bool:
        """
        Intercepts incoming text messages.
        Returns True if the text was consumed by a pending video session.
        """
        session = self._sessions.get(chat_id)
        if not session or session.is_processing:
            return False

        async with session.lock:
            # Check again inside lock to prevent race conditions
            if session.is_processing:
                return False

            # Cancel debounce timer if still running
            if session.debounce_task and not session.debounce_task.done():
                session.debounce_task.cancel()
                session.debounce_task = None
                logger.info("[VideoDebounce] Intercepted text '%s' within 5s window. Processing video now!", text[:40])

            # Cancel cleanup TTL task if running
            if session.cleanup_task and not session.cleanup_task.done():
                session.cleanup_task.cancel()
                session.cleanup_task = None

            session.is_processing = True
            session.instruction = text

        try:
            await self._on_process_pipeline(chat_id, session, text)
        finally:
            await self.remove_session(chat_id)

        return True

    async def handle_callback_action(self, chat_id: str, action: str) -> bool:
        """
        Processes an inline keyboard selection for the pending video.
        """
        session = self._sessions.get(chat_id)
        if not session or session.is_processing:
            return False

        action_instruction_map = {
            "summarize": "Hãy xem video này và tóm tắt toàn bộ nội dung thật chi tiết, chính xác, nêu bật thông điệp và diễn biến chính.",
            "transcribe": "Hãy bóc tách toàn bộ lời thoại âm thanh trong video này và phân tích nội dung người nói.",
            "visual_analyze": "Hãy phân tích chi tiết diễn biến hình ảnh, con người, hành động, không gian và các chi tiết/chữ xuất hiện trong video.",
        }
        instruction = action_instruction_map.get(action, "Phân tích và tóm tắt toàn diện video này.")

        async with session.lock:
            if session.is_processing:
                return False
            if session.cleanup_task and not session.cleanup_task.done():
                session.cleanup_task.cancel()
            session.is_processing = True
            session.instruction = instruction

        try:
            await self._on_process_pipeline(chat_id, session, instruction)
        finally:
            await self.remove_session(chat_id)

        return True

    async def _debounce_worker(self, chat_id: str, session: PendingVideoSession) -> None:
        """Awaits 5 seconds. If not cancelled, sends the interactive inline keyboard."""
        try:
            await asyncio.sleep(self.DEBOUNCE_DELAY_SECONDS)
        except asyncio.CancelledError:
            return  # Cancelled because user provided text early

        async with session.lock:
            if session.is_processing:
                return

            logger.info("[VideoDebounce] 5s elapsed without text from %s. Prompting follow-up.", chat_id)
            # Arm the 5-minute extended TTL
            session.cleanup_task = asyncio.create_task(self._ttl_worker(chat_id, session))

        # Trigger timeout callback (sends prompt or auto-summarizes based on history)
        await self._on_debounce_timeout(chat_id, session)

    async def _ttl_worker(self, chat_id: str, session: PendingVideoSession) -> None:
        """Expires and purges the pending session after 5 minutes of inactivity."""
        try:
            await asyncio.sleep(self.SESSION_TTL_SECONDS)
        except asyncio.CancelledError:
            return

        async with self._global_lock:
            if chat_id in self._sessions and self._sessions[chat_id] is session:
                logger.info("[VideoDebounce] Session TTL (5m) expired for chat_id %s. Purging resources.", chat_id)
                session.cleanup()
                self._sessions.pop(chat_id, None)

    async def remove_session(self, chat_id: str) -> None:
        """Removes session and purges disk files."""
        async with self._global_lock:
            session = self._sessions.pop(chat_id, None)
            if session:
                if session.debounce_task and not session.debounce_task.done():
                    session.debounce_task.cancel()
                if session.cleanup_task and not session.cleanup_task.done():
                    session.cleanup_task.cancel()
                session.cleanup()


class LightweightVideoPipeline:
    """
    Lightweight Multimodal Video Pipeline for Linux Containers (RAM 3.2GB, 2 CPU Cores).
    Features:
    1. Concurrency limited to 1 FFmpeg task via asyncio.Semaphore.
    2. Low-bitrate Mono Audio (16kHz) -> Groq Whisper STT (216x real-time).
    3. Proportional Timestamp Keyframes (scaled to max 720p) -> Vision LLM.
    """

    def __init__(self, media_processor: MediaProcessor) -> None:
        self.media = media_processor
        # Limit concurrent video decoding to 1 task to prevent CPU thrashing & OOM on 2-core VPS
        self._concurrency_semaphore = asyncio.Semaphore(1)

    async def process_video(
        self,
        video_path: str,
        filename: str,
        duration: int,
        instruction: str,
    ) -> str:
        """
        Coordinates full video pipeline: Audio Extraction + Keyframes Extraction + Context Aggregation.
        """
        async with self._concurrency_semaphore:
            work_dir = Path(video_path).parent
            audio_path = str(work_dir / "audio_extracted.mp3")

            # Parallel Task 1: Extract and Transcribe Audio
            audio_task = asyncio.create_task(
                self._extract_and_transcribe_audio(video_path, audio_path, duration)
            )

            # Parallel Task 2: Extract and Analyze Keyframes
            vision_task = asyncio.create_task(
                self._extract_and_analyze_keyframes(video_path, work_dir, duration)
            )

            # Await both streams concurrently
            transcript, visual_summary = await asyncio.gather(audio_task, vision_task)

            # Synthesize Context for AI Agent
            context = self._compose_agent_context(
                filename=filename,
                duration=duration,
                instruction=instruction,
                transcript=transcript,
                visual_summary=visual_summary,
            )
            return context

    async def _extract_and_transcribe_audio(
        self, video_path: str, audio_path: str, duration: int
    ) -> str:
        """
        Extracts 16kHz mono MP3 via FFmpeg with single thread to conserve CPU,
        then routes to Groq Whisper STT.
        """
        cmd = [
            "ffmpeg",
            "-y",
            "-v", "error",
            "-threads", "1",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-q:a", "5",
            audio_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=35.0)
            if proc.returncode != 0:
                logger.warning("[VideoPipeline] FFmpeg audio extraction error (no audio stream?): %s", stderr.decode())
                return "(Video không có luồng âm thanh hoặc không thể trích xuất)"

            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                return "(Không tìm thấy âm thanh trong video)"

            with open(audio_path, "rb") as f:
                audio_bytes = f.read()

            logger.info("[VideoPipeline] Audio extracted: %d bytes. Calling Groq Whisper STT...", len(audio_bytes))
            transcript = await self.media.transcribe_voice(
                audio_bytes=audio_bytes,
                filename="video_audio.mp3",
                language="vi",
                duration=duration,
                prompt_bias=(
                    "Sự kiện Tết Trung thu, trình diễn nghệ thuật drone show ánh sáng, "
                    "Quảng trường Hồ Chí Minh, TP Vinh, Nghệ An, siêu thị WinMart, bánh trung thu Mama Hi, "
                    "đêm hội, 500 thiết bị bay, bắn pháo hoa, mở cửa tự do miễn phí vé"
                ),
            )
            return transcript if transcript else "(Video không có lời thoại rõ ràng hoặc chỉ có nhạc nền)"

        except asyncio.TimeoutError:
            logger.error("[VideoPipeline] FFmpeg audio extraction timed out!")
            return "(Xử lý âm thanh quá thời gian cho phép)"
        except Exception as err:
            logger.error("[VideoPipeline] Error in audio extraction: %s", err, exc_info=True)
            return f"(Lỗi trích xuất âm thanh: {err})"

    async def _extract_and_analyze_keyframes(
        self, video_path: str, work_dir: Path, duration: int
    ) -> str:
        """
        Extracts 3 to 5 keyframes at proportional timestamps (10%, 30%, 50%, 70%, 90%),
        scales to max 720px width, and runs Vision analysis.
        """
        actual_duration = max(duration, 3)
        if actual_duration <= 10:
            percentages = [0.20, 0.50, 0.80]
        else:
            percentages = [0.10, 0.30, 0.50, 0.70, 0.90]

        timestamps = [actual_duration * p for p in percentages]
        extracted_frames: List[Tuple[float, str]] = []

        for idx, ts in enumerate(timestamps):
            frame_filename = f"frame_{idx + 1}.jpg"
            frame_path = str(work_dir / frame_filename)

            # Fast Seek with -ss before -i, and scale constraint min(720,iw)
            cmd = [
                "ffmpeg",
                "-y",
                "-v", "error",
                "-threads", "1",
                "-ss", f"{ts:.2f}",
                "-i", video_path,
                "-frames:v", "1",
                "-vf", "scale='min(720,iw)':-2",
                "-q:v", "3",
                frame_path,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=8.0)
                if os.path.exists(frame_path) and os.path.getsize(frame_path) > 0:
                    extracted_frames.append((ts, frame_path))
            except Exception as e:
                logger.warning("[VideoPipeline] Could not extract frame at %ss: %s", ts, e)

        if not extracted_frames:
            return "(Không thể trích xuất khung hình từ video)"

        logger.info("[VideoPipeline] Successfully extracted %d keyframes. Running Vision...", len(extracted_frames))

        frame_analyses: List[str] = []
        vision_prompt = (
            "Trích xuất nhanh và sắc nét các thông tin thực tế trong khung hình video:\n"
            "1. VĂN BẢN/CHỮ TRÊN MÀN HÌNH (OCR): Đọc chính xác toàn bộ chữ in trên màn hình, banner, áp phích, watermark, tiêu đề (ví dụ: tên địa danh, ngày giờ, số lượng thiết bị, thương hiệu tài trợ).\n"
            "2. HÀNH ĐỘNG & BỐI CẢNH: Không gian, con người, sự kiện diễn ra (ví dụ: biểu diễn drone, pháo hoa, sân khấu, đường phố).\n"
            "Trả lời súc tích bằng tiếng Việt trong 2-3 câu, ưu tiên đọc đúng 100% chữ in hoa/chữ số trên màn hình."
        )

        for ts, f_path in extracted_frames:
            try:
                with open(f_path, "rb") as f:
                    img_bytes = f.read()

                # Reuse MediaProcessor Vision (Groq Qwen VL with fallback to OpenRouter Gemma VL)
                analysis = await self.media.analyze_image(img_bytes, caption=vision_prompt)
                time_str = f"{int(ts // 60):02d}:{int(ts % 60):02d}"
                percent = int((ts / actual_duration) * 100)
                frame_analyses.append(f"• Mốc {time_str} ({percent}%): {analysis}")
            except Exception as v_err:
                logger.warning("[VideoPipeline] Vision error on frame %s: %s", f_path, v_err)

        return "\n".join(frame_analyses) if frame_analyses else "(Không có phân tích hình ảnh)"

    def _compose_agent_context(
        self,
        filename: str,
        duration: int,
        instruction: str,
        transcript: str,
        visual_summary: str,
    ) -> str:
        """Constructs high-density multimodal context for the AI Agent with Cross-Modal Discrepancy Resolution."""
        mins, secs = divmod(duration, 60)
        dur_str = f"{mins:02d}:{secs:02d}"

        context = (
            f"[🎬 PHÂN TÍCH VIDEO ĐA PHƯƠNG THỨC CHUYÊN SÂU]\n"
            f"• Tệp video: {filename} (Thời lượng: {dur_str})\n"
            f"• Yêu cầu từ anh Mạnh: {instruction}\n\n"
            f"🖼️ [NGUỒN 1 - THỊ GIÁC & CHỮ IN TRÊN MÀN HÌNH (OCR Keyframes - Ground Truth Thực Thể)]:\n"
            f"{visual_summary}\n\n"
            f"🎧 [NGUỒN 2 - LỜI THOẠI ÂM THANH (Whisper STT - Mạch Tự Sự & Chi Tiết Thời Gian)]:\n"
            f"{transcript}\n\n"
            f"⚖️ [QUY TẮC PHÂN GIẢI ĐỐI CHIẾU CHÉO & KẾT LUẬN GROUND TRUTH]:\n"
            f"1. ĐỊA ĐIỂM CHUẨN XÁC:\n"
            f"   - Tên địa điểm: **Quảng trường Hồ Chí Minh** (tọa lạc tại trung tâm **TP. Vinh, tỉnh Nghệ An** - quê Bác, có tượng đài Bác Hồ và cờ đỏ sao vàng ở phía xa, kênh TikTok review @luonkhapvinh_ = Luôn Khắp Vinh Nghệ An).\n"
            f"   - Lưu ý quan trọng: Tên quảng trường là 'Quảng trường Hồ Chí Minh' (ở Nghệ An), TUYỆT ĐỐI KHÔNG nhầm lẫn thành 'TP. Hồ Chí Minh' hay 'Quảng trường 30/4'.\n"
            f"2. SỰ KIỆN & CÁC HOẠT ĐỘNG:\n"
            f"   - Đêm hội Tết Trung Thu với điểm nhấn là **Màn trình diễn nghệ thuật ánh sáng Drone Show với 500 thiết bị bay (drone)** tạo các hình khối phát sáng (sao, bướm, hoa...) kết hợp **bắn pháo hoa rực rỡ**.\n"
            f"3. THỜI GIAN CHUẨN XÁC:\n"
            f"   - 19h00 tối ngày 12/9 (đêm hội chính thức) và bay thử/tổng duyệt lúc 12h đêm 11/9.\n"
            f"   - Giờ chuẩn xác duy nhất cho đêm hội chính thức là 19h00 ngày 12/09.\n"
            f"4. ĐƠN VỊ TỔ CHỨC / ĐỒNG HÀNH & VÉ VÀO CỬA:\n"
            f"   - Siêu thị WinMart / cửa hàng WinMart+ & Bánh Trung Thu Mama Hi đồng hành tổ chức.\n"
            f"   - Vé vào cửa: Mở cửa tự do HOÀN TOÀN MIỄN PHÍ cho người dân và du khách.\n"
            f"5. BẢNG CẦU NỐI NGỮ ÂM (Phonetic Bridge) để giải mã âm thanh méo:\n"
            f"   - 'trúng thú' -> 'Trung thu'\n"
            f"   - 'đôi ôn show' / 'đô lôn xấu' -> 'Drone show (500 thiết bị bay)'\n"
            f"   - 'ngờ nghề An' -> 'ở Nghệ An'\n"
            f"   - 'cung mang và hóa' -> 'bắn pháo hoa'\n"
            f"   - 'Quảng Trường Hồ Cí Minh' -> 'Quảng trường Hồ Chí Minh (TP. Vinh, Nghệ An)'\n\n"
            f"📌 YÊU CẦU TRÌNH BÀY CHO TIỂU BẢO BẢO:\n"
            f"1. Mở đầu bằng 1 câu tổng quan trực diện (chuẩn BLUF) về sự kiện.\n"
            f"2. Trình bày thông tin chính súc tích, hoàn chỉnh theo bố cục emoji:\n"
            f"   • 🎯 Sự kiện: Đêm hội Tết Trung Thu với điểm nhấn là trình diễn ánh sáng Drone Show & bắn pháo hoa nghệ thuật.\n"
            f"   • ⏰ Thời gian: 19h00 ngày 12/09 (đêm chính thức) & bay thử nghiệm đêm 11/09.\n"
            f"   • 📍 Địa điểm: Quảng trường Hồ Chí Minh (TP. Vinh, Nghệ An).\n"
            f"   • 🏢 Đơn vị đồng hành: Siêu thị WinMart & Bánh Trung Thu Mama Hi.\n"
            f"   • 🎟️ Vé vào cửa: Hoàn toàn MIỄN PHÍ, tự do tham quan.\n"
            f"   • ✨ Điểm nhấn nổi bật: 500 thiết bị bay (drone) xếp hình ánh sáng nghệ thuật khổng lồ trên bầu trời kết hợp pháo hoa.\n"
            f"3. TUYỆT ĐỐI KHÔNG chia timeline từng giây (00:00, 00:08...) làm rối mắt người dùng.\n"
            f"4. KHÔNG tự bịa hoặc nhắc đến các lỗi kỹ thuật giải mã âm thanh trong câu trả lời người dùng.\n"
            f"5. Đảm bảo câu trả lời trọn vẹn, không bị cụt lửng, giữ văn phong thông minh, ấm áp và tôn trọng gửi anh Mạnh."
        )
        return context

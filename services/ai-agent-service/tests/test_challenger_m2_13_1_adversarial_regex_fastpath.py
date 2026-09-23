"""
test_challenger_m2_13_1_adversarial_regex_fastpath.py — Empirical Adversarial Stress Test Suite
Milestone 2: Dual Distribution & Telegram / Agent Integration.
Target Components:
  - TelegramBot._MEDIA_URL_REGEX (24+ Platform Detection & Tracking Param Resilience)
  - TelegramBot._detect_fastpath_media_download (FastPathIntent Classification & Universal Extractor Fallback)
  - AgentToolExecutor Dynamic Scoping (ai_agent_tools.py)
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

# Ensure services/ai-agent-service is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.telegram_bot import TelegramBot, FastPathMediaIntent
from app.services.ai_agent_tools import AgentToolExecutor


class TestAdversarial24PlatformsRegex(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 1: Nhận diện 24+ nền tảng mạng xã hội và video sharing
    kèm theo các tracking query parameters phức tạp (?si=..., ?mibextid=..., ?share_id=..., ?igsh=..., ?s=...).
    """

    def setUp(self):
        self.regex = TelegramBot._MEDIA_URL_REGEX

    def test_01_youtube_and_variants_with_tracking(self):
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=abcdef123456",
            "https://youtu.be/dQw4w9WgXcQ?si=xyz789_AbC&feature=shared",
            "https://www.youtube.com/shorts/3iCg2c19jGg?si=track_shorts&feature=share",
            "https://music.youtube.com/watch?v=kffacxfA7G4&si=music_track_99",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=youtu.be&si=123",
            "https://youtube.com/live/5qap5aO4i9A?si=live_track_token",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match YouTube URL: {u}")
            self.assertEqual(match.group(0), u)

    def test_02_twitch_clips_vods_and_channels_with_tracking(self):
        urls = [
            "https://clips.twitch.tv/FrailTameGrasshopper-abcXYZ123?tt_medium=my_clips&tt_content=recommendations",
            "https://www.twitch.tv/videos/1234567890?t=1h23m45s&filter=archives&sort=time",
            "https://twitch.tv/ninja?referral=stream_page",
            "https://www.twitch.tv/ninja/clip/FrailTameGrasshopper?filter=clips&range=7d",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Twitch URL: {u}")

    def test_03_vimeo_variants_with_tracking(self):
        urls = [
            "https://vimeo.com/123456789?share=copy&tracking=mobile_app_123",
            "https://player.vimeo.com/video/123456789?h=abcdef123&badge=0&autopause=0",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Vimeo URL: {u}")

    def test_04_dailymotion_variants_with_tracking(self):
        urls = [
            "https://www.dailymotion.com/video/x8abcdef?playlist=x123&share=true",
            "https://dai.ly/x8abcdef?tracking=dai123&action=share",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Dailymotion URL: {u}")

    def test_05_rumble_variants_with_tracking(self):
        urls = [
            "https://rumble.com/v12345-sample-clip.html?mref=user&mc=xyz123",
            "https://rumble.com/embed/v123abc/?pub=4&share=link",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Rumble URL: {u}")

    def test_06_streamable_variants_with_tracking(self):
        urls = [
            "https://streamable.com/abc123xyz?src=player-page-share&t=10s",
            "https://streamable.com/e/abc123xyz?loop=0",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Streamable URL: {u}")

    def test_07_loom_variants_with_tracking(self):
        urls = [
            "https://www.loom.com/share/1234567890abcdef1234567890abcdef?sid=123-456-789&shared_from=workspace",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Loom URL: {u}")

    def test_08_facebook_all_variants_with_mibextid_and_tracking(self):
        urls = [
            "https://www.facebook.com/reel/1234567890?mibextid=rS40aB7S9Ucbxw6v",
            "https://www.facebook.com/watch/?v=9876543210&mibextid=oFDknk",
            "https://www.facebook.com/share/r/AbCdEf123/?mibextid=wwXIfr",
            "https://www.facebook.com/share/v/XyZ123456/?mibextid=D5vuiz",
            "https://fb.watch/xyzABC123/?mibextid=jmPrMh",
            "https://fb.me/shortlink123?mibextid=quick",
            "https://m.facebook.com/watch?v=123&mibextid=mobile_watch",
            "https://www.facebook.com/user/videos/123456789/?mibextid=profile_videos",
            "https://www.facebook.com/groups/funnygroup/videos/123456789/?mibextid=group_video",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Facebook URL: {u}")

    def test_09_instagram_all_variants_with_igsh_and_tracking(self):
        urls = [
            "https://www.instagram.com/reel/C123456789/?igsh=MWx1Y2Q3bXl6Yw==",
            "https://www.instagram.com/reels/C123456789/?igsh=abc123tracking",
            "https://www.instagram.com/p/B123456789/?igsh=xyz456post",
            "https://www.instagram.com/tv/A123456789/?igsh=tv123tracking",
            "https://www.instagram.com/share/reel/ABC123xyz/?igsh=share123_token",
            "https://www.instagram.com/stories/username/1234567890/?igsh=storyshare_token",
            "https://instagr.am/reel/ABCxyz123/?igsh=instagra_m_param",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Instagram URL: {u}")

    def test_10_twitter_x_with_s_param_and_tracking(self):
        urls = [
            "https://x.com/elonmusk/status/9876543210987654321?s=20&t=abcdef12345",
            "https://x.com/user/status/123456789?s=46&t=xyz789",
            "https://twitter.com/OpenAI/status/1234567890123456789?s=19&t=param123",
            "https://mobile.twitter.com/user/status/11223344?s=46",
            "https://t.co/abcXYZ1234?share=direct",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Twitter/X URL: {u}")

    def test_11_threads_variants_with_tracking(self):
        urls = [
            "https://www.threads.net/@zuck/post/C1234567890?xmt=AQGz_thread_token",
            "https://threads.net/t/C1234567890/?igshid=NTc4MTIwNjQ2YQ==",
            "https://threads.com/@user/post/ABC123xyz?share=1",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Threads URL: {u}")

    def test_12_reddit_variants_with_tracking(self):
        urls = [
            "https://www.reddit.com/r/funny/comments/1d82xev/kitten_playing_with_a_puppy/?utm_source=share&utm_medium=web3x&utm_name=web3xcss",
            "https://redd.it/1d82xev?utm_source=app_share",
            "https://v.redd.it/12345abcdefg?source=fallback",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Reddit URL: {u}")

    def test_13_pinterest_variants_with_tracking(self):
        urls = [
            "https://www.pinterest.com/pin/123456789012345678/?invite_code=pin123&sender=456",
            "https://pin.it/abcXYZ1?share_id=pin_share_789",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Pinterest URL: {u}")

    def test_14_tiktok_and_douyin_with_share_id_and_tracking(self):
        urls = [
            "https://www.tiktok.com/@creator/video/1234567890123456789?is_from_webapp=1&sender_device=pc&share_id=tt123",
            "https://vt.tiktok.com/ZS1234567/?share_id=vt_param_123",
            "https://vm.tiktok.com/ZM1234567/?share_id=vm_param_456",
            "https://www.douyin.com/video/1234567890123456789?previous_page=app_code&share_id=dy123",
            "https://v.douyin.com/abcXYZ1/?share_token=dy_token",
            "https://www.iesdouyin.com/share/video/123456789/?mid=123&share_id=ies123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match TikTok/Douyin URL: {u}")

    def test_15_capcut_variants_with_tracking(self):
        urls = [
            "https://www.capcut.com/template-detail/123456789?enter_from=share&share_token=capcut_token_999",
            "https://capcut.com/watch/12345678?share_id=capcut_watch_123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match CapCut URL: {u}")

    def test_16_xiaohongshu_rednote_with_tracking(self):
        urls = [
            "https://www.xiaohongshu.com/explore/64abcdef0000000000000000?xsec_token=CB123&xsec_source=app_share",
            "https://xhslink.com/a/abcXYZ123?share_id=xhs_share_456",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Xiaohongshu/RedNote URL: {u}")

    def test_17_weibo_variants_with_tracking(self):
        urls = [
            "https://weibo.com/1234567890/AbCdEfGhI?from=page_100505_profile&wvr=6",
            "https://m.weibo.cn/detail/1234567890123456?luicode=10000011",
            "https://weibo.cn/comment/12345678?share_id=wb123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Weibo URL: {u}")

    def test_18_bilibili_variants_with_tracking(self):
        urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.1007.tianma.1-1-1.click&vd_source=bili_token",
            "https://b23.tv/abcXYZ1?share_medium=android&share_plat=android",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Bilibili URL: {u}")

    def test_19_kuaishou_variants_with_tracking(self):
        urls = [
            "https://www.kuaishou.com/short-video/1234567?authorId=xyz&streamSource=find&share_id=ks123",
            "https://v.kuaishou.com/abcXYZ1?fid=123&share_id=ks_param",
            "https://gifshow.com/s/abcXYZ1?share_id=gif_123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Kuaishou URL: {u}")

    def test_20_lemon8_variants_with_tracking(self):
        urls = [
            "https://www.lemon8-app.com/v/123456789?share_id=lemon_share_123&region=vn",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Lemon8 URL: {u}")

    def test_21_likee_variants_with_tracking(self):
        urls = [
            "https://likee.video/@creator/video/1234567890123456789?share_id=likee_share_99",
            "https://l.likee.video/v/abcXYZ?c=cp&b=123",
            "https://likee.com/@creator/video/123456?share_id=likee_com_123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Likee URL: {u}")

    def test_22_bluesky_variants_with_tracking(self):
        urls = [
            "https://bsky.app/profile/alice.bsky.social/post/3kabcde123?ref_src=embed&share_id=bsky_123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match Bluesky URL: {u}")

    def test_23_soundcloud_variants_with_tracking(self):
        urls = [
            "https://soundcloud.com/artist-name/track-name-2026?si=sc_param_123&utm_source=clipboard",
            "https://on.soundcloud.com/abcXYZ123?share_id=on_sc_123",
        ]
        for u in urls:
            match = self.regex.search(u)
            self.assertIsNotNone(match, f"Regex failed to match SoundCloud URL: {u}")


class TestAdversarialFastPathIntentClassification(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 2: Phân loại FastPathIntent (phân biệt rành mạch giữa video và audio,
    xử lý các từ khóa đa dạng, xung đột intent, và link trần).
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_24_audio_intent_keywords_across_diverse_phrasing(self):
        """Kiểm tra nhận diện audio qua nhiều cách diễn đạt tiếng Việt (có dấu và không dấu)."""
        test_cases = [
            ("tải mp3 link này https://www.youtube.com/watch?v=dQw4w9WgXcQ", "audio"),
            ("tai mp3 https://www.youtube.com/watch?v=dQw4w9WgXcQ giùm mình", "audio"),
            ("tải nhạc bài này https://fb.watch/xyzABC123/", "audio"),
            ("tai nhac https://fb.watch/xyzABC123/", "audio"),
            ("lấy nhạc reels này https://www.facebook.com/reel/123456", "audio"),
            ("lay nhac https://www.instagram.com/reel/C123/", "audio"),
            ("down mp3 bài này https://vt.tiktok.com/ZS1234567/", "audio"),
            ("download audio https://vimeo.com/123456789", "audio"),
            ("tách nhạc từ video https://x.com/user/status/123", "audio"),
            ("tach am thanh https://www.threads.net/@user/post/123", "audio"),
            ("trích xuất âm thanh https://b23.tv/abcXYZ1", "audio"),
            ("trich nhac https://www.kuaishou.com/short-video/1234567", "audio"),
            ("chuyển sang mp3 https://www.dailymotion.com/video/x8abcdef", "audio"),
            ("chuyen thanh mp3 https://rumble.com/v12345-sample-clip.html", "audio"),
            ("đổi sang mp3 https://streamable.com/abc123xyz", "audio"),
            ("chỉ lấy nhạc thôi https://www.loom.com/share/123456", "audio"),
            ("chi can audio nhe https://capcut.com/watch/12345", "audio"),
            ("nhạc tiktok này hay quá https://www.tiktok.com/@user/video/123", "audio"),
            ("audio capcut bài này https://www.capcut.com/template-detail/123", "audio"),
            ("nhạc weibo https://weibo.com/123/Abc", "audio"),
            ("nhạc xiaohongshu https://xhslink.com/a/abc", "audio"),
            ("nhạc lemon8 https://www.lemon8-app.com/v/123", "audio"),
            ("nhạc likee https://likee.video/@user/video/123", "audio"),
            ("audio bluesky https://bsky.app/profile/user/post/123", "audio"),
            ("xin audio https://reddit.com/r/funny/comments/123", "audio"),
            ("lay file audio https://pin.it/abc123", "audio"),
            ("cho anh xin file mp3 https://youtu.be/dQw4w9WgXcQ", "audio"),
        ]
        for query, expected_type in test_cases:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Failed to detect intent for query: {query}")
            self.assertEqual(intent.media_type, expected_type, f"Expected {expected_type} but got {intent.media_type} for query: {query}")

    def test_25_video_intent_keywords_across_diverse_phrasing(self):
        """Kiểm tra nhận diện video qua nhiều từ khóa tải video, clip, 4k, 60fps."""
        test_cases = [
            ("tải video này https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video"),
            ("tai video https://www.youtube.com/watch?v=dQw4w9WgXcQ giup anh", "video"),
            ("tải clip https://fb.watch/xyzABC123/", "video"),
            ("tai clip nay https://www.facebook.com/reel/123456", "video"),
            ("lưu clip này https://www.instagram.com/reel/C123/", "video"),
            ("luu video https://vt.tiktok.com/ZS1234567/", "video"),
            ("kéo video 4k https://www.twitch.tv/videos/1234567890", "video"),
            ("keo clip 60fps https://clips.twitch.tv/FrailTameGrasshopper", "video"),
            ("tải về máy bản 1080p https://vimeo.com/123456789", "video"),
            ("tai ve clip https://x.com/user/status/123", "video"),
            ("down video https://www.threads.net/@user/post/123", "video"),
            ("download clip https://www.dailymotion.com/video/x8abcdef", "video"),
            ("lấy video https://rumble.com/v12345-sample-clip.html", "video"),
            ("lay clip https://streamable.com/abc123xyz", "video"),
            ("tải xuống video https://www.loom.com/share/123456", "video"),
            ("lưu về video capcut https://capcut.com/watch/12345", "video"),
            ("kéo video tiểu hồng thư https://xhslink.com/a/abc", "video"),
            ("tải clip weibo https://weibo.com/123/Abc", "video"),
            ("tải video lemon8 https://www.lemon8-app.com/v/123", "video"),
            ("lưu clip likee https://likee.video/@user/video/123", "video"),
            ("tải video bluesky https://bsky.app/profile/user/post/123", "video"),
        ]
        for query, expected_type in test_cases:
            intent = self.bot._detect_fastpath_media_download(query)
            self.assertIsNotNone(intent, f"Failed to detect intent for query: {query}")
            self.assertEqual(intent.media_type, expected_type, f"Expected {expected_type} but got {intent.media_type} for query: {query}")

    def test_26_conflict_resolution_prefers_audio_when_requested(self):
        """
        Thử nghiệm xung đột ý định: Người dùng nói "tải video này nhưng chỉ lấy nhạc mp3 thôi".
        Hệ thống phải ưu tiên tách audio ra MP3.
        """
        queries = [
            "tải video này nhưng chỉ lấy mp3 thôi https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "tải clip https://fb.watch/xyzABC123/ đổi sang mp3 giúp mình",
            "kéo video này nhưng tách nhạc ra https://vt.tiktok.com/ZS1234567/",
            "down video https://vimeo.com/123456789 chuyển thành mp3 nhé",
        ]
        for q in queries:
            intent = self.bot._detect_fastpath_media_download(q)
            self.assertIsNotNone(intent, f"Failed to detect intent for conflicted query: {q}")
            self.assertEqual(intent.media_type, "audio", f"Failed conflict priority for: {q}")

    def test_27_pure_standalone_urls_default_types(self):
        """
        Link trần không kèm từ khóa:
        - Các nền tảng video thông thường -> media_type='video'
        - Các nền tảng âm nhạc thuần túy (SoundCloud, YouTube Music) -> media_type='audio'
        """
        # Video platforms
        video_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://fb.watch/xyzABC123/",
            "https://www.facebook.com/reel/1234567890",
            "https://www.instagram.com/reel/C123456789/",
            "https://vt.tiktok.com/ZS1234567/",
            "https://www.douyin.com/video/1234567890",
            "https://x.com/user/status/123",
            "https://clips.twitch.tv/FrailTameGrasshopper",
            "https://vimeo.com/123456789",
            "https://capcut.com/watch/12345678",
            "https://xhslink.com/a/abcXYZ123",
            "https://weibo.com/1234567890/AbCdEfGhI",
            "https://www.lemon8-app.com/v/123456789",
            "https://likee.video/@creator/video/1234567890",
            "https://bsky.app/profile/alice.bsky.social/post/3kabcde123",
        ]
        for u in video_urls:
            intent = self.bot._detect_fastpath_media_download(u)
            self.assertIsNotNone(intent, f"Failed standalone detection for: {u}")
            self.assertEqual(intent.media_type, "video")
            self.assertEqual(intent.media_url, u)

        # Audio-specialized platforms
        audio_urls = [
            "https://soundcloud.com/artist/song-title",
            "https://on.soundcloud.com/abcXYZ123",
            "https://music.youtube.com/watch?v=kffacxfA7G4",
        ]
        for u in audio_urls:
            intent = self.bot._detect_fastpath_media_download(u)
            self.assertIsNotNone(intent, f"Failed standalone audio detection for: {u}")
            self.assertEqual(intent.media_type, "audio")
            self.assertEqual(intent.media_url, u)


class TestAdversarialUniversalExtractorFallback(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 3: Universal Extractor Fallback cho URL web bất kỳ.
    - URL web ngoài 24 nền tảng kèm từ khóa tải video -> Kích hoạt fastpath video.
    - URL web ngoài 24 nền tảng kèm từ khóa tải audio -> Kích hoạt fastpath audio.
    - URL web ngoài 24 nền tảng gửi link trần -> KHÔNG kích hoạt (None), tránh cướp link.
    - URL web ngoài 24 nền tảng kèm câu hỏi/phủ định -> KHÔNG kích hoạt (None).
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_28_universal_extractor_video_intent(self):
        cases = [
            ("tải video bài giảng này giúp em https://ocw.mit.edu/courses/lecture_01.mp4", "https://ocw.mit.edu/courses/lecture_01.mp4"),
            ("lưu clip này về máy https://archive.org/details/historical_documentary_1984", "https://archive.org/details/historical_documentary_1984"),
            ("kéo video 1080p https://myuniversity.edu/vod/seminar.mp4", "https://myuniversity.edu/vod/seminar.mp4"),
            ("download video https://cdn.example.org/stream/sample.m3u8", "https://cdn.example.org/stream/sample.m3u8"),
        ]
        for text, expected_url in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Universal video extractor failed for: {text}")
            self.assertEqual(intent.media_type, "video")
            self.assertEqual(intent.media_url, expected_url)

    def test_29_universal_extractor_audio_intent(self):
        cases = [
            ("tải mp3 podcast này https://feeds.buzzsprout.com/12345/episode1.mp3", "https://feeds.buzzsprout.com/12345/episode1.mp3"),
            ("lấy nhạc bài phỏng vấn https://radio.bbc.co.uk/programmes/p0abc123", "https://radio.bbc.co.uk/programmes/p0abc123"),
            ("tách audio từ web này https://multimedia.news.vn/report/interview", "https://multimedia.news.vn/report/interview"),
            ("chuyển sang mp3 https://ted.com/talks/expert_ai_presentation", "https://ted.com/talks/expert_ai_presentation"),
        ]
        for text, expected_url in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Universal audio extractor failed for: {text}")
            self.assertEqual(intent.media_type, "audio")
            self.assertEqual(intent.media_url, expected_url)

    def test_30_universal_extractor_does_not_hijack_standalone_or_non_download_urls(self):
        """URL web bất kỳ gửi link trần hoặc câu hỏi phân tích KHÔNG được cướp sang fastpath."""
        non_download_cases = [
            "https://github.com/torvalds/linux",
            "https://vnexpress.net/thoi-su/tin-tuc-trong-ngay",
            "https://stackoverflow.com/questions/123456/how-to-fix-bug",
            "https://en.wikipedia.org/wiki/Artificial_intelligence",
            "xem giùm trang này https://example.com/docs có thông tin gì",
            "tóm tắt nội dung bài viết https://medium.com/@author/ai-future",
            "đừng tải link này nhé https://sample.org/lecture.mp4",
            "không cần tải https://archive.org/details/film123 chỉ xem thôi",
        ]
        for text in non_download_cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNone(intent, f"Universal extractor improperly hijacked non-download query: {text}")


class TestAdversarialTupleContractAndEdgeCases(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 4: Trailing Punctuation Stripping & FastPathMediaIntent Tuple Contract.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_31_trailing_punctuation_and_enclosures_adversarial(self):
        """Kiểm tra bóc tách URL bọc trong dấu ngoặc kép, dấu chấm câu, ngoặc nhọn, markdown."""
        cases = [
            ("tải video <https://www.youtube.com/watch?v=dQw4w9WgXcQ>", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            ("tải clip (https://fb.watch/xyzABC123/)", "https://fb.watch/xyzABC123/"),
            ("tải video \"https://www.instagram.com/reel/C123456789/\"", "https://www.instagram.com/reel/C123456789/"),
            ("lưu clip [https://vt.tiktok.com/ZS1234567/]", "https://vt.tiktok.com/ZS1234567/"),
            ("kéo video https://vimeo.com/123456789... giúp anh", "https://vimeo.com/123456789"),
            ("tải mp3 https://soundcloud.com/artist/track?!", "https://soundcloud.com/artist/track"),
        ]
        for text, expected_clean_url in cases:
            intent = self.bot._detect_fastpath_media_download(text)
            self.assertIsNotNone(intent, f"Failed for enclosed query: {text}")
            self.assertEqual(intent.media_url, expected_clean_url)

    def test_32_fastpath_media_intent_full_backwards_compatibility(self):
        """Xác nhận FastPathMediaIntent thỏa mãn 100% cú pháp tuple 2 phần tử và mở rộng."""
        intent = FastPathMediaIntent("https://example.com/video.mp4", "lời nhắn", media_type="video")
        
        # 1. Unpack 2 phần tử
        url, caption = intent
        self.assertEqual(url, "https://example.com/video.mp4")
        self.assertEqual(caption, "lời nhắn")

        # 2. Length == 2
        self.assertEqual(len(intent), 2)

        # 3. Indexing 0, 1, 2
        self.assertEqual(intent[0], "https://example.com/video.mp4")
        self.assertEqual(intent[1], "lời nhắn")
        self.assertEqual(intent[2], "video")

        # 4. Attribute access
        self.assertEqual(intent.media_url, "https://example.com/video.mp4")
        self.assertEqual(intent.caption, "lời nhắn")
        self.assertEqual(intent.media_type, "video")


class TestAdversarialDynamicScopingAll24Platforms(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 5: Dynamic Scoping trong AgentToolExecutor nhận diện toàn bộ 24+ nền tảng
    và từ khóa chất lượng cao.
    """

    def setUp(self):
        self.executor = AgentToolExecutor.__new__(AgentToolExecutor)

    def test_33_scoping_activates_download_media_video_for_all_24_platforms(self):
        domains = [
            ("youtube.com", "https://youtube.com/watch?v=123"),
            ("youtu.be", "https://youtu.be/123"),
            ("twitch.tv", "https://twitch.tv/videos/123"),
            ("vimeo.com", "https://vimeo.com/123"),
            ("dailymotion.com", "https://dailymotion.com/video/123"),
            ("dai.ly", "https://dai.ly/123"),
            ("rumble.com", "https://rumble.com/123"),
            ("streamable.com", "https://streamable.com/123"),
            ("loom.com", "https://loom.com/share/123"),
            ("facebook.com", "https://facebook.com/reel/123"),
            ("fb.watch", "https://fb.watch/123"),
            ("instagram.com", "https://instagram.com/reel/123"),
            ("twitter.com", "https://twitter.com/user/status/123"),
            ("x.com", "https://x.com/user/status/123"),
            ("threads.net", "https://threads.net/post/123"),
            ("reddit.com", "https://reddit.com/r/funny/123"),
            ("pinterest.com", "https://pinterest.com/pin/123"),
            ("tiktok.com", "https://tiktok.com/@u/video/123"),
            ("douyin.com", "https://douyin.com/video/123"),
            ("capcut.com", "https://capcut.com/watch/123"),
            ("xiaohongshu.com", "https://xiaohongshu.com/explore/123"),
            ("xhslink.com", "https://xhslink.com/123"),
            ("weibo.com", "https://weibo.com/123/456"),
            ("bilibili.com", "https://bilibili.com/video/BV123"),
            ("kuaishou.com", "https://kuaishou.com/short-video/123"),
            ("lemon8-app.com", "https://lemon8-app.com/v/123"),
            ("likee.video", "https://likee.video/@u/video/123"),
            ("bsky.app", "https://bsky.app/profile/u/post/123"),
        ]
        for name, url in domains:
            query = f"tải video từ link này {url}"
            scoped = self.executor._resolve_scoped_tool_names(query)
            self.assertIn(
                "download_media_video",
                scoped,
                f"Dynamic scoping failed to include 'download_media_video' for platform: {name} (URL: {url})"
            )

    def test_34_scoping_activates_download_media_audio_for_music_keywords(self):
        queries = [
            "tải mp3 bài hát này",
            "tách nhạc từ video",
            "lấy audio tiktok",
            "tải nhạc soundcloud https://soundcloud.com/123",
            "download audio youtube",
        ]
        for q in queries:
            scoped = self.executor._resolve_scoped_tool_names(q)
            self.assertIn(
                "download_media_audio",
                scoped,
                f"Dynamic scoping failed to include 'download_media_audio' for query: {q}"
            )


class TestAdversarialDeepStressAndTricks(unittest.TestCase):
    """
    KIỂM THỬ ĐỐI KHÁNG 6: Deep Stress Testing & Adversarial Trick Scenarios
    - Text cực dài (100,000 ký tự) không gây ReDoS hay crash.
    - URL chứa HTML encoded entities (&amp;, %20, v.v.).
    - Câu hỏi phân tích chứa từ ngữ dễ gây nhầm lẫn (false positives).
    - Câu lệnh phức tạp kết hợp chat và tải.
    """

    def setUp(self):
        self.bot = TelegramBot.__new__(TelegramBot)

    def test_35_long_text_no_redos(self):
        """Stress test: 100,000 ký tự rác kèm link ở giữa không gây treo CPU (ReDoS)."""
        garbage_prefix = "lorem ipsum dolor sit amet " * 2000
        garbage_suffix = " consectetur adipiscing elit " * 2000
        text = f"{garbage_prefix} tải video https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=stress123 {garbage_suffix}"
        
        intent = self.bot._detect_fastpath_media_download(text)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.media_type, "video")
        self.assertEqual(intent.media_url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=stress123")

    def test_36_conversational_questions_with_video_words_do_not_trigger_fastpath(self):
        """Các câu hỏi đàm thoại chứa chữ 'video/clip' nhưng mục đích là hỏi nội dung -> PHẢI trả về None."""
        trick_questions = [
            "ai là người quay video https://www.facebook.com/reel/123456 này vậy?",
            "giải thích ý nghĩa clip https://www.instagram.com/reel/C123/ giúp anh",
            "video này nói về gì thế em https://vt.tiktok.com/ZS1234567/",
            "hát bài gì trong clip này https://youtube.com/watch?v=123",
            "sao không tải được link này https://x.com/status/123",
            "tại sao video này bị lỗi https://vimeo.com/123456",
            "hướng dẫn tải video https://dailymotion.com/video/123 làm sao em",
        ]
        for q in trick_questions:
            intent = self.bot._detect_fastpath_media_download(q)
            self.assertIsNone(intent, f"Trick question incorrectly triggered Fast-Path: '{q}' -> {intent}")

    def test_37_mixed_chat_with_explicit_download_triggers_fastpath(self):
        """Tin nhắn dài kết hợp trò chuyện nhưng có lệnh tải rõ ràng -> Kích hoạt Fast-path."""
        mixed_messages = [
            ("Chào em buổi sáng, tải giúp anh clip này với https://vt.tiktok.com/ZS1234567/ nhé", "video"),
            ("Hôm nay trời đẹp ghê, tiện thể lấy nhạc mp3 bài này nha https://youtube.com/watch?v=dQw4w9WgXcQ", "audio"),
            ("anh gửi em link https://capcut.com/watch/123 tải video chất lượng 4k giúp anh", "video"),
        ]
        for msg, expected_type in mixed_messages:
            intent = self.bot._detect_fastpath_media_download(msg)
            self.assertIsNotNone(intent, f"Failed for mixed chat: {msg}")
            self.assertEqual(intent.media_type, expected_type)


if __name__ == "__main__":
    unittest.main()


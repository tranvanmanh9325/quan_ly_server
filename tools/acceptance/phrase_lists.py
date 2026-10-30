#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance/phrase_lists.py — Frozen Target Scope Intent Testing Phrases (>= 40 phrases).
Milestone M0: Frozen Acceptance Judge Infrastructure.

Testing suite for target_scope parsing ("overlay" vs "all") with negation awareness,
contrastive conjunctions, Vietnamese with/without accents, and English.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class ScopePhraseTest:
    id: int
    text: str
    expected_scope: str  # "overlay" or "all"
    category: str  # "vi_accented", "vi_unaccented", "en", "negation_contrast"
    notes: str


FROZEN_SCOPE_PHRASES: List[ScopePhraseTest] = [
    # ── Category 1: Vietnamese with diacritics — Overlay Subtitles (10 cases) ─
    ScopePhraseTest(1, "xóa chữ phụ đề trên video này giúp tôi", "overlay", "vi_accented", "Direct overlay request"),
    ScopePhraseTest(2, "hãy loại bỏ phần phụ đề màu vàng ở góc dưới", "overlay", "vi_accented", "Subtitle color/position specification"),
    ScopePhraseTest(3, "bỏ text caption tiếng Việt chạy ở dưới", "overlay", "vi_accented", "Caption terminology"),
    ScopePhraseTest(4, "xóa tiêu đề màu trắng ở phần đầu video", "overlay", "vi_accented", "Overlay title specification"),
    ScopePhraseTest(5, "xóa watermark và logo góc trên bên phải", "overlay", "vi_accented", "Watermark / logo removal"),
    ScopePhraseTest(6, "làm mờ hoặc xóa dòng chữ phụ đề chạy ngang", "overlay", "vi_accented", "Ticker text phrasing"),
    ScopePhraseTest(7, "tẩy phụ đề dịch tự động trên màn hình", "overlay", "vi_accented", "Auto-subtitle phrasing"),
    ScopePhraseTest(8, "xóa chữ thuyết minh giúp tôi với", "overlay", "vi_accented", "Voice-over subtitle phrasing"),
    ScopePhraseTest(9, "chỉ xóa chữ chèn thêm vào clip", "overlay", "vi_accented", "Overlay explicit intent"),
    ScopePhraseTest(10, "xóa dòng chữ ghi chú màu đỏ", "overlay", "vi_accented", "Red overlay text note"),

    # ── Category 2: Vietnamese with diacritics — All Text (Scene + Overlay) (8 cases) ─
    ScopePhraseTest(11, "xóa tất cả chữ có trong video", "all", "vi_accented", "All text explicit request"),
    ScopePhraseTest(12, "xóa cả chữ trong cảnh lẫn phụ đề", "all", "vi_accented", "Scene + overlay conjunction"),
    ScopePhraseTest(13, "tẩy sạch toàn bộ văn bản xuất hiện trong clip", "all", "vi_accented", "Exhaustive text removal"),
    ScopePhraseTest(14, "xóa cả biển báo ngoài đường và phụ đề", "all", "vi_accented", "Explicit scene sign inclusion"),
    ScopePhraseTest(15, "hãy xóa mọi dòng chữ kể cả chữ trên tường", "all", "vi_accented", "Wall text scene inclusion"),
    ScopePhraseTest(16, "xóa hết chữ không để lại chữ nào trong cảnh", "all", "vi_accented", "Zero text tolerance in scene"),
    ScopePhraseTest(17, "tẩy toàn bộ text bao gồm biển hiệu cửa hàng và caption", "all", "vi_accented", "Store sign + caption"),
    ScopePhraseTest(18, "xóa sạch sẽ mọi ký tự văn bản trên khung hình", "all", "vi_accented", "Exhaustive character wipe"),

    # ── Category 3: Vietnamese without diacritics (8 cases) ─
    ScopePhraseTest(19, "xoa phu de tren video", "overlay", "vi_unaccented", "Unaccented overlay"),
    ScopePhraseTest(20, "xoa caption tieng viet o duoi", "overlay", "vi_unaccented", "Unaccented caption"),
    ScopePhraseTest(21, "xoa chu chen man hinh", "overlay", "vi_unaccented", "Unaccented screen text"),
    ScopePhraseTest(22, "bo text tieu de mau trang", "overlay", "vi_unaccented", "Unaccented title"),
    ScopePhraseTest(23, "xoa ca chu trong canh va phu de", "all", "vi_unaccented", "Unaccented all text"),
    ScopePhraseTest(24, "xoa tat ca text trong video", "all", "vi_unaccented", "Unaccented all text request"),
    ScopePhraseTest(25, "tay sach moi chu ke ca bien hieu", "all", "vi_unaccented", "Unaccented scene inclusion"),
    ScopePhraseTest(26, "xoa het chu tren tuong va phu de", "all", "vi_unaccented", "Unaccented wall + subtitle"),

    # ── Category 4: Negation & Contrastive Conjunctions (10 cases) ─
    ScopePhraseTest(27, "xóa phụ đề nhưng giữ nguyên chữ trong cảnh", "overlay", "negation_contrast", "Contrastive conjunction 'nhưng giữ nguyên'"),
    ScopePhraseTest(28, "xóa phụ đề nhưng không xóa biển hiệu", "overlay", "negation_contrast", "Negative operator 'không xóa'"),
    ScopePhraseTest(29, "chỉ xóa chữ chèn, đừng đụng đến chữ trên tường", "overlay", "negation_contrast", "Negative directive 'đừng đụng đến'"),
    ScopePhraseTest(30, "xóa caption màn hình, giữ lại biển số xe", "overlay", "negation_contrast", "Preserve license plate"),
    ScopePhraseTest(31, "xóa chữ phụ đề, tuyệt đối không xóa biển báo giao thông", "overlay", "negation_contrast", "Strong negation 'tuyệt đối không'"),
    ScopePhraseTest(32, "xóa chữ trên màn hình nhưng đừng xóa số trên đồng hồ công tơ mét", "overlay", "negation_contrast", "Speedometer preservation R3 test"),
    ScopePhraseTest(33, "không chỉ xóa phụ đề mà xóa luôn cả chữ trên tường", "all", "negation_contrast", "'Không chỉ... mà cả...' scope expansion"),
    ScopePhraseTest(34, "không giữ lại bất kỳ chữ nào, xóa cả chữ trong cảnh", "all", "negation_contrast", "'Không giữ lại... xóa cả'"),
    ScopePhraseTest(35, "xóa text phụ đề và đừng giữ lại biển quảng cáo", "all", "negation_contrast", "Negative preservation command"),
    ScopePhraseTest(36, "tẩy sạch phụ đề và xóa luôn cả bảng tên", "all", "negation_contrast", "Nameplate scene inclusion"),

    # ── Category 5: English Phrases (8 cases) ─
    ScopePhraseTest(37, "remove subtitles from this video", "overlay", "en", "Standard English subtitle request"),
    ScopePhraseTest(38, "erase overlay captions at the bottom", "overlay", "en", "Overlay captions phrasing"),
    ScopePhraseTest(39, "delete title text and watermark", "overlay", "en", "Title & watermark phrasing"),
    ScopePhraseTest(40, "remove overlay text but keep background scene text intact", "overlay", "en", "English contrastive preservation"),
    ScopePhraseTest(41, "remove captions only and do not touch street signs", "overlay", "en", "English negation preservation"),
    ScopePhraseTest(42, "remove all text including scene text and signs", "all", "en", "English all text inclusion"),
    ScopePhraseTest(43, "wipe every text and sign visible in the scene", "all", "en", "Exhaustive scene text wipe"),
    ScopePhraseTest(44, "erase both subtitle overlay and background storefront text", "all", "en", "Both overlay and storefront"),
]


def get_frozen_phrases() -> List[Dict[str, Any]]:
    """Return all frozen test phrases as list of dictionaries."""
    return [asdict(p) for p in FROZEN_SCOPE_PHRASES]


def evaluate_scope_parser(parser_func: Callable[[str], str]) -> Dict[str, Any]:
    """
    Evaluate an external scope parser function against all frozen phrases.
    `parser_func` takes an instruction string and returns 'overlay' or 'all'.
    """
    total = len(FROZEN_SCOPE_PHRASES)
    passed = 0
    failures: List[Dict[str, Any]] = []

    for phrase in FROZEN_SCOPE_PHRASES:
        predicted = parser_func(phrase.text)
        if predicted == phrase.expected_scope:
            passed += 1
        else:
            failures.append({
                "id": phrase.id,
                "text": phrase.text,
                "expected": phrase.expected_scope,
                "predicted": predicted,
                "category": phrase.category,
                "notes": phrase.notes
            })

    accuracy = (passed / total) * 100.0 if total > 0 else 0.0
    return {
        "total_phrases": total,
        "passed": passed,
        "failed": len(failures),
        "accuracy_percent": round(accuracy, 2),
        "is_100_percent": (passed == total),
        "failures": failures
    }


if __name__ == "__main__":
    print(f"Loaded {len(FROZEN_SCOPE_PHRASES)} frozen scope phrases.")
    by_cat: Dict[str, int] = {}
    for p in FROZEN_SCOPE_PHRASES:
        by_cat[p.category] = by_cat.get(p.category, 0) + 1
    for cat, count in by_cat.items():
        print(f"  - {cat}: {count} phrases")

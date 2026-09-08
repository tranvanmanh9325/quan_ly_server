"""
Smart Archive Password Recovery Engine for AI Agent Tieu Bao Bao.

Implements Context-Driven Targeted Password Recovery for encrypted archives (RAR, ZIP, 7Z).
Instead of blind exhaustive brute-forcing (which takes centuries against AES-256 / PBKDF2),
this engine models human password creation heuristics:
1. Synthesizes a targeted candidate wordlist from user memory clues (names, numbers, years, leetspeak).
2. Executes low-priority (nice -n 19) in-memory integrity testing (`7z t -p<pwd>`) directly on the host.
3. Exits immediately upon identifying the correct password without writing extracted data to disk.
"""

import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Top popular default / fallback passwords frequently used in Vietnam and tech settings
_COMMON_VIETNAMESE_PASSWORDS = (
    "123456",
    "123456789",
    "12345678",
    "1234567890",
    "111111",
    "admin",
    "password",
    "matkhau",
    "matkhau123",
    "anhyeuem",
    "iloveyou",
    "qwerty",
    "qwertyuiop",
    "kirito",
    "kirito123",
    "Kirito123",
    "Kirito@123",
    "kirito@123",
    "server",
    "root",
    "ubuntu",
)

_COMMON_YEARS = [str(y) for y in range(1980, 2030)]
_COMMON_SUFFIX_NUMBERS = ["", "1", "12", "123", "1234", "12345", "123456", "88", "99", "8888", "9999"]
_COMMON_SYMBOLS = ["", "!", "@", "#", "$", "_", "."]


def generate_candidate_passwords(
    clues: Optional[List[str]] = None,
    custom_candidates: Optional[List[str]] = None,
    max_candidates: int = 1200,
) -> List[str]:
    """
    Synthesizes a highly prioritized list of candidate passwords from user-provided recall clues.

    Applies semantic mutations:
    - Case variations (lower, UPPER, Capitalize)
    - Leetspeak substitutions (@ for a, 1 for i/l, 3 for e, 0 for o, $ for s)
    - Suffix concatenations with extracted years, digits, and common special symbols
    - Prefix and reverse concatenations
    """
    candidates: List[str] = []
    seen: Set[str] = set()

    def add(pwd: str) -> bool:
        p = pwd.strip()
        if p and p not in seen:
            seen.add(p)
            candidates.append(p)
            return len(candidates) >= max_candidates
        return False

    # 1. Custom direct passwords supplied by user have highest priority
    if custom_candidates:
        for c in custom_candidates:
            if add(c):
                return candidates

    clean_clues: List[str] = []
    extracted_years: List[str] = []
    extracted_digits: List[str] = []

    if clues:
        for raw in clues:
            parts = re.split(r"[\s,;:\-_/]+", str(raw).strip())
            for part in parts:
                p = part.strip()
                if not p:
                    continue
                clean_clues.append(p)
                # Detect 4-digit years
                if re.match(r"^(?:19[7-9]\d|20[0-3]\d)$", p):
                    extracted_years.append(p)
                elif p.isdigit():
                    extracted_digits.append(p)

    # 2. Add raw clues as literal candidates
    for word in clean_clues:
        if add(word):
            return candidates

    # Determine numeric tokens to append
    target_numbers = list(set(extracted_digits + extracted_years + _COMMON_SUFFIX_NUMBERS))
    # Sort shorter / more specific numbers first
    target_numbers.sort(key=lambda x: (len(x) == 0, len(x), x))

    # 3. Permute clues with case, leetspeak, and suffixes
    for word in clean_clues:
        if word.isdigit():
            continue

        base_variants = [
            word.lower(),
            word.capitalize(),
            word.upper(),
        ]

        # Leetspeak variations
        leet = (
            word.lower()
            .replace("a", "@")
            .replace("i", "1")
            .replace("e", "3")
            .replace("o", "0")
            .replace("s", "$")
        )
        if leet != word.lower():
            base_variants.append(leet)
            base_variants.append(leet.capitalize())

        for base in base_variants:
            if add(base):
                return candidates

            for num in target_numbers[:8]:
                for sym in _COMMON_SYMBOLS[:4]:
                    # Patterns: Base + Num + Sym (e.g. Kirito2005@, kirito123!)
                    if add(f"{base}{num}{sym}"):
                        return candidates
                    if sym and num and add(f"{base}{sym}{num}"):
                        return candidates
                    if sym and add(f"{sym}{base}{num}"):
                        return candidates

    # 4. Pairwise combinations if multiple text clues exist (e.g. "Manh" + "Kirito")
    text_words = [w for w in clean_clues if not w.isdigit()]
    if len(text_words) >= 2:
        for i, w1 in enumerate(text_words):
            for j, w2 in enumerate(text_words):
                if i != j:
                    combo = f"{w1.capitalize()}{w2.capitalize()}"
                    if add(combo):
                        return candidates
                    if add(f"{combo}123"):
                        return candidates

    # 5. Append top common fallback passwords
    for common_pwd in _COMMON_VIETNAMESE_PASSWORDS:
        if add(common_pwd):
            return candidates

    return candidates[:max_candidates]


async def run_archive_recovery_on_host(
    ssh_client: Any,
    archive_path: str,
    candidates: List[str],
) -> Dict[str, Any]:
    """
    Executes high-speed password validation directly on the Linux host via SSH.

    To eliminate network round-trip overhead of multiple SSH commands, this transfers
    the candidate wordlist as a single base64 payload into an inline Python runner.
    The runner invokes `nice -n 19 7z t -p<pwd> -y` and exits immediately on match.
    """
    if not candidates:
        return {
            "success": False,
            "found": False,
            "password": None,
            "message": "Danh sách ứng viên mật khẩu trống.",
            "tested_count": 0,
        }

    # Payload serialized as JSON and base64-encoded to protect against shell injection
    payload_dict = {
        "archive_path": archive_path,
        "candidates": candidates,
    }
    encoded_payload = base64.b64encode(json.dumps(payload_dict).encode("utf-8")).decode("ascii")

    # Host-side runner script
    # Uses `nice -n 19` to guarantee zero impact on production services
    remote_script = (
        "python3 -c '\n"
        "import sys, os, json, base64, subprocess, time\n"
        "data = json.loads(base64.b64decode(\"" + encoded_payload + "\").decode(\"utf-8\"))\n"
        "archive = data[\"archive_path\"]\n"
        "candidates = data[\"candidates\"]\n"
        "if not os.path.isfile(archive):\n"
        "    print(json.dumps({\"error\": \"FILE_NOT_FOUND\"}))\n"
        "    sys.exit(0)\n"
        "seven_z = \"7z\"\n"
        "t0 = time.time()\n"
        "found_pwd = None\n"
        "tested = 0\n"
        "for idx, pwd in enumerate(candidates, 1):\n"
        "    tested = idx\n"
        "    cmd = [\"nice\", \"-n\", \"19\", seven_z, \"t\", f\"-p{pwd}\", \"-y\", archive]\n"
        "    try:\n"
        "        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)\n"
        "        out = (p.stdout or \"\") + (p.stderr or \"\")\n"
        "        if \"Everything is Ok\" in out:\n"
        "            found_pwd = pwd\n"
        "            break\n"
        "    except Exception:\n"
        "        continue\n"
        "elapsed = round(time.time() - t0, 2)\n"
        "print(json.dumps({\n"
        "    \"found\": bool(found_pwd),\n"
        "    \"password\": found_pwd,\n"
        "    \"tested_count\": tested,\n"
        "    \"total_candidates\": len(candidates),\n"
        "    \"elapsed_sec\": elapsed\n"
        "}))\n"
        "'"
    )

    try:
        raw_output = await ssh_client.execute_command(remote_script)
        # Parse the last JSON line output from stdout
        json_line = None
        for line in reversed(raw_output.splitlines()):
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                json_line = line_str
                break

        if not json_line:
            logger.warning("[ArchiveRecovery] No valid JSON line in output: %s", raw_output[:300])
            return {
                "success": False,
                "found": False,
                "password": None,
                "message": f"Không nhận được phản hồi hợp lệ từ máy chủ: {raw_output.strip()[:180]}",
                "tested_count": 0,
            }

        result = json.loads(json_line)
        if "error" in result:
            if result["error"] == "FILE_NOT_FOUND":
                return {
                    "success": False,
                    "found": False,
                    "password": None,
                    "message": f"Không tìm thấy tệp nén tại `{archive_path}` trên máy chủ.",
                    "tested_count": 0,
                }
            return {
                "success": False,
                "found": False,
                "password": None,
                "message": f"Lỗi máy chủ: {result.get('error')}",
                "tested_count": 0,
            }

        return {
            "success": True,
            "found": result.get("found", False),
            "password": result.get("password"),
            "tested_count": result.get("tested_count", 0),
            "total_candidates": result.get("total_candidates", len(candidates)),
            "elapsed_sec": result.get("elapsed_sec", 0.0),
        }

    except Exception as e:
        logger.error("[ArchiveRecovery] Execution error on host: %s", type(e).__name__, exc_info=True)
        return {
            "success": False,
            "found": False,
            "password": None,
            "message": f"Lỗi khi thực thi dò mật khẩu trên máy chủ: {type(e).__name__}",
            "tested_count": 0,
        }

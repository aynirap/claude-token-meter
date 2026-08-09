"""Path A — อ่าน % rate limit ทางการของ Claude (แบบ Clawdmeter)

ยิง request จิ๋ว ๆ ไปที่ api.anthropic.com แล้วอ่านค่าจาก response headers
ที่ชื่อ anthropic-ratelimit-unified-* (ไม่สนใจ body)

ต้องมี OAuth token ของ Claude Code ใน Keychain ก่อน:
    ติดตั้ง claude CLI แล้ว `claude`  → login → จะสร้าง "Claude Code-credentials"

หมายเหตุ:
- request นี้ *กิน quota เล็กน้อย* (ใช้ Haiku, max_tokens=1) — ต่างจาก Path B
- token อ่านสด ๆ จาก Keychain ทุกครั้ง (Claude Code refresh ให้เอง)
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass, field

KEYCHAIN_SERVICE = "Claude Code-credentials"
API_URL = "https://api.anthropic.com/v1/messages"
OAUTH_BETA = "oauth-2025-04-20"
PING_MODEL = "claude-haiku-4-5"


class NoCredentials(Exception):
    pass


class PingError(Exception):
    pass


def read_token() -> str:
    """ดึง access_token จาก Keychain (raise NoCredentials ถ้าไม่มี)"""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NoCredentials(str(e))

    if out.returncode != 0 or not out.stdout.strip():
        raise NoCredentials("ไม่พบ Claude Code-credentials ใน Keychain")

    raw = out.stdout.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # บางเวอร์ชันเก็บเป็น token ดิบ ๆ
        return raw

    # โครงสร้างอาจซ้อนใต้ claudeAiOauth หรือ top-level
    for container in (data.get("claudeAiOauth"), data):
        if isinstance(container, dict):
            tok = container.get("accessToken") or container.get("access_token")
            if tok:
                return tok
    raise NoCredentials("อ่าน token จาก credentials ไม่ได้ (โครงสร้างไม่รู้จัก)")


@dataclass
class RateLimit:
    unified_5h: float | None = None      # % ใช้ไปในหน้าต่าง 5 ชม.
    unified_7d: float | None = None      # % ใช้ไปรายสัปดาห์
    reset_5h: int | None = None          # unix epoch
    reset_7d: int | None = None          # unix epoch
    representative: str | None = None    # หน้าต่างที่ binding (เช่น five_hour)
    raw: dict = field(default_factory=dict)  # header ทั้งหมดที่ขึ้นต้น anthropic-ratelimit-

    def reset_in(self, which: str = "5h") -> str:
        import time
        epoch = self.reset_5h if which == "5h" else self.reset_7d
        if not epoch:
            return "—"
        mins = int((epoch - time.time()) // 60)
        if mins <= 0:
            return "พร้อม reset"
        d, rem = divmod(mins, 60 * 24)
        h, m = divmod(rem, 60)
        if d:
            return f"{d}วัน {h}ชม"
        return f"{h}ชม {m}น" if h else f"{m} นาที"


def _to_pct(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    # header อาจเป็น 0..1 หรือ 0..100 — normalize ให้เป็น %
    return f * 100 if f <= 1.0 else f


def ping() -> RateLimit:
    """ยิง request จิ๋วแล้วอ่าน rate-limit headers"""
    token = read_token()
    body = json.dumps({
        "model": PING_MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "."}],
    }).encode()

    req = urllib.request.Request(API_URL, data=body, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("authorization", f"Bearer {token}")
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("anthropic-beta", OAUTH_BETA)

    try:
        resp = urllib.request.urlopen(req, timeout=20)
        headers = resp.headers
    except urllib.error.HTTPError as e:
        # แม้ error ก็มักมี rate-limit headers ติดมา — ลองอ่านก่อน
        headers = e.headers
        if e.code == 401:
            raise PingError("token หมดอายุ/ไม่ถูกต้อง — ลองรัน claude สักครั้งเพื่อ refresh") from e
        if headers is None:
            raise PingError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise PingError(f"network: {e.reason}") from e

    rl = RateLimit()
    for key in headers.keys():
        lk = key.lower()
        if lk.startswith("anthropic-ratelimit-"):
            rl.raw[lk] = headers[key]

    rl.unified_5h = _to_pct(rl.raw.get("anthropic-ratelimit-unified-5h-utilization"))
    rl.unified_7d = _to_pct(rl.raw.get("anthropic-ratelimit-unified-7d-utilization"))
    rl.representative = rl.raw.get("anthropic-ratelimit-unified-representative-claim")
    for attr, key in (("reset_5h", "anthropic-ratelimit-unified-5h-reset"),
                      ("reset_7d", "anthropic-ratelimit-unified-7d-reset")):
        try:
            setattr(rl, attr, int(rl.raw[key]))
        except (KeyError, ValueError, TypeError):
            pass
    return rl


def available() -> bool:
    """เช็คว่ามี credentials ให้ใช้ Path A ไหม (ไม่ยิง API)"""
    try:
        read_token()
        return True
    except NoCredentials:
        return False


if __name__ == "__main__":
    # ทดสอบ + dump header ทั้งหมด (ใช้ยืนยันชื่อ header จริง)
    try:
        rl = ping()
    except (NoCredentials, PingError) as e:
        print("!!", e)
        raise SystemExit(1)

    print("=== anthropic-ratelimit-* headers ทั้งหมด ===")
    for k, v in sorted(rl.raw.items()):
        print(f"  {k}: {v}")
    print()
    print(f"5h utilization: {rl.unified_5h}")
    print(f"7d utilization: {rl.unified_7d}")

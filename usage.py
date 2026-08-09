"""อ่าน usage logs ของ Claude Code จาก ~/.claude/projects/**/*.jsonl

ไม่เรียก API ใด ๆ — อ่านไฟล์ที่ Claude Code เขียนไว้ในเครื่องแล้ว
จึงไม่มี cost และไม่กิน quota เลย
"""
from __future__ import annotations

import json
import os
import glob
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"

# ราคาต่อ 1 ล้าน token (USD) — อ้างอิงราคา API pay-as-you-go
# ใช้คำนวณ "cost equivalent" เฉย ๆ (Pro plan จริงไม่ได้จ่ายตรงนี้)
#   cache_write ~1.25x ของ input, cache_read ~0.1x ของ input
PRICING = {
    "opus":   {"in": 5.0,  "out": 25.0, "cw": 6.25, "cr": 0.50},
    "sonnet": {"in": 3.0,  "out": 15.0, "cw": 3.75, "cr": 0.30},
    "haiku":  {"in": 1.0,  "out": 5.0,  "cw": 1.25, "cr": 0.10},
}
DEFAULT_PRICE = PRICING["opus"]


def _price_for(model: str) -> dict:
    m = (model or "").lower()
    if "haiku" in m:
        return PRICING["haiku"]
    if "sonnet" in m:
        return PRICING["sonnet"]
    if "opus" in m:
        return PRICING["opus"]
    return DEFAULT_PRICE


@dataclass
class Record:
    ts: datetime          # timestamp (UTC-aware)
    model: str
    input: int
    output: int
    cache_creation: int
    cache_read: int

    @property
    def total_tokens(self) -> int:
        return self.input + self.output + self.cache_creation + self.cache_read

    @property
    def cost(self) -> float:
        p = _price_for(self.model)
        return (
            self.input * p["in"]
            + self.output * p["out"]
            + self.cache_creation * p["cw"]
            + self.cache_read * p["cr"]
        ) / 1_000_000


def _parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        # รูปแบบเช่น "2026-08-09T06:40:22.123Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def iter_records(since: datetime | None = None):
    """yield Record ทุกตัวจาก log (กรองด้วย since ถ้ากำหนด)

    optimization: ข้ามไฟล์ที่ mtime เก่ากว่า since ไปเลย (ทั้งไฟล์ไม่มี record ในช่วง)
    """
    if not PROJECTS_DIR.exists():
        return

    since_epoch = since.timestamp() if since else None
    pattern = str(PROJECTS_DIR / "**" / "*.jsonl")

    for path in glob.iglob(pattern, recursive=True):
        try:
            if since_epoch is not None and os.path.getmtime(path) < since_epoch:
                continue
        except OSError:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = obj.get("message")
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict):
                        continue

                    ts = _parse_ts(obj.get("timestamp", ""))
                    if ts is None:
                        continue
                    if since is not None and ts < since:
                        continue

                    yield Record(
                        ts=ts,
                        model=msg.get("model", ""),
                        input=int(usage.get("input_tokens", 0) or 0),
                        output=int(usage.get("output_tokens", 0) or 0),
                        cache_creation=int(usage.get("cache_creation_input_tokens", 0) or 0),
                        cache_read=int(usage.get("cache_read_input_tokens", 0) or 0),
                    )
        except OSError:
            continue


@dataclass
class Summary:
    tokens: int = 0
    cost: float = 0.0
    messages: int = 0
    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    window_hours: float = 5.0
    oldest: datetime | None = None
    newest: datetime | None = None

    @property
    def reset_at(self) -> datetime | None:
        """เวลาที่ record เก่าสุดในหน้าต่างจะหลุดออก (= oldest + window)"""
        if self.oldest is None:
            return None
        return self.oldest + timedelta(hours=self.window_hours)


def summarize(window_hours: float = 5.0) -> Summary:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    s = Summary(window_hours=window_hours)
    for r in iter_records(since=since):
        s.tokens += r.total_tokens
        s.cost += r.cost
        s.messages += 1
        s.input += r.input
        s.output += r.output
        s.cache_creation += r.cache_creation
        s.cache_read += r.cache_read
        if s.oldest is None or r.ts < s.oldest:
            s.oldest = r.ts
        if s.newest is None or r.ts > s.newest:
            s.newest = r.ts
    return s


def human_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


if __name__ == "__main__":
    # ทดสอบ: python usage.py
    for hours in (5, 24, 24 * 7):
        s = summarize(window_hours=hours)
        label = {5: "5 ชม.", 24: "24 ชม.", 168: "7 วัน"}[hours]
        print(
            f"[{label:>6}] {human_tokens(s.tokens):>6} tokens | "
            f"{s.messages:>4} msgs | ~${s.cost:.2f} เทียบ API"
        )

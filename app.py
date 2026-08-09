"""Claude Token Meter — menu bar widget สำหรับ macOS

โชว์ % rate limit ทางการของ Claude (Pro plan) แบบ Clawdmeter
- Path A: ยิง API จิ๋ว ๆ อ่าน header anthropic-ratelimit-unified-* (% ทางการ)
- Path B: อ่าน log ในเครื่อง (token count + cost) — สำรอง/เสริม

ถ้ามี Claude Code credentials ใน Keychain → ใช้ Path A เป็นหลัก
ถ้าไม่มี หรือ ping พลาด → fallback ไป Path B

รัน:  ./.venv/bin/python app.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import rumps

import usage
import ratelimit

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS = {
    "window_hours": 5.0,
    "refresh_seconds": 180,        # Path A กิน quota นิดหน่อยต่อ ping → ตั้งห่างหน่อย
    "budget_tokens": 10_000_000,   # ใช้เฉพาะตอน fallback Path B
    "prefer": "auto",              # auto = ใช้ A ถ้ามี, ไม่งั้น B
}

REFRESH_OPTIONS = [60, 120, 180, 300, 600]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def dot_for(pct: float) -> str:
    if pct >= 90:
        return "🔴"
    if pct >= 60:
        return "🟡"
    return "🟢"


class MeterApp(rumps.App):
    def __init__(self):
        super().__init__("Claude Meter", title="⚪ …", quit_button=None)
        self.cfg = load_config()

        # เมนูรายละเอียด
        self.item_mode = rumps.MenuItem("โหมด: —")
        self.item_5h = rumps.MenuItem("5 ชม.: —")
        self.item_7d = rumps.MenuItem("สัปดาห์: —")
        self.item_local = rumps.MenuItem("log ในเครื่อง: —")
        self.item_cost = rumps.MenuItem("เทียบ API: —")
        self.item_updated = rumps.MenuItem("อัปเดต: —")

        refresh_menu = rumps.MenuItem("ช่วง refresh")
        for r in REFRESH_OPTIONS:
            refresh_menu.add(rumps.MenuItem(f"{r} วินาที",
                                            callback=self._make_refresh_cb(r)))

        self.menu = [
            self.item_mode,
            None,
            self.item_5h,
            self.item_7d,
            None,
            self.item_local,
            self.item_cost,
            None,
            self.item_updated,
            rumps.MenuItem("รีเฟรชเดี๋ยวนี้", callback=self.refresh),
            refresh_menu,
            None,
            rumps.MenuItem("ออก", callback=rumps.quit_application),
        ]

        self.timer = rumps.Timer(self.refresh, self.cfg["refresh_seconds"])
        self.timer.start()
        self.refresh(None)

    def _make_refresh_cb(self, value):
        def cb(_sender):
            self.cfg["refresh_seconds"] = value
            save_config(self.cfg)
            self.timer.stop()
            self.timer = rumps.Timer(self.refresh, value)
            self.timer.start()
            self.refresh(None)
        return cb

    # ---- แหล่งข้อมูล ----
    def _refresh_path_a(self) -> bool:
        """ลองใช้ Path A (official %). คืน True ถ้าสำเร็จ"""
        try:
            rl = ratelimit.ping()
        except (ratelimit.NoCredentials, ratelimit.PingError) as e:
            self.item_mode.title = f"โหมด: A ใช้ไม่ได้ ({e})"
            return False

        p5 = rl.unified_5h if rl.unified_5h is not None else 0.0
        p7 = rl.unified_7d if rl.unified_7d is not None else 0.0
        self.title = f"{dot_for(p5)} 5h {p5:.0f}% · 7d {p7:.0f}%"

        rep = " ◀ binding" if rl.representative == "five_hour" else ""
        self.item_mode.title = "โหมด: A (rate-limit ทางการ)"
        self.item_5h.title = f"5 ชม.: {p5:.0f}%  (reset {rl.reset_in('5h')}){rep}"
        rep7 = " ◀ binding" if rl.representative == "seven_day" else ""
        self.item_7d.title = f"สัปดาห์: {p7:.0f}%  (reset {rl.reset_in('7d')}){rep7}"
        return True

    def _refresh_path_b(self):
        """Path B: อ่าน log ในเครื่อง (token + cost)"""
        try:
            s = usage.summarize(window_hours=self.cfg["window_hours"])
        except Exception:
            self.item_local.title = "log ในเครื่อง: อ่านไม่ได้"
            self.item_cost.title = "เทียบ API: —"
            return None
        self.item_local.title = (
            f"log 5 ชม.: {usage.human_tokens(s.tokens)} tokens · {s.messages} ข้อความ"
        )
        self.item_cost.title = f"เทียบ API pay-as-you-go: ~${s.cost:.2f}"
        return s

    def refresh(self, _sender):
        used_a = False
        if self.cfg.get("prefer", "auto") != "b" and ratelimit.available():
            used_a = self._refresh_path_a()

        s = self._refresh_path_b()

        if not used_a:
            # fallback: ให้ title มาจาก Path B (token vs budget)
            if s is not None:
                budget = self.cfg["budget_tokens"] or DEFAULTS["budget_tokens"]
                pct = s.tokens / budget * 100 if budget else 0
                self.title = f"{dot_for(pct)} {usage.human_tokens(s.tokens)}"
                self.item_mode.title = "โหมด: B (log ในเครื่อง)"
            else:
                self.title = "⚪ –"
            self.item_5h.title = "5 ชม.: — (ต้อง login claude)"
            self.item_7d.title = "สัปดาห์: —"

        self.item_updated.title = (
            f"อัปเดต: {datetime.now().strftime('%H:%M:%S')} "
            f"(ทุก {self.cfg['refresh_seconds']}วิ)"
        )


if __name__ == "__main__":
    MeterApp().run()

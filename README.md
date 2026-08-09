# Claude Token Meter 🟢

Menu bar widget บน macOS ที่โชว์ปริมาณ token ที่ใช้ใน Claude Code
ในหน้าต่าง 5 ชั่วโมงล่าสุด — แรงบันดาลใจจาก [Clawdmeter](https://github.com/HermannBjorgvin/Clawdmeter)
แต่ทำเป็น widget บนจอด้วย Python แทน hardware

## แนวคิด

Clawdmeter ตัวจริงยิง API อ่าน rate-limit header — แต่บนเครื่องนี้ไม่มี
Claude Code CLI credentials ให้หยิบ (ใช้ Claude Code app ที่จัดการ auth เอง)

โปรเจกต์นี้เลยใช้อีกวิธี: **อ่าน usage log ที่ Claude Code เขียนไว้ในเครื่องแล้ว**
ที่ `~/.claude/projects/**/*.jsonl` — ทุกข้อความมี field `usage` (input/output/cache tokens)

ผลลัพธ์:
- ✅ **ไม่เรียก API เลย** → ไม่มี cost, ไม่กิน quota
- ✅ อัปเดตทันที ไม่ต้อง login อะไร
- ⚠️ วัด "จำนวน token ที่ใช้" ไม่ใช่ "% rate limit ทางการ" ของ Anthropic

## สองโหมด

**Path A — % rate limit ทางการ (แบบ Clawdmeter)** ← ใช้เป็นหลักถ้ามี credentials
- ยิง request จิ๋ว (Haiku, `max_tokens=1`) อ่าน header `anthropic-ratelimit-unified-5h/7d-utilization`
- Title: `🟢 5h 26% · 7d 4%` — % จริงของ Pro plan + เวลา reset
- ⚠️ กิน quota นิดหน่อยต่อ ping (จึง refresh ห่างหน่อย 180 วิ)
- ต้อง login `claude` CLI ก่อน (สร้าง `Claude Code-credentials` ใน Keychain)

**Path B — อ่าน log ในเครื่อง** ← fallback อัตโนมัติ / ข้อมูลเสริมใน dropdown
- อ่าน `~/.claude/projects/**/*.jsonl` → token count + cost เทียบ API
- ✅ ไม่เรียก API, ไม่มี cost, ไม่กิน quota

ระบบสลับให้เอง: มี credentials → A, token หมดอายุ/network พลาด → B

สี dot: 🟢 <60% · 🟡 60–90% · 🔴 >90%

## รัน

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run.sh
```

หรือทดสอบ parser เฉย ๆ (ไม่เปิด GUI):

```bash
./.venv/bin/python usage.py
```

## ตั้งค่า

แก้ผ่านเมนู หรือแก้ไฟล์ `config.json`:
- `window_hours` — ขนาดหน้าต่าง rolling (ค่าเริ่มต้น 5)
- `refresh_seconds` — ช่วง refresh (120)
- `budget_tokens` — เพดานประมาณสำหรับ gauge % (10M) — ปรับให้ตรงกับเพดานจริงที่สังเกตเอง

## roadmap

- [x] **Path B**: อ่าน log ในเครื่อง (zero cost)
- [x] **Path A**: ยิง API อ่าน `anthropic-ratelimit-unified-*-utilization` header → % ทางการ
- [ ] auto-refresh token เอง (ตอนนี้พึ่ง Claude Code app refresh ให้ — ถ้าไม่ได้ใช้นาน token อาจหมดอายุ แล้ว fallback ไป B)
- [ ] LaunchAgent เปิดอัตโนมัติตอน login

## หมายเหตุเรื่อง token หมดอายุ

Path A อ่าน token สด ๆ จาก Keychain ทุกครั้ง — Claude Code จะ refresh token ให้
ตอนคุณใช้งานปกติ ถ้าไม่ได้แตะ Claude Code นาน ๆ จน token หมดอายุ widget จะ
fallback ไป Path B เอง (ขึ้น "โหมด: A ใช้ไม่ได้") — แค่เปิด Claude Code ใช้สักครั้ง
ก็ refresh กลับมา

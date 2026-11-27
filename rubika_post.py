"""Post new Behesht Abzar products to Rubika channel.
Reads products.json, posts only NEW toks (tracked in posted_rubika.json).
Uses official Rubika Bot API: POST https://botapi.rubika.ir/v3/{token}/{method}

Secrets (GitHub repo > Settings > Secrets > Actions):
  RUBIKA_BOT_TOKEN : token from BotFather@ in Rubika
  RUBIKA_CHAT_ID   : channel chat_id (GUID) or @BahashtAbzar — code tries both.

If secrets are missing -> SKIP (exit 0), workflow stays green.
Max 5 posts per run to avoid spam / rate-limit.
"""
import json, os, sys, time

import requests

API_BASE = "https://botapi.rubika.ir/v3/{token}/{method}"
MAX_PER_RUN = 5

def call(token, method, payload, timeout=30):
    url = API_BASE.format(token=token, method=method)
    r = requests.post(url, json=payload, timeout=timeout)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}

def fa_num(n):
    try:
        return f"{int(n):,}".replace(",", "٬")
    except Exception:
        return str(n)

def build_text(x):
    price = fa_num(x.get("p", 0))
    lines = [
        f"🛠️ {x.get('t','')}",
        "",
        f"💰 قیمت: {price} تومان",
        f"📦 دسته: {x.get('c','')}",
        "",
        "📍 بهشت ابزار اهواز | کوت عبدالله، شریعتی، خ ۱۰",
        "🚚 پرداخت درب منزل در اهواز ✅",
        "",
        f"🔗 مشاهده در دیوار:\n{x.get('divar','')}",
        "",
        "📞 سفارش: 09361478804",
        "📲 روبیکا: @BahashtAbzar",
    ]
    return "\n".join(lines)

def try_send_text(token, chat_candidates, text):
    last = None
    for cid in chat_candidates:
        code, js = call(token, "sendMessage", {"chat_id": cid, "text": text})
        print(f"sendMessage to [{cid[:20]}...] http={code} resp={str(js)[:300]}", flush=True)
        if isinstance(js, dict) and js.get("status") == "OK":
            return True, cid, js
        last = js
        time.sleep(1)
    return False, None, last

def try_send_photo(token, chat_id, img_url, caption):
    """Download first image, upload to Rubika, send as file. Returns True/False."""
    try:
        print(f"downloading img: {img_url[:80]}...", flush=True)
        r = requests.get(img_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 5000:
            print(f"img download fail http={r.status_code} size={len(r.content)}", flush=True)
            return False
        if len(r.content) > 9 * 1024 * 1024:
            print("img too big, skip photo", flush=True)
            return False
        # 1) request upload slot
        code, js = call(token, "requestSendFile", {"type": "Image"})
        print(f"requestSendFile http={code} resp={str(js)[:300]}", flush=True)
        data = (js.get("data") if isinstance(js, dict) else None) or {}
        file_id = data.get("id") or data.get("file_id") or js.get("id")
        upload_url = data.get("upload_url") or data.get("uploadUrl") or data.get("url")
        if not file_id or not upload_url:
            print("no upload slot, fallback to text", flush=True)
            return False
        # 2) upload bytes
        files = {"file": ("photo.jpg", r.content, "image/jpeg")}
        up = requests.post(upload_url, files=files, timeout=60)
        print(f"upload http={up.status_code} resp={up.text[:200]}", flush=True)
        if up.status_code not in (200, 201):
            return False
        # 3) send file
        code2, js2 = call(token, "sendFile", {"chat_id": chat_id, "file_id": file_id, "text": caption})
        print(f"sendFile http={code2} resp={str(js2)[:300]}", flush=True)
        return isinstance(js2, dict) and js2.get("status") == "OK"
    except Exception as e:
        print(f"photo flow ERR: {str(e)[:200]}", flush=True)
        return False

def main():
    token = (os.environ.get("RUBIKA_BOT_TOKEN") or "").strip()
    chat_raw = (os.environ.get("RUBIKA_CHAT_ID") or "").strip()
    if not token or not chat_raw:
        print("RUBIKA SKIP: secrets RUBIKA_BOT_TOKEN / RUBIKA_CHAT_ID not set. Add them in repo Settings > Secrets > Actions.", flush=True)
        return 0
    try:
        prods = json.load(open("products.json", encoding="utf-8"))
    except Exception as e:
        print(f"products.json unreadable: {e}", flush=True)
        return 0
    try:
        posted = json.load(open("posted_rubika.json", encoding="utf-8"))
        if isinstance(posted, list):
            posted = {t: 1 for t in posted}
    except Exception:
        posted = {}
    # candidates: as-given + variants (with/without @)
    cands = []
    for c in [chat_raw, chat_raw.lstrip("@"), "@" + chat_raw.lstrip("@")]:
        if c and c not in cands:
            cands.append(c)
    print(f"products: {len(prods)}, already posted: {len(posted)}, chat candidates: {cands}", flush=True)
    news = [x for x in prods if x.get("tok") not in posted]
    print(f"new to post: {len(news)}", flush=True)
    if not news:
        print("nothing new.", flush=True)
        return 0
    # sanity: test token first
    code, js = call(token, "getMe", {})
    print(f"getMe http={code} resp={str(js)[:300]}", flush=True)
    done = 0
    working_chat = None
    for x in news[:MAX_PER_RUN]:
        tok = x.get("tok")
        caption = build_text(x)
        ok = False
        # first message: discover working chat_id with text
        if working_chat is None:
            ok, working_chat, _ = try_send_text(token, cands, caption)
            if ok:
                # try to also send photo as second message? keep simple: text already sent.
                # Optionally send photo follow-up for richer channel:
                img = (x.get("imgs") or [""])[0]
                if img:
                    ph = try_send_photo(token, working_chat, img, f"📸 {x.get('t','')}")
                    print(f"photo extra: {ph}", flush=True)
            else:
                print(f"FAILED {tok} — check bot is admin in channel + chat_id. Response logged above.", flush=True)
                break
        else:
            ok, _, _ = try_send_text(token, [working_chat], caption)
            if ok:
                img = (x.get("imgs") or [""])[0]
                if img:
                    ph = try_send_photo(token, working_chat, img, f"📸 {x.get('t','')}")
                    print(f"photo extra: {ph}", flush=True)
            else:
                print(f"FAILED {tok}", flush=True)
                break
        if ok:
            posted[tok] = 1
            done += 1
            print(f"posted {tok} ({done}/{min(len(news), MAX_PER_RUN)})", flush=True)
            time.sleep(2)
        else:
            break
    json.dump(posted, open("posted_rubika.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE posted_now={done} total_posted={len(posted)}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())

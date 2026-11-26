
"""Auto-update Behesht Abzar products from Divar profile.
Runs in GitHub Actions every hour + on demand.
Profile: https://divar.ir/pro/bxdrxdtU
Output: products.json + products.js (window.P = [...]) + last-check.txt
"""
import json, re, sys

PROFILE = "https://divar.ir/pro/bxdrxdtU"

def write_heartbeat(status, count=""):
    try:
        from datetime import datetime, timezone, timedelta
        tehran = timezone(timedelta(hours=3, minutes=30))
        now_utc = datetime.now(timezone.utc)
        now_thr = now_utc.astimezone(tehran)
        txt = (
            f"last check (Tehran): {now_thr:%Y-%m-%d %H:%M:%S}\n"
            f"last check (UTC): {now_utc:%Y-%m-%d %H:%M:%S}\n"
            f"status: {status}\n"
            f"products: {count}\n"
        )
        open("last-check.txt", "w", encoding="utf-8").write(txt)
        print("heartbeat: " + txt.replace("\n", " | "), flush=True)
    except Exception as e:
        print(f"heartbeat fail: {e}", flush=True)

def guess_cat(title: str) -> str:
    t = title or ""
    if "کارواش" in t: return "کارواش"
    if any(k in t for k in ["فرز", "پولیش", "سنگ", "سنباده"]): return "فرز و سنگ"
    if any(k in t for k in ["جوش", "اینورتر"]): return "جوشکاری"
    if any(k in t for k in ["سشوار", "حرارتی", "هیتر"]): return "حرارتی"
    if any(k in t for k in ["اتو لوله", "اتولوله", "کاور کولر", "کولر"]): return "تاسیسات"
    if any(k in t for k in ["بلوور", "دمنده", "مکنده"]): return "نظافت"
    if any(k in t for k in ["عمودبر", "اره", "فارسی", "رکسون"]): return "اره و فارسی‌بر"
    return "دریل و بتن‌کن"

def clean_title(raw: str) -> str:
    if not raw: return ""
    t = raw.replace("پرداخت درب منزل اهواز", "").replace("پرداخت درب منزل", "")
    t = t.replace("پرداخت درب اهواز", "").replace("ارسال فوری اهواز", "")
    t = re.sub(r"\s+", " ", t).strip(" -،,")
    return t[:120]

def main():
    from playwright.sync_api import sync_playwright
    tokens = []
    ads = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
                                   "--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(viewport={"width": 1280, "height": 900},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                            locale="fa-IR")
        pg = ctx.new_page()
        print("profile...", flush=True)
        try:
            pg.goto(PROFILE, timeout=90000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"PROFILE GOTO FAIL: {e}", flush=True)
            try:
                open("debug.html", "w", encoding="utf-8").write(pg.content())
                print("saved debug.html", flush=True)
            except Exception:
                pass
            b.close()
            write_heartbeat("FAIL profile-load", 0)
            print("RESULT: FAIL profile-load", flush=True)
            sys.exit(1)
        pg.wait_for_timeout(5000)
        for _ in range(10):
            pg.evaluate("window.scrollBy(0,1200)")
            pg.wait_for_timeout(600)
        pg.wait_for_timeout(2000)
        try:
            title = pg.title()
        except Exception:
            title = ""
        print(f"page title: {title}", flush=True)
        html_len = len(pg.content())
        print(f"page html len: {html_len}", flush=True)
        hrefs = pg.evaluate("()=>[...document.querySelectorAll('a[href*=\"/v/\"]')].map(a=>a.href)")
        print(f"links with /v/: {len(hrefs)}", flush=True)
        for h in hrefs:
            m = re.search(r"/v/(?:x|[^/\"?#]+)/([A-Za-z0-9_-]{7,10})(?:[/?#]|$)", h)
            if m and m.group(1) not in tokens:
                tokens.append(m.group(1))
        print(f"tokens: {len(tokens)}", flush=True)
        if len(tokens) < 3:
            print("No tokens found. Page may be blocked (security check / captcha).", flush=True)
            try:
                body_txt = pg.evaluate("()=>document.body.innerText.slice(0,500)")
                print(f"page text head: {body_txt}", flush=True)
                open("debug.html", "w", encoding="utf-8").write(pg.content())
                print("saved debug.html for inspection", flush=True)
            except Exception as e:
                print(f"debug save fail: {e}", flush=True)
            b.close()
            write_heartbeat("FAIL no-tokens", 0)
            print("RESULT: FAIL no-tokens (products NOT overwritten)", flush=True)
            sys.exit(1)
        for idx, tok in enumerate(tokens, 1):
            url = f"https://divar.ir/v/x/{tok}"
            try:
                pg.goto(url, timeout=90000, wait_until="domcontentloaded")
                pg.wait_for_timeout(2500)
                for _ in range(4):
                    pg.evaluate("window.scrollBy(0,800)")
                    pg.wait_for_timeout(350)
                ld = pg.evaluate("""()=>{
                  const el=document.querySelector('script[type="application/ld+json"]');
                  return el?el.textContent:"";
                }""")
                ptitle, price, one_img = "", 0, ""
                if ld:
                    try:
                        j = json.loads(ld)
                        if isinstance(j, list): j = j[0]
                        ptitle = j.get("name", "")
                        price = int(str(j.get("offers", {}).get("price", 0) or 0))
                        one_img = j.get("image", "")
                    except Exception:
                        pass
                if not ptitle:
                    try:
                        ptitle = pg.evaluate("()=>{const h=document.querySelector('h1');return h?h.innerText:document.title}")
                    except Exception:
                        ptitle = tok
                imgs = pg.evaluate("""()=>{const s=new Set();
                  document.querySelectorAll('img').forEach(im=>{let u=im.currentSrc||im.src||'';
                  if(u&&u.startsWith('http'))s.add(u.split('?')[0])});return [...s]}""")
                good = [u for u in imgs if "webp_post" in u]
                seen = []
                for u in good:
                    if u not in seen: seen.append(u)
                if not seen and one_img: seen = [one_img]
                links = pg.evaluate("()=>[...document.querySelectorAll('a')].map(a=>a.href)")
                pay = ""
                for h_ in links:
                    if "open-platform-redirect" in h_ and "tomanpay" in h_:
                        pay = h_; break
                ads[tok] = {"t": clean_title(ptitle) or tok, "p": price,
                             "imgs": seen[:6], "pay": pay or url}
                print(f"[{idx}/{len(tokens)}] {tok} | {ads[tok]['t'][:35]} | {price} | imgs:{len(seen)} pay:{bool(pay)}", flush=True)
            except Exception as e:
                print(f"[{idx}] {tok} ERR {str(e)[:150]}", flush=True)
        b.close()

    old_cat, old_pay = {}, {}
    try:
        old = json.load(open("products.json", encoding="utf-8"))
        for x in old:
            if "tok" in x:
                old_cat[x["tok"]] = x.get("c", "")
                if x.get("pay"): old_pay[x["tok"]] = x.get("pay")
    except Exception as e:
        print(f"old products.json read: {e}", flush=True)

    prods = []
    for i, tok in enumerate(tokens, 1):
        a = ads.get(tok, {"t": tok, "p": 0, "imgs": [], "pay": f"https://divar.ir/v/x/{tok}"})
        c = old_cat.get(tok) or guess_cat(a["t"])
        pay = a["pay"] if ("open-platform" in a["pay"]) else (old_pay.get(tok) or a["pay"])
        prods.append({"id": i, "tok": tok, "t": a["t"], "c": c, "p": a["p"],
                      "imgs": a["imgs"], "divar": f"https://divar.ir/v/x/{tok}", "pay": pay})
    prods = [x for x in prods if x["t"] != x["tok"] or x["imgs"]]
    for i, x in enumerate(prods, 1): x["id"] = i
    print(f"valid products: {len(prods)}", flush=True)
    if len(prods) < 3:
        write_heartbeat("FAIL too-few-products", len(prods))
        print("RESULT: FAIL too-few-products (products NOT overwritten)", flush=True)
        sys.exit(1)
    json.dump(prods, open("products.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    js = "window.P=" + json.dumps(prods, ensure_ascii=False) + ";\n"
    open("products.js", "w", encoding="utf-8").write(js)
    write_heartbeat("OK", len(prods))
    print(f"DONE products:{len(prods)} js_bytes:{len(js.encode('utf-8'))}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
            

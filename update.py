"""Auto-update Behesht Abzar products from Divar profile.
Profile: https://divar.ir/pro/bxdrxdtU
Output: products.json + products.js + last-check.txt
v6: NEVER shrink on partial load. Merge old+new.
    Missing old items are kept UNLESS their ad page is proven dead.
"""
import json, re, sys, time

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

FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬،", "0123456789,,")

def fa_num(s):
    try:
        return int(s.translate(FA).replace(",", "").replace(" ", ""))
    except Exception:
        return 0

def guess_cat(title):
    t = title or ""
    if "کارواش" in t: return "کارواش"
    if any(k in t for k in ["فرز", "پولیش", "سنگ", "سنباده"]): return "فرز و سنگ"
    if any(k in t for k in ["جوش", "اینورتر"]): return "جوشکاری"
    if any(k in t for k in ["سشوار", "حرارتی", "هیتر"]): return "حرارتی"
    if any(k in t for k in ["اتو لوله", "اتولوله", "کاور کولر", "کولر"]): return "تاسیسات"
    if any(k in t for k in ["بلوور", "دمنده", "مکنده"]): return "نظافت"
    if any(k in t for k in ["عمودبر", "اره", "فارسی", "رکسون"]): return "اره و فارسی‌بر"
    return "دریل و بتن‌کن"

def clean_title(raw):
    if not raw: return ""
    t = raw.replace("پرداخت درب منزل اهواز", "").replace("پرداخت درب منزل", "")
    t = t.replace("پرداخت درب اهواز", "").replace("ارسال فوری اهواز", "")
    t = re.sub(r"\s+", " ", t).strip(" -،,")
    return t[:120]

def ld_parse(ld_text):
    title, price, img = "", 0, ""
    if not ld_text: return title, price, img
    try:
        j = json.loads(ld_text)
    except Exception:
        return title, price, img
    objs = []
    if isinstance(j, list): objs = j
    elif isinstance(j, dict) and "@graph" in j and isinstance(j["@graph"], list): objs = j["@graph"]
    elif isinstance(j, dict): objs = [j]
    for o in objs:
        if not isinstance(o, dict): continue
        if not title and isinstance(o.get("name"), str): title = o["name"]
        off = o.get("offers")
        cand = []
        if isinstance(off, dict): cand = [off]
        elif isinstance(off, list): cand = [x for x in off if isinstance(x, dict)]
        for c in cand:
            for k in ("price", "lowPrice", "highPrice"):
                v = c.get(k)
                if v:
                    try: price = int(str(v).split(".")[0])
                    except Exception: pass
                    if price: break
            if price: break
        im = o.get("image")
        if isinstance(im, str) and im.startswith("http"): img = im
        elif isinstance(im, list) and im and isinstance(im[0], str): img = im[0]
        if title and price: break
    return title, price, img

def goto_retry(pg, url, tries=3, timeout=120000):
    for a in range(1, tries + 1):
        try:
            print(f"goto try {a}/{tries}: {url[:60]}", flush=True)
            pg.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return True
        except Exception as e:
            print(f"goto try {a} FAIL: {str(e)[:200]}", flush=True)
            time.sleep(4)
    print(f"goto ALL FAIL: {url}", flush=True)
    return False

DEAD_PHRASES = ["حذف شده", "یافت نشد", "وجود ندارد", "منقضی شده", "not found", "404"]

def is_ad_dead(pg):
    try:
        txt = pg.evaluate("()=>document.body.innerText.slice(0,4000)")
        t = txt or ""
        for ph in DEAD_PHRASES:
            if ph in t:
                return True
        try:
            title = pg.title() or ""
            if "404" in title or "یافت نشد" in title:
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False

def main():
    old_list, old_map = [], {}
    try:
        old_list = json.load(open("products.json", encoding="utf-8"))
        for x in old_list:
            if "tok" in x: old_map[x["tok"]] = x
        print(f"old products: {len(old_list)}", flush=True)
    except Exception as e:
        print(f"old products.json unreadable: {str(e)[:200]}", flush=True)

    from playwright.sync_api import sync_playwright
    tokens, ads = [], {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
                                   "--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(viewport={"width": 1280, "height": 900},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                            locale="fa-IR")
        pg = ctx.new_page()
        print("profile...", flush=True)
        if not goto_retry(pg, PROFILE, tries=3):
            try:
                open("debug.html", "w", encoding="utf-8").write(pg.content())
            except Exception:
                pass
            b.close()
            write_heartbeat("FAIL profile-load", len(old_list))
            print("RESULT: FAIL profile-load (divar did not answer, retry later)", flush=True)
            sys.exit(1)
        pg.wait_for_timeout(6000)
        prev, stable = -1, 0
        for s in range(30):
            pg.evaluate("window.scrollBy(0,1400)")
            pg.wait_for_timeout(900)
            try:
                hrefs = pg.evaluate("()=>[...document.querySelectorAll('a[href*=\"/v/\"]')].map(a=>a.href)")
            except Exception:
                hrefs = []
            tmp = []
            for h in hrefs:
                m = re.search(r"/v/(?:x|[^/\"?#]+)/([A-Za-z0-9_-]{7,10})(?:[/?#]|$)", h)
                if m and m.group(1) not in tmp: tmp.append(m.group(1))
            try:
                html_all = pg.content()
                for m in re.findall(r"/v/(?:x/)?([A-Za-z0-9_-]{7,10})", html_all):
                    if m not in tmp and len(m) >= 7: tmp.append(m)
            except Exception:
                pass
            print(f"scroll {s+1}: {len(tmp)} tokens", flush=True)
            if len(tmp) == prev: stable += 1
            else: stable = 0
            prev = len(tmp)
            tokens = tmp
            if stable >= 4 and len(tokens) >= 3: break
        print(f"final tokens: {len(tokens)}", flush=True)
        if len(tokens) < 3:
            try:
                open("debug.html", "w", encoding="utf-8").write(pg.content())
            except Exception:
                pass
            b.close()
            write_heartbeat("FAIL no-tokens", len(old_list))
            print("RESULT: FAIL no-tokens (products NOT overwritten)", flush=True)
            sys.exit(1)
        for idx, tok in enumerate(tokens, 1):
            url = f"https://divar.ir/v/x/{tok}"
            ok = goto_retry(pg, url, tries=2)
            if not ok:
                old = old_map.get(tok)
                if old:
                    ads[tok] = {"t": old.get("t", tok), "p": old.get("p", 0),
                                "imgs": old.get("imgs", []), "pay": old.get("pay", url)}
                    print(f"[{idx}/{len(tokens)}] {tok} kept-old (page fail)", flush=True)
                continue
            try:
                pg.wait_for_timeout(2800)
                for _ in range(3):
                    pg.evaluate("window.scrollBy(0,800)")
                    pg.wait_for_timeout(350)
                ld = pg.evaluate("""()=>{const el=document.querySelector('script[type="application/ld+json"]');return el?el.textContent:""}""")
                html = ""
                try: html = pg.content()
                except Exception: pass
                body_txt = ""
                try: body_txt = pg.evaluate("()=>document.body.innerText.slice(0,6000)")
                except Exception: pass
                ptitle, price, one_img = ld_parse(ld)
                if not price and html:
                    m2 = re.findall(r'"price"\s*:\s*"?(\d[\d.]*)"?', html)
                    for cand in m2:
                        try:
                            v = int(cand.split(".")[0])
                            if v >= 100000: price = v; break
                        except Exception: pass
                if not price and body_txt:
                    m3 = re.findall(r"([۰-۹0-9٬,\s]{4,})\s*تومان", body_txt)
                    best = 0
                    for cand in m3:
                        v = fa_num(cand)
                        if v > best: best = v
                    if best >= 100000: price = best
                if not ptitle:
                    try:
                        ptitle = pg.evaluate("()=>{const h=document.querySelector('h1');return h?h.innerText:document.title}")
                    except Exception:
                        ptitle = tok
                imgs = pg.evaluate("""()=>{const s=new Set();document.querySelectorAll('img').forEach(im=>{let u=im.currentSrc||im.src||'';if(u&&u.startsWith('http'))s.add(u.split('?')[0])});return [...s]}""")
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
                old = old_map.get(tok, {})
                if not price and old.get("p"): price = old["p"]
                if (not ptitle or ptitle == tok) and old.get("t"): ptitle = old["t"]
                if not seen and old.get("imgs"): seen = old["imgs"]
                if "open-platform" not in (pay or "") and old.get("pay"): pay = old["pay"]
                ads[tok] = {"t": clean_title(ptitle) or old.get("t", tok), "p": price or 0,
                            "imgs": seen[:6], "pay": pay or url}
                print(f"[{idx}/{len(tokens)}] {tok} | {ads[tok]['t'][:35]} | {price} | imgs:{len(seen)} pay:{bool(pay)}", flush=True)
            except Exception as e:
                print(f"[{idx}] {tok} ERR {str(e)[:150]}", flush=True)
                old = old_map.get(tok)
                if old:
                    ads[tok] = {"t": old.get("t", tok), "p": old.get("p", 0),
                                "imgs": old.get("imgs", []), "pay": old.get("pay", url)}
        # verify missing old ads: keep unless proven dead
        missing = [t for t in old_map if t not in tokens]
        print(f"missing old to verify: {len(missing)}", flush=True)
        dead = set()
        for tok in missing:
            url = f"https://divar.ir/v/x/{tok}"
            ok = goto_retry(pg, url, tries=2)
            if not ok:
                print(f"verify {tok}: page fail -> KEEP", flush=True)
                continue
            try:
                pg.wait_for_timeout(2500)
                if is_ad_dead(pg):
                    print(f"verify {tok}: DEAD -> remove", flush=True)
                    dead.add(tok)
                else:
                    print(f"verify {tok}: alive -> KEEP", flush=True)
            except Exception as e:
                print(f"verify {tok} ERR -> KEEP: {str(e)[:120]}", flush=True)
        b.close()
        kept_dead = dead

    prods = []
    for i, tok in enumerate(tokens, 1):
        a = ads.get(tok)
        if not a:
            old = old_map.get(tok)
            if old:
                a = {"t": old.get("t", tok), "p": old.get("p", 0),
                     "imgs": old.get("imgs", []), "pay": old.get("pay", f"https://divar.ir/v/x/{tok}")}
            else:
                continue
        c = old_map.get(tok, {}).get("c") or guess_cat(a["t"])
        prods.append({"id": 0, "tok": tok, "t": a["t"], "c": c, "p": a["p"],
                      "imgs": a["imgs"], "divar": f"https://divar.ir/v/x/{tok}", "pay": a["pay"]})
    # always merge missing old (except proven dead)
    for ot in old_list:
        tok = ot.get("tok")
        if tok and tok not in tokens and tok not in kept_dead:
            prods.append(ot)
            print(f"merged old {tok}", flush=True)
    # dedupe by tok keeping first
    seen_tok = set()
    uniq = []
    for x in prods:
        if x["tok"] not in seen_tok:
            seen_tok.add(x["tok"])
            uniq.append(x)
    prods = uniq
    prods = [x for x in prods if x["t"] != x["tok"] or x["imgs"]]
    print(f"valid fresh: {len(tokens)} + merged old = final {len(prods)} / old {len(old_list)} / dead {len(kept_dead)}", flush=True)
    if len(prods) < 3:
        write_heartbeat("FAIL too-few", len(old_list))
        print("RESULT: FAIL too-few (NOT overwritten)", flush=True)
        sys.exit(1)
    for i, x in enumerate(prods, 1): x["id"] = i
    print(f"final products: {len(prods)}", flush=True)
    json.dump(prods, open("products.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open("products.js", "w", encoding="utf-8").write("window.P=" + json.dumps(prods, ensure_ascii=False) + ";\n")
    write_heartbeat("OK", len(prods))
    print(f"DONE products:{len(prods)}", flush=True)

if __name__ == "__main__":
    sys.exit(main())

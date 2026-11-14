import datetime
import json
import os
import random
import re
import sys
import time
import requests

API_KEY = os.environ.get("ZENROWS_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: Set ZENROWS_API_KEY in Railway Variables!", flush=True)
    sys.exit(1)

PROFILE_1 = os.environ.get("PROFILE_1", "https://guns.lol/daaniiaa")
PROFILE_2 = os.environ.get("PROFILE_2", "https://guns.lol/naruto057")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))
BATCH_SLEEP_SECONDS = int(os.environ.get("BATCH_SLEEP_SECONDS", "300"))
INTRA_BATCH_MIN_SEC = 6.0
INTRA_BATCH_MAX_SEC = 12.0

# 0 = run until ZenRows credits are exhausted (HTTP 402)
MAX_TOTAL_RUNS = int(os.environ.get("MAX_TOTAL_RUNS", "0"))
# 0 = disabled (keeps running until credits finish); set e.g. 5 to auto-stop if counter stalls
MAX_STALE_BATCHES = int(os.environ.get("MAX_STALE_BATCHES", "0"))

COUNTRIES = [
    "gb", "de", "fr", "ca", "au", "nl", "es", "it", "se", "pl", "br",
    "jp", "sg", "pt", "ch", "be", "at", "no", "fi", "dk", "ie", "us",
]

ENDPOINT = "https://api.zenrows.com/v1/"
DETAILS_ENDPOINT = "https://api.zenrows.com/v1/subscriptions/self/details"
RETRYABLE_STATUSES = {422, 429, 500, 502, 503, 504}
STOP_STATUSES = {400, 401, 402, 403}


def mask_secret(text):
    return str(text).replace(API_KEY, "***HIDDEN***")


def log(msg):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {mask_secret(msg)}", flush=True)


def get_subscription_info():
    try:
        r = requests.get(DETAILS_ENDPOINT, headers={"X-API-Key": API_KEY}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def extract_diag(html, elem_id):
    m = re.search(rf'<script[^>]*id="{elem_id}"[^>]*>(.*?)</script>', html, re.I | re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def parse_views_int(val):
    if val is None:
        return None
    digits = re.sub(r"[^\d]", "", str(val))
    return int(digits) if digits else None


def extract_views_from_html(html):
    m = re.search(r'page_views\\?":(\d+)', html)
    return int(m.group(1)) if m else None


def extract_cf_ray(xhr_list):
    for item in xhr_list or []:
        headers = item.get("headers") or {}
        ray = headers.get("Cf-Ray") or headers.get("cf-ray")
        if ray:
            return ray
    return None


hook_js = (
    "if(!window.__zh){window.__zh=1;const L=window.__zn=[],F=window.fetch;"
    "if(F)window.fetch=async function(u,o){const s=typeof u==='string'?u:u.url||'',r0=[(o&&o.method)||'G',0,s,''];"
    "L.push(r0);try{const r=await F.apply(this,arguments);r0[1]=r.status;if(/analytics/i.test(s))try{r0[3]=(await r.clone().text()).slice(0,50);}catch(e){}return r;}catch(e){r0[3]='err';throw e;}};}"
)

prep_js = (
    "(()=>{const d=document,b=d.body||d.documentElement,cf=/just a moment|attention required/i.test(d.title)||!!d.querySelector('#challenge-form,#challenge-running');"
    "const p=cf?null:[...d.querySelectorAll('div,button')].filter(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect(),t=(e.innerText||'').trim();"
    "return s.display!=='none'&&+s.opacity>0&&s.pointerEvents!=='none'&&((s.position==='fixed'&&r.width>=innerWidth*0.7)||((s.position==='fixed'||s.cursor==='pointer')&&t.length>0&&t.length<=60&&/click|enter/i.test(t)));})"
    ".sort((a,b)=>(+getComputedStyle(b).zIndex||0)-(+getComputedStyle(a).zIndex||0))[0];"
    "if(p)p.setAttribute('data-zr-enter','1');else{const x=d.createElement('div');x.id='zr-d';x.setAttribute('data-zr-enter','1');"
    "x.style.cssText='position:fixed;left:2px;top:2px;width:10px;height:10px;opacity:.01;z-index:2147483647;';if(cf)x.onclick=e=>e.stopPropagation();b.appendChild(x);}})();"
)

safe_js = (
    "(()=>{const d=document,m=d.getElementById('zr-d'),h=!!m;if(m)m.remove();"
    "if(!/just a moment|attention required/i.test(d.title)&&!d.querySelector('#challenge-form,#challenge-running')){"
    "const el=d.querySelector('[data-zr-enter=\"1\"]'),st=!!el&&getComputedStyle(el).display!=='none';"
    "for(const[x,y]of((h||st)?[[180,180],[1740,180],[960,540]]:[[180,180]])){const e=d.elementFromPoint(x,y);"
    "if(e&&!e.closest('a,button,input,iframe,video,audio,svg')){['mousedown','mouseup','click'].forEach(v=>e.dispatchEvent(new MouseEvent(v,{bubbles:1,clientX:x,clientY:y})));e.click&&e.click();}}}})();"
)

go_p2_js = (
    "(()=>{try{const d=document,t=d.querySelector('[name=\"cf-turnstile-response\"]'),v=d.querySelector('[style*=\"bottom: 12px\"]');"
    "const n=window.__zn||[],ok=n.some(x=>/analytics\\/view/i.test(x[2])&&x[1]===200);"
    "sessionStorage.setItem('zr_p1',JSON.stringify({v:v?v.innerText.trim():null,ok,ts:t?t.value.length:0,net:n}));}catch(e){}"
    "location.href=" + json.dumps(PROFILE_2) + ";})();"
)

after_js = (
    "(()=>{try{const d=document,t=d.querySelector('[name=\"cf-turnstile-response\"]'),tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'';"
    "let p1=null;try{p1=JSON.parse(sessionStorage.getItem('zr_p1')||'null');}catch(e){}"
    "const s=d.createElement('script');s.id='zr-diag-after';s.type='application/json';"
    "s.textContent=JSON.stringify({tz,lang:navigator.language||'',p1,p2:{u:location.href,ts:t?t.value.length:0,net:window.__zn||[]}});"
    "(d.body||d.documentElement).appendChild(s);}catch(e){}})();"
)


def build_params(country):
    scroll_px = random.randint(180, 340)
    js_instructions = [
        {"evaluate": hook_js},
        {"wait": random.randint(2400, 2900)},
        {"evaluate": prep_js},
        {"click": "[data-zr-enter='1']"},
        {"wait": random.randint(1100, 1400)},
        {"evaluate": safe_js},
        {"evaluate": f"window.scrollBy(0,{scroll_px});"},
        {"wait": 5500},
        {"wait": 4500},
        {"evaluate": go_p2_js},
        {"wait": 3800},
        {"evaluate": hook_js},
        {"wait": random.randint(1500, 1800)},
        {"evaluate": prep_js},
        {"click": "[data-zr-enter='1']"},
        {"wait": random.randint(1100, 1300)},
        {"evaluate": safe_js},
        {"evaluate": f"window.scrollBy(0,{scroll_px});"},
        {"wait": 8000},
        {"evaluate": after_js},
    ]
    return {
        "apikey": API_KEY,
        "url": PROFILE_1,
        "js_render": "true",
        "premium_proxy": "true",
        "proxy_country": country,
        "js_instructions": json.dumps(js_instructions),
        "json_response": "true",
    }


def main():
    mode_lbl = "UNTIL CREDITS RUN OUT" if MAX_TOTAL_RUNS == 0 else str(MAX_TOTAL_RUNS)
    log(f"=== Railway Residential Dual Runner | MaxRuns={mode_lbl} | Batch={BATCH_SIZE} ===")
    log(f"Target 1: {PROFILE_1} -> Target 2: {PROFILE_2}")

    sub = get_subscription_info()
    if sub:
        log("Account Status: " + json.dumps(sub, ensure_ascii=False))

    bag = []
    last_country = None
    total_runs_done = 0
    total_credits = 0
    dania_200_total = 0
    naruto_200_total = 0

    baseline_dania = None
    baseline_naruto = None
    last_seen_dania = None
    last_seen_naruto = None
    stale_batches = 0

    batch_num = 0
    stop_reason = None

    while MAX_TOTAL_RUNS == 0 or total_runs_done < MAX_TOTAL_RUNS:
        batch_num += 1
        runs_in_this_batch = BATCH_SIZE if MAX_TOTAL_RUNS == 0 else min(BATCH_SIZE, MAX_TOTAL_RUNS - total_runs_done)
        batch_start_dania = last_seen_dania
        batch_start_naruto = last_seen_naruto

        log(f"\n--- Starting Batch #{batch_num} ({runs_in_this_batch} runs) ---")

        for step in range(1, runs_in_this_batch + 1):
            if not bag:
                bag = COUNTRIES[:]
                random.shuffle(bag)
                if last_country and len(bag) > 1 and bag[0] == last_country:
                    bag[0], bag[-1] = bag[-1], bag[0]

            country = bag.pop(0)
            last_country = country
            total_runs_done += 1
            run_lbl = f"{total_runs_done}" if MAX_TOTAL_RUNS == 0 else f"{total_runs_done}/{MAX_TOTAL_RUNS}"

            params = build_params(country)
            response = None

            for attempt in range(1, 3):
                t0 = time.time()
                try:
                    r = requests.get(ENDPOINT, params=params, timeout=(15, 180))
                    elapsed = round(time.time() - t0, 1)
                    if r.status_code == 200:
                        response = r
                        break
                    log(f"[Run {run_lbl} | {country.upper()} | Try {attempt}] HTTP {r.status_code} ({elapsed}s): {r.text[:250]}")
                    if r.status_code in STOP_STATUSES:
                        stop_reason = f"HTTP {r.status_code} (Credits exhausted or billing/param stop)"
                        break
                    if r.status_code in RETRYABLE_STATUSES and attempt == 1:
                        time.sleep(10)
                        continue
                    break
                except Exception as exc:
                    log(f"[Run {run_lbl} | {country.upper()} | Try {attempt}] NetError: {exc}")
                    if attempt == 1:
                        time.sleep(10)
                        continue
                    break

            if stop_reason:
                break

            if response is not None:
                cr = int(response.headers.get("X-Request-Credits") or 0)
                total_credits += cr
                data = response.json()
                html = data.get("html", "")
                diag = extract_diag(html, "zr-diag-after") or {}
                p1 = diag.get("p1") or {}
                p2 = diag.get("p2") or {}
                tz = diag.get("tz") or "?"
                lang = diag.get("lang") or "?"
                ray = extract_cf_ray(data.get("xhr")) or "?"
                colo = ray.split("-")[-1] if "-" in str(ray) else ray

                d_ok = bool(p1.get("ok")) or any(
                    isinstance(x, list) and len(x) >= 3 and "analytics/view" in str(x[2]).lower() and x[1] == 200
                    for x in (p1.get("net") or [])
                )
                n_ok = any(
                    isinstance(x, list) and len(x) >= 3 and "analytics/view" in str(x[2]).lower() and x[1] == 200
                    for x in (p2.get("net") or [])
                )
                if d_ok:
                    dania_200_total += 1
                if n_ok:
                    naruto_200_total += 1

                d_views = parse_views_int(p1.get("v"))
                n_views = extract_views_from_html(html) if "naruto057" in str(p2.get("u", "")).lower() else None

                if d_views is not None:
                    if baseline_dania is None:
                        baseline_dania = d_views
                    last_seen_dania = d_views
                if n_views is not None:
                    if baseline_naruto is None:
                        baseline_naruto = n_views
                    last_seen_naruto = n_views

                log(
                    f"[Run {run_lbl} | {country.upper()} | {tz}/{lang}/{colo}] "
                    f"Cr:{cr} (Tot:{total_credits}) | Dania:{'OK' if d_ok else 'MISS'}(v={d_views}) | "
                    f"Naruto:{'OK' if n_ok else 'MISS'}(v={n_views},ts={p2.get('ts')})"
                )

            if step < runs_in_this_batch:
                time.sleep(random.uniform(INTRA_BATCH_MIN_SEC, INTRA_BATCH_MAX_SEC))

        if stop_reason:
            log(f"Stopping cleanly: {stop_reason}")
            break

        if MAX_STALE_BATCHES > 0 and batch_num >= 2:
            d_grew = (batch_start_dania is not None and last_seen_dania is not None and last_seen_dania > batch_start_dania)
            n_grew = (batch_start_naruto is not None and last_seen_naruto is not None and last_seen_naruto > batch_start_naruto)
            if not d_grew and not n_grew:
                stale_batches += 1
                log(f"[WARN] No view growth in Batch #{batch_num} (stale={stale_batches}/{MAX_STALE_BATCHES})")
            else:
                stale_batches = 0
            if stale_batches >= MAX_STALE_BATCHES:
                log("AUTO-STOP: Counter did not grow across configured stale batches.")
                break

        if MAX_TOTAL_RUNS == 0 or total_runs_done < MAX_TOTAL_RUNS:
            log(f"--- Batch #{batch_num} finished. Sleeping {BATCH_SLEEP_SECONDS // 60} minutes... ---")
            time.sleep(BATCH_SLEEP_SECONDS)

    log("\n=== FINAL SUMMARY ===")
    log(f"Runs Attempted: {total_runs_done} | Total Credits Billed: {total_credits}")
    log(f"Dania 200s: {dania_200_total} | Views: {baseline_dania} -> {last_seen_dania}")
    log(f"Naruto 200s: {naruto_200_total} | Views: {baseline_naruto} -> {last_seen_naruto}")
    sys.exit(0)


if __name__ == "__main__":
    main()

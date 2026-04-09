#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IP to Username Generator v2.2 - Termux Edition
- Loop mode permanen (tidak perlu exit → run lagi)
- termux-clipboard-set untuk copy username
- Batch input, cache, history, export CSV
- Fallback chain: nevacloud → ip-api
"""

import re, requests, sys, time, csv, os, subprocess
from datetime import datetime
from bs4 import BeautifulSoup

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    COLOR = True
except ImportError:
    COLOR = False
    class Fore:
        GREEN = YELLOW = RED = CYAN = MAGENTA = WHITE = ""
    class Style:
        RESET_ALL = BRIGHT = ""

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_PREFIX  = "876fa2cd825d29262ef0__cr.id"
NEVA_URL     = "https://nevacloud.com/tools/check-ip/"
IPAPI_URL    = "http://ip-api.com/json/{ip}?fields=status,regionName,city,as,message,countryCode"
TIMEOUT      = 10
MAX_RETRY    = 2
# ─────────────────────────────────────────────────────────────────────────────

ASN_RE = re.compile(r'AS(\d+)', re.IGNORECASE)

_IP_PATTERN = re.compile(
    r'(?:'
    r'(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}'
    r'|(?:[0-9a-fA-F]{1,4}:){1,6}(?::[0-9a-fA-F]{1,4}){1,6}'
    r'|(?:[0-9a-fA-F]{1,4}:){1,7}:'
    r'|:(?::[0-9a-fA-F]{1,4}){1,7}'
    r'|::'
    r'|(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'
    r')'
)

_cache:   dict = {}   # ip → info dict
_history: list = []   # semua hasil sesi ini

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def c(color: str, text: str) -> str:
    return f"{color}{text}{Style.RESET_ALL}" if COLOR else text

def sanitize(s: str) -> str:
    if not s: return "unknown"
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s or "unknown"

def extract_asn_num(as_field: str) -> str:
    if not as_field: return "0"
    m = ASN_RE.search(as_field)
    if m: return m.group(1)
    digs = re.findall(r"\d+", as_field)
    return digs[0] if digs else "0"

def extract_ips(text: str) -> list:
    found, seen = [], set()
    for m in _IP_PATTERN.finditer(text):
        ip = m.group(0)
        if ip not in seen:
            seen.add(ip)
            found.append(ip)
    return found

# ─── CLIPBOARD (TERMUX) ───────────────────────────────────────────────────────
def copy_to_clipboard(text: str) -> bool:
    """Copy text ke clipboard via termux-clipboard-set."""
    if not text:
        return False
    try:
        proc = subprocess.Popen(
            ['termux-clipboard-set'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        proc.communicate(input=text.encode('utf-8'), timeout=5)
        if proc.returncode == 0:
            return True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    # Fallback: simpan ke file agar bisa dipaste manual
    try:
        clip_file = os.path.join(os.path.expanduser("~"), ".last_username.txt")
        with open(clip_file, 'w', encoding='utf-8') as f:
            f.write(text)
        print(c(Fore.YELLOW, f"  ⚠ Disimpan ke: {clip_file}  (cat ~/.last_username.txt)"))
    except Exception:
        print(c(Fore.YELLOW, f"  ⚠ Copy manual:\n  {text}"))
    return False

# ─── PARSERS ─────────────────────────────────────────────────────────────────
def parse_nevacloud_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    region = city = as_field = country_code = None

    for ln in lines:
        low = ln.lower()
        if ("region" in low or "provinsi" in low or "state" in low) and not region:
            parts = re.split(r'[:\u2022\-–]+', ln, 1)
            if len(parts) > 1 and parts[1].strip():
                region = parts[1].strip(); continue
        if ("city" in low or "kota" in low) and not city:
            parts = re.split(r'[:\u2022\-–]+', ln, 1)
            if len(parts) > 1 and parts[1].strip():
                city = parts[1].strip(); continue
        if ("asn" in low or "autonomous system" in low or low.startswith("as")) and not as_field:
            m = ASN_RE.search(ln)
            if m: as_field = "AS" + m.group(1); continue
            parts = re.split(r'[:\u2022\-–]+', ln, 1)
            if len(parts) > 1 and re.search(r"\d", parts[1]):
                as_field = parts[1].strip(); continue
        if ("country" in low or "negara" in low) and not country_code:
            parts = re.split(r'[:\u2022\-–]+', ln, 1)
            if len(parts) > 1 and parts[1].strip():
                val = parts[1].strip().upper()
                if 2 <= len(val) <= 3:
                    country_code = val

    if not (region or city or as_field):
        return None
    return {
        "region": region or "",
        "city": city or "",
        "as": as_field or "",
        "countryCode": country_code or ""
    }

# ─── LOOKUPS ─────────────────────────────────────────────────────────────────
def lookup_ipapi(ip: str) -> dict:
    try:
        r = requests.get(IPAPI_URL.format(ip=ip), timeout=TIMEOUT)
        j = r.json()
        if j.get("status") == "success":
            return {
                "status": "success",
                "region": j.get("regionName", ""),
                "city": j.get("city", ""),
                "as": j.get("as", ""),
                "countryCode": j.get("countryCode", "").upper(),
                "source": "ip-api"
            }
        return {"status": "fail", "message": j.get("message", "failed")}
    except Exception as e:
        return {"status": "fail", "message": f"ipapi_err:{e}"}

def lookup_nevacloud(ip: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ip-checker/2.0)"}
    try:
        r = requests.get(NEVA_URL, params={"ip": ip}, timeout=TIMEOUT, headers=headers)
        p = parse_nevacloud_html(r.text)
        if p:
            p.update({"status": "success", "source": "nevacloud"})
            return p
        r2 = requests.post(NEVA_URL, data={"ip": ip}, timeout=TIMEOUT, headers=headers)
        p2 = parse_nevacloud_html(r2.text)
        if p2:
            p2.update({"status": "success", "source": "nevacloud"})
            return p2
        return {"status": "fail", "message": "nevacloud_parse_failed"}
    except Exception as e:
        return {"status": "fail", "message": f"nevacloud_err:{e}"}

def lookup(ip: str, retry: int = MAX_RETRY) -> dict:
    """Lookup dengan cache + retry + fallback: nevacloud → ip-api."""
    if ip in _cache:
        cached = _cache[ip].copy()
        cached["source"] = cached.get("source", "?") + " (cached)"
        return cached

    for attempt in range(1, retry + 2):
        # Primary: nevacloud
        info = lookup_nevacloud(ip)

        # Enrichment: jika nevacloud OK tapi missing countryCode
        if info.get("status") == "success" and not info.get("countryCode"):
            enrich = lookup_ipapi(ip)
            if enrich.get("status") == "success":
                info["countryCode"] = enrich.get("countryCode", "")
                if not info.get("region") and enrich.get("region"):
                    info["region"] = enrich["region"]
                if not info.get("city") and enrich.get("city"):
                    info["city"] = enrich["city"]
                if not info.get("as") and enrich.get("as"):
                    info["as"] = enrich["as"]

        # Fallback: langsung ip-api
        if info.get("status") != "success":
            info = lookup_ipapi(ip)

        if info.get("status") == "success":
            _cache[ip] = info
            return info

        if attempt <= retry:
            print(c(Fore.YELLOW, f"  ↻ retry {attempt}/{retry}…"), end="\r", flush=True)
            time.sleep(1.2)

    return {"status": "fail", "message": "all_sources_failed"}

# ─── USERNAME BUILDER ─────────────────────────────────────────────────────────
def build_username(state: str, city: str, as_field: str, country_code: str = "id") -> str:
    cc      = (country_code or "id").lower()
    state_s = sanitize(state)
    city_s  = sanitize(city)
    asn     = extract_asn_num(as_field)
    prefix  = re.sub(r'(__cr\.)[a-z]+$', rf'\g<1>{cc}', BASE_PREFIX)
    return f"{prefix};state.{state_s};city.{city_s};asn.{asn}"

# ─── DISPLAY ─────────────────────────────────────────────────────────────────
def print_result(ip: str, info: dict, username: str):
    cc     = info.get("countryCode", "??")
    region = info.get("region", "-")
    city   = info.get("city", "-")
    asf    = info.get("as", "-")
    src    = info.get("source", "?")
    flag   = "🇮🇩" if cc == "ID" else ("🌐" if not cc else f"[{cc}]")

    print(c(Fore.CYAN,    f"\n  IP       : {ip}"))
    print(c(Fore.WHITE,   f"  Country  : {flag} {cc}  (→ __cr.{cc.lower()})"))
    print(c(Fore.WHITE,   f"  Region   : {region}"))
    print(c(Fore.WHITE,   f"  City     : {city}"))
    print(c(Fore.WHITE,   f"  AS       : {asf}"))
    print(c(Fore.MAGENTA, f"  Source   : {src}"))
    print(c(Fore.GREEN, Style.BRIGHT + f"\n  ✔ Username: {username}"))

    ok = copy_to_clipboard(username)
    if ok:
        print(c(Fore.GREEN, "  (copied to clipboard ✔)"))

def print_batch_summary(results: list):
    print(c(Fore.CYAN, "\n─── BATCH SUMMARY ─────────────────────────────────"))
    for ip, uname in results:
        status = c(Fore.GREEN, "✔") if uname else c(Fore.RED, "✗")
        print(f"  {status} {ip:<18} → {uname or 'FAILED'}")
    print(c(Fore.CYAN, "────────────────────────────────────────────────────"))

# ─── HISTORY ─────────────────────────────────────────────────────────────────
def print_history():
    if not _history:
        print(c(Fore.YELLOW, "  Belum ada history."))
        return
    print(c(Fore.CYAN, "\n─── HISTORY ────────────────────────────────────────"))
    for i, h in enumerate(_history, 1):
        print(f"  {i:>3}. [{h['timestamp']}] {h['ip']:<18} [{h['countryCode']}] → {h['username']}")
    print(c(Fore.CYAN, "────────────────────────────────────────────────────"))

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def export_history():
    if not _history:
        print(c(Fore.YELLOW, "  Belum ada history untuk di-export."))
        return
    fname = f"lookup_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ip","countryCode","region","city","as","username","source","timestamp"])
        w.writeheader()
        w.writerows(_history)
    print(c(Fore.GREEN, f"  ✔ Exported {len(_history)} entries → {fname}"))

# ─── PROCESS IP(S) ───────────────────────────────────────────────────────────
def process_ips(raw: str) -> list:
    ips = extract_ips(raw)
    if not ips:
        candidate = raw.strip()
        if candidate:
            print(c(Fore.RED, f"  ✗ '{candidate}' bukan IP valid."))
        return []

    results = []
    for ip in ips:
        print(c(Fore.YELLOW, f"\n[{ip}] lookup…"), end=" ", flush=True)
        info = lookup(ip)
        if info.get("status") != "success":
            print(c(Fore.RED, f"gagal → {info.get('message')}"))
            results.append((ip, ""))
            continue

        cc       = info.get("countryCode", "ID") or "ID"
        username = build_username(info.get("region",""), info.get("city",""), info.get("as",""), cc)
        print_result(ip, info, username)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _history.append({
            "ip": ip,
            "countryCode": cc,
            "region": info.get("region",""),
            "city": info.get("city",""),
            "as": info.get("as",""),
            "username": username,
            "source": info.get("source",""),
            "timestamp": ts,
        })
        results.append((ip, username))
        time.sleep(0.2)

    return results

# ─── HELP ────────────────────────────────────────────────────────────────────
def print_help():
    print(c(Fore.CYAN, """
  PERINTAH TERSEDIA:
    <ip>           → lookup satu IP
    <ip1 ip2 ...>  → lookup batch (pisah spasi/koma)
    history        → tampilkan history sesi ini
    export         → export history ke CSV
    clear          → bersihkan cache
    help           → tampilkan ini
    exit / q       → keluar
"""))

# ─── MAIN LOOP ───────────────────────────────────────────────────────────────
def main():
    print(c(Fore.CYAN, Style.BRIGHT + """
╔══════════════════════════════════════════════════════╗
║    IP to Username Generator  ★  Termux v2.2          ║
║    Loop Mode · Cache · Batch · Export CSV            ║
╚══════════════════════════════════════════════════════╝"""))
    print(c(Fore.WHITE, "  Ketik IP (satu atau banyak), 'help', atau 'exit'\n"))

    while True:
        try:
            raw = input(c(Fore.YELLOW, "  ❯ ")).strip()
        except EOFError:
            # Kalau di-pipe input habis, langsung selesai
            print(c(Fore.YELLOW, "\n  EOF. Bye!"))
            break
        except KeyboardInterrupt:
            print(c(Fore.YELLOW, "\n\n  Interrupted. Bye!"))
            break

        if not raw:
            continue

        cmd = raw.lower()
        if cmd in {"exit", "quit", "q"}:
            print(c(Fore.CYAN, "\n  Bye! Sampai jumpa."))
            break
        elif cmd == "help":
            print_help()
        elif cmd == "history":
            print_history()
        elif cmd == "export":
            export_history()
        elif cmd == "clear":
            _cache.clear()
            print(c(Fore.GREEN, "  Cache dibersihkan."))
        else:
            results = process_ips(raw)
            if len(results) > 1:
                print_batch_summary(results)
                # Copy username terakhir yang valid
                valid = [u for _, u in results if u]
                if valid:
                    copy_to_clipboard(valid[-1])
            elif results and results[0][1]:
                # Single IP sudah di-copy di print_result
                pass

if __name__ == "__main__":
    main()

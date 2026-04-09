#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re, requests, sys, time, csv, os, subprocess
from datetime import datetime
from bs4 import BeautifulSoup

# ─── COLOR ─────────────────────────────────────────────
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    COLOR = True
except:
    COLOR = False
    class Fore:
        GREEN = YELLOW = RED = CYAN = MAGENTA = WHITE = ""
    class Style:
        RESET_ALL = BRIGHT = ""

# ─── CONFIG ────────────────────────────────────────────
BASE_PREFIX = "876fa2cd825d29262ef0__cr.id"
NEVA_URL = "https://nevacloud.com/tools/check-ip/"
IPAPI_URL = "http://ip-api.com/json/{ip}?fields=status,regionName,city,as,message,countryCode"

# ─── CLIPBOARD FIX TERMUX ─────────────────────────────
def copy_to_clipboard(text):
    try:
        subprocess.run(["termux-clipboard-set", text])
    except:
        pass

# ─── HELPERS ───────────────────────────────────────────
def c(color, text):
    return f"{color}{text}{Style.RESET_ALL}" if COLOR else text

def sanitize(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower()) or "unknown"

def extract_asn_num(as_field):
    m = re.search(r'AS(\d+)', as_field or "")
    return m.group(1) if m else "0"

# ─── LOOKUP SIMPLE (dipersingkat biar stabil) ──────────
def lookup_ip(ip):
    try:
        r = requests.get(IPAPI_URL.format(ip=ip), timeout=5).json()
        if r.get("status") == "success":
            return r
    except:
        pass
    return None

# ─── USERNAME ──────────────────────────────────────────
def build_username(region, city, asn, cc):
    prefix = re.sub(r'(__cr\.)[a-z]+$', rf'\1{cc.lower()}', BASE_PREFIX)
    return f"{prefix};state.{sanitize(region)};city.{sanitize(city)};asn.{asn}"

# ─── MAIN PROCESS ──────────────────────────────────────
def process(ip):
    print(c(Fore.YELLOW, f"\n[{ip}] lookup..."))

    data = lookup_ip(ip)
    if not data:
        print(c(Fore.RED, "  ✗ gagal"))
        return None

    cc = data.get("countryCode", "ID")
    region = data.get("regionName", "")
    city = data.get("city", "")
    asn = extract_asn_num(data.get("as", ""))

    username = build_username(region, city, asn, cc)

    print(c(Fore.GREEN, f"  ✔ {username}"))

    copy_to_clipboard(username)
    return username

# ─── MAIN LOOP ─────────────────────────────────────────
def main():
    print("Username Generator (Termux FIX)\n")

    while True:
        ip = input("❯ ").strip()
        if ip in ["exit", "q"]:
            break
        process(ip)

if __name__ == "__main__":
    main()

"""
dubai_agent/scraper_villas.py
Scraping ciblé : LOYERS de villas 3-5BR
Jumeirah 1/2/3, Umm Suqeim 1/2, Al Safa 1/2, Al Manara, Al Wasl
Toutes les valeurs sont converties en LOYER ANNUEL AED pour permettre les comparaisons.
"""

import asyncio
import sqlite3
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from playwright.async_api import async_playwright, Page

DB_PATH = "dubai_realestate.db"

# ── Zones cibles ──────────────────────────────────────────────────────────────
TARGET_ZONES = {
    "Jumeirah 1":     ["jumeirah 1", "jumeirah1", "jumeirah - 1"],
    "Jumeirah 2":     ["jumeirah 2", "jumeirah2", "jumeirah - 2"],
    "Jumeirah 3":     ["jumeirah 3", "jumeirah3", "jumeirah - 3"],
    "Umm Suqeim 1":   ["umm suqeim 1", "umm suqueim 1", "umm suqeim1"],
    "Umm Suqeim 2":   ["umm suqeim 2", "umm suqueim 2", "umm suqeim2"],
    "Al Safa 1":      ["al safa 1", "alsafa 1", "al safa1"],
    "Al Safa 2":      ["al safa 2", "alsafa 2", "al safa2"],
    "Al Manara":      ["al manara", "manara"],
    "Al Wasl":        ["al wasl", "alwasl"],
    "Al Quoz 1":      ["al quoz 1"],
    "Madinat Jumeirah": ["madinat jumeirah", "madinat"],
}

# URLs LOCATION (to-rent) villas 3-5BR
BAYUT_URLS = [
    "https://www.bayut.com/to-rent/villas/dubai/jumeirah/jumeirah-1/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/jumeirah/jumeirah-2/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/jumeirah/jumeirah-3/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/umm-suqeim/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/al-safa/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/al-manara/?beds=3,4,5",
    "https://www.bayut.com/to-rent/villas/dubai/al-wasl/?beds=3,4,5",
]

PROPERTYFINDER_URLS = [
    "https://www.propertyfinder.ae/en/search?l=2&c=2&t=4&ob=mr&bdr=3&nbds=5&ne=jumeirah-1",
    "https://www.propertyfinder.ae/en/search?l=2&c=2&t=4&ob=mr&bdr=3&nbds=5&ne=jumeirah-2",
    "https://www.propertyfinder.ae/en/search?l=2&c=2&t=4&ob=mr&bdr=3&nbds=5&ne=jumeirah-3",
    "https://www.propertyfinder.ae/en/search?l=2&c=2&t=4&ob=mr&bdr=3&nbds=5&ne=umm-suqeim",
    "https://www.propertyfinder.ae/en/search?l=2&c=2&t=4&ob=mr&bdr=3&nbds=5&ne=al-safa",
]

# ── Dataclass ─────────────────────────────────────────────────────────────────
@dataclass
class RentalListing:
    source: str
    title: str
    zone: str
    district_raw: str
    rent_annual_aed: int          # Loyer ANNUEL AED (normalisé — valeur de référence)
    rent_monthly_aed: int         # rent_annual / 12
    sqft: Optional[int]
    rent_per_sqft_annual: Optional[float]   # AED/sqft/an
    bedrooms: int
    bathrooms: Optional[int]
    cheques: Optional[int]        # Nb de chèques (1=annuel, 4=trimestriel, 12=mensuel)
    furnished: Optional[bool]
    url: str
    scraped_at: str
    listing_age_days: Optional[int]

# ── Database ──────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rental_listings (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            source                TEXT,
            title                 TEXT,
            zone                  TEXT,
            district_raw          TEXT,
            rent_annual_aed       INTEGER,
            rent_monthly_aed      INTEGER,
            sqft                  INTEGER,
            rent_per_sqft_annual  REAL,
            bedrooms              INTEGER,
            bathrooms             INTEGER,
            cheques               INTEGER,
            furnished             INTEGER,
            url                   TEXT UNIQUE,
            scraped_at            TEXT,
            listing_age_days      INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rental_weekly_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            week_date        TEXT,
            zone             TEXT,
            bedrooms         INTEGER,
            avg_rent_annual  REAL,
            med_rent_annual  REAL,
            min_rent_annual  INTEGER,
            max_rent_annual  INTEGER,
            avg_rent_sqft    REAL,
            listing_count    INTEGER,
            UNIQUE(week_date, zone, bedrooms)
        )
    """)
    conn.commit()
    conn.close()

def save_listings(listings: list[RentalListing]) -> int:
    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    for l in listings:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO rental_listings
                (source,title,zone,district_raw,rent_annual_aed,rent_monthly_aed,
                 sqft,rent_per_sqft_annual,bedrooms,bathrooms,cheques,furnished,
                 url,scraped_at,listing_age_days)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (l.source, l.title, l.zone, l.district_raw,
                  l.rent_annual_aed, l.rent_monthly_aed,
                  l.sqft, l.rent_per_sqft_annual,
                  l.bedrooms, l.bathrooms, l.cheques, l.furnished,
                  l.url, l.scraped_at, l.listing_age_days))
            inserted += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return inserted

def save_weekly_snapshot():
    conn = sqlite3.connect(DB_PATH)
    week = datetime.now().strftime("%Y-W%W")
    rows = conn.execute("""
        SELECT zone, bedrooms,
               AVG(rent_annual_aed), MIN(rent_annual_aed), MAX(rent_annual_aed),
               AVG(rent_per_sqft_annual), COUNT(*)
        FROM rental_listings
        WHERE scraped_at >= date('now','-7 days')
        GROUP BY zone, bedrooms
    """).fetchall()
    for r in rows:
        conn.execute("""
            INSERT OR REPLACE INTO rental_weekly_snapshots
            (week_date,zone,bedrooms,avg_rent_annual,min_rent_annual,max_rent_annual,avg_rent_sqft,listing_count)
            VALUES (?,?,?,?,?,?,?,?)
        """, (week, r[0], r[1], round(r[2]), r[3], r[4], round(r[5] or 0, 1), r[6]))
    conn.commit()
    conn.close()
    print(f"  [DB] Snapshot loyers {week}: {len(rows)} combinaisons zone×chambres")

# ── Helpers ───────────────────────────────────────────────────────────────────
def normalize_rent_to_annual(amount: int, text_context: str) -> int:
    """
    Les annonces à Dubaï affichent parfois le loyer mensuel ou trimestriel.
    Règle empirique :
      - Si > 500 000 → probablement annuel (loyer villa annuel max ~800K AED)
      - Si 20 000 – 120 000 → probablement mensuel → x12
      - Sinon → on garde tel quel (annuel)
    """
    ctx = text_context.lower()
    if "per month" in ctx or "/month" in ctx or "monthly" in ctx:
        return amount * 12
    if "per year" in ctx or "/year" in ctx or "yearly" in ctx or "annual" in ctx or "p.a" in ctx:
        return amount
    # Heuristique sur la valeur
    if 10_000 <= amount <= 150_000:
        return amount * 12   # probablement mensuel
    return amount            # probablement annuel

def clean_amount(txt: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", txt or "")
    return int(digits) if digits else None

def clean_sqft(txt: str) -> Optional[int]:
    m = re.search(r"([\d,]+)\s*(?:sqft|sq\.ft|ft²|sqm)", txt or "", re.I)
    if m:
        val = int(m.group(1).replace(",", ""))
        if "sqm" in txt.lower():
            val = int(val * 10.764)
        return val
    return None

def extract_bedrooms(txt: str) -> Optional[int]:
    m = re.search(r"(\d)\s*(?:bed|br|bedroom)", txt or "", re.I)
    if m:
        n = int(m.group(1))
        return n if 3 <= n <= 5 else None
    return None

def extract_cheques(txt: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*cheque", txt or "", re.I)
    return int(m.group(1)) if m else None

def is_furnished(txt: str) -> Optional[bool]:
    txt = (txt or "").lower()
    if "furnished" in txt and "unfurnished" not in txt:
        return True
    if "unfurnished" in txt:
        return False
    return None

def normalize_zone(location_text: str) -> Optional[str]:
    lt = location_text.lower()
    for zone, variants in TARGET_ZONES.items():
        if any(v in lt for v in variants):
            return zone
    return None

# ── Scrapers ──────────────────────────────────────────────────────────────────
async def scrape_bayut(page: Page) -> list[RentalListing]:
    results = []
    for url in BAYUT_URLS:
        zone_hint = url.split("/")[-2].replace("-", " ").title()
        print(f"    → Bayut {zone_hint}")
        try:
            await page.goto(url, timeout=45000, wait_until="networkidle")
            await page.wait_for_timeout(2500)
            cards = await page.query_selector_all(
                "[class*='property-card'], [data-testid='listing-card'], article"
            )
            for card in cards[:40]:
                try:
                    title_el = await card.query_selector("[class*='title'], h2, h3")
                    price_el = await card.query_selector("[class*='price']")
                    loc_el   = await card.query_selector("[class*='location'], [class*='address']")
                    area_el  = await card.query_selector("[aria-label*='sqft'], [class*='area']")
                    beds_el  = await card.query_selector("[aria-label*='bed'], [class*='bed']")
                    baths_el = await card.query_selector("[aria-label*='bath'], [class*='bath']")
                    link_el  = await card.query_selector("a[href]")
                    full_txt = (await card.inner_text()).lower()

                    title_txt = (await title_el.inner_text()).strip() if title_el else ""
                    price_txt = (await price_el.inner_text()).strip() if price_el else ""
                    loc_txt   = (await loc_el.inner_text()).strip()   if loc_el   else ""
                    area_txt  = (await area_el.inner_text()).strip()  if area_el  else ""
                    beds_txt  = (await beds_el.inner_text()).strip()  if beds_el  else ""
                    baths_txt = (await baths_el.inner_text()).strip() if baths_el else ""
                    href      = await link_el.get_attribute("href")   if link_el  else ""

                    raw_amt = clean_amount(price_txt)
                    sqft    = clean_sqft(area_txt)
                    beds    = extract_bedrooms(beds_txt) or extract_bedrooms(title_txt)
                    zone    = normalize_zone(loc_txt) or normalize_zone(title_txt)

                    if not raw_amt or not zone or not beds:
                        continue

                    annual = normalize_rent_to_annual(raw_amt, full_txt)
                    # Sanity check : loyer annuel villa Dubai 3-5BR entre 100K et 900K AED
                    if not (100_000 <= annual <= 900_000):
                        continue

                    results.append(RentalListing(
                        source="Bayut",
                        title=title_txt[:140],
                        zone=zone,
                        district_raw=loc_txt[:100],
                        rent_annual_aed=annual,
                        rent_monthly_aed=annual // 12,
                        sqft=sqft,
                        rent_per_sqft_annual=round(annual / sqft, 1) if sqft else None,
                        bedrooms=beds,
                        bathrooms=clean_amount(baths_txt),
                        cheques=extract_cheques(full_txt),
                        furnished=is_furnished(full_txt),
                        url=f"https://www.bayut.com{href}" if href.startswith("/") else href,
                        scraped_at=datetime.now().isoformat(),
                        listing_age_days=None,
                    ))
                except Exception:
                    continue
        except Exception as e:
            print(f"    ❌ Erreur Bayut {zone_hint}: {e}")
    return results

async def scrape_propertyfinder(page: Page) -> list[RentalListing]:
    results = []
    for url in PROPERTYFINDER_URLS:
        zone_hint = url.split("ne=")[-1] if "ne=" in url else "?"
        print(f"    → PropertyFinder {zone_hint}")
        try:
            await page.goto(url, timeout=45000, wait_until="networkidle")
            await page.wait_for_timeout(2500)
            cards = await page.query_selector_all(
                "[class*='card'], article, [data-testid*='property']"
            )
            for card in cards[:40]:
                try:
                    price_el = await card.query_selector("[class*='price']")
                    title_el = await card.query_selector("h2, h3, [class*='title']")
                    loc_el   = await card.query_selector("[class*='location']")
                    area_el  = await card.query_selector("[class*='area']")
                    beds_el  = await card.query_selector("[class*='bed']")
                    link_el  = await card.query_selector("a[href]")
                    full_txt = (await card.inner_text()).lower()

                    price_txt = (await price_el.inner_text()) if price_el else ""
                    title_txt = (await title_el.inner_text()) if title_el else ""
                    loc_txt   = (await loc_el.inner_text())   if loc_el   else ""
                    area_txt  = (await area_el.inner_text())  if area_el  else ""
                    beds_txt  = (await beds_el.inner_text())  if beds_el  else ""
                    href      = await link_el.get_attribute("href") if link_el else ""

                    raw_amt = clean_amount(price_txt)
                    sqft    = clean_sqft(area_txt)
                    beds    = extract_bedrooms(beds_txt) or extract_bedrooms(title_txt)
                    zone    = normalize_zone(loc_txt) or normalize_zone(title_txt)

                    if not raw_amt or not zone or not beds:
                        continue

                    annual = normalize_rent_to_annual(raw_amt, full_txt)
                    if not (100_000 <= annual <= 900_000):
                        continue

                    results.append(RentalListing(
                        source="PropertyFinder",
                        title=title_txt[:140].strip(),
                        zone=zone,
                        district_raw=loc_txt[:100],
                        rent_annual_aed=annual,
                        rent_monthly_aed=annual // 12,
                        sqft=sqft,
                        rent_per_sqft_annual=round(annual / sqft, 1) if sqft else None,
                        bedrooms=beds,
                        bathrooms=None,
                        cheques=extract_cheques(full_txt),
                        furnished=is_furnished(full_txt),
                        url=f"https://www.propertyfinder.ae{href}" if href.startswith("/") else href,
                        scraped_at=datetime.now().isoformat(),
                        listing_age_days=None,
                    ))
                except Exception:
                    continue
        except Exception as e:
            print(f"    ❌ Erreur PF: {e}")
    return results

# ── Run ───────────────────────────────────────────────────────────────────────
async def run_villa_scraping() -> list[RentalListing]:
    print("\n🏡 Scraping LOYERS villas 3-5BR — Jumeirah / Umm Suqeim / Al Safa")
    init_db()
    all_listings: list[RentalListing] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-AE",
            timezone_id="Asia/Dubai",
        )
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        print("\n  📡 Bayut.com — Villas à louer...")
        bayut = await scrape_bayut(page)
        all_listings.extend(bayut)
        print(f"  ✅ Bayut: {len(bayut)} annonces de location")

        print("\n  📡 PropertyFinder.ae — Villas à louer...")
        pf = await scrape_propertyfinder(page)
        all_listings.extend(pf)
        print(f"  ✅ PropertyFinder: {len(pf)} annonces de location")

        await browser.close()

    n_saved = save_listings(all_listings)
    save_weekly_snapshot()

    # Résumé par zone
    by_zone: dict[str, list] = {}
    for l in all_listings:
        by_zone.setdefault(l.zone, []).append(l)
    print(f"\n  📊 Loyers annuels par zone:")
    for zone, lst in sorted(by_zone.items()):
        rents = [l.rent_annual_aed for l in lst]
        print(f"     {zone:<18} {len(lst):>3} annonces  "
              f"moy AED {sum(rents)//len(rents):>9,}/an")
    print(f"\n  💾 {n_saved}/{len(all_listings)} nouvelles annonces sauvegardées")
    return all_listings


if __name__ == "__main__":
    asyncio.run(run_villa_scraping())

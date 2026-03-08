"""
dubai_agent/scraper_villas.py
Scrape PropertyFinder.ae directement — aucune clé API requise
"""

import sqlite3, os, json, time, re
import urllib.request, urllib.parse
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

DB_PATH = "dubai_realestate.db"

# ── Zones cibles PropertyFinder ───────────────────────────────────────────────
# slug = identifiant URL PropertyFinder pour chaque zone
ZONES = [
    {"label": "Jumeirah 1",   "slug": "jumeirah-1"},
    {"label": "Jumeirah 2",   "slug": "jumeirah-2"},
    {"label": "Jumeirah 3",   "slug": "jumeirah-3"},
    {"label": "Umm Suqeim 1", "slug": "umm-suqeim-1"},
    {"label": "Umm Suqeim 2", "slug": "umm-suqeim-2"},
    {"label": "Al Safa 1",    "slug": "al-safa-1"},
    {"label": "Al Safa 2",    "slug": "al-safa-2"},
    {"label": "Al Manara",    "slug": "al-manara"},
    {"label": "Al Wasl",      "slug": "al-wasl"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.propertyfinder.ae/",
}


@dataclass
class RentalListing:
    source: str
    title: str
    zone: str
    district_raw: str
    rent_annual_aed: int
    rent_monthly_aed: int
    sqft: Optional[int]
    rent_per_sqft_annual: Optional[float]
    bedrooms: int
    bathrooms: Optional[int]
    cheques: Optional[int]
    furnished: Optional[bool]
    url: str
    scraped_at: str
    listing_age_days: Optional[int]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rental_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, title TEXT, zone TEXT, district_raw TEXT,
            rent_annual_aed INTEGER, rent_monthly_aed INTEGER,
            sqft INTEGER, rent_per_sqft_annual REAL,
            bedrooms INTEGER, bathrooms INTEGER,
            cheques INTEGER, furnished INTEGER,
            url TEXT UNIQUE, scraped_at TEXT, listing_age_days INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rental_weekly_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_date TEXT, zone TEXT, bedrooms INTEGER,
            avg_rent_annual REAL, med_rent_annual REAL,
            min_rent_annual INTEGER, max_rent_annual INTEGER,
            avg_rent_sqft REAL, listing_count INTEGER,
            UNIQUE(week_date, zone, bedrooms)
        )
    """)
    conn.commit()
    conn.close()


def save_listings(listings):
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
                  l.sqft, l.rent_per_sqft_annual, l.bedrooms,
                  l.bathrooms, l.cheques,
                  int(l.furnished) if l.furnished is not None else None,
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
               AVG(rent_annual_aed), MIN(rent_annual_aed),
               MAX(rent_annual_aed), AVG(rent_per_sqft_annual), COUNT(*)
        FROM rental_listings
        WHERE scraped_at >= date('now','-7 days')
        GROUP BY zone, bedrooms
    """).fetchall()
    for r in rows:
        conn.execute("""
            INSERT OR REPLACE INTO rental_weekly_snapshots
            (week_date,zone,bedrooms,avg_rent_annual,min_rent_annual,
             max_rent_annual,avg_rent_sqft,listing_count)
            VALUES (?,?,?,?,?,?,?,?)
        """, (week, r[0], r[1], round(r[2]), r[3], r[4],
              round(r[5] or 0, 1), r[6]))
    conn.commit()
    conn.close()
    print(f"  [DB] Snapshot {week}: {len(rows)} combinaisons")


def fetch_propertyfinder(slug: str, page: int = 1) -> list:
    """
    Appel API interne PropertyFinder — retourne les annonces en JSON.
    URL pattern: /en/plp/rent/villa/?neighborhoodId=...&bedroom=3,4,5
    On utilise leur endpoint de recherche qui retourne du JSON.
    """
    params = urllib.parse.urlencode({
        "c":         "2",          # 2 = location/rent
        "t":         "4",          # 4 = villa
        "nb":        slug,
        "rms":       "3,4,5",      # 3, 4 ou 5 chambres
        "pf":        "1",
        "page":      str(page),
    })
    url = f"https://www.propertyfinder.ae/en/search/results.json?{params}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fetch_propertyfinder_html(slug: str, beds: int, page: int = 1) -> str:
    """Fallback : récupère la page HTML de recherche PropertyFinder."""
    url = (f"https://www.propertyfinder.ae/en/rent/villas-for-rent/"
           f"{slug}-neighbourhood.html"
           f"?beds={beds}&page={page}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_from_html(html: str, zone_label: str) -> list:
    """
    Extrait les annonces depuis le JSON embarqué dans la page HTML.
    PropertyFinder injecte les données dans window.__INITIAL_STATE__ ou
    des balises <script type="application/json">.
    """
    listings = []

    # Chercher le JSON embarqué dans __INITIAL_STATE__
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>',
        r'<script[^>]*type=["\']application/json["\'][^>]*>({.+?})</script>',
        r'"listings"\s*:\s*(\[.+?\])',
        r'"properties"\s*:\s*(\[.+?\])',
        r'"hits"\s*:\s*(\[.+?\])',
    ]

    raw_data = None
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                raw_data = json.loads(match.group(1))
                break
            except Exception:
                continue

    if not raw_data:
        return []

    # Naviguer dans la structure pour trouver les annonces
    def find_listings(obj, depth=0):
        if depth > 5:
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if any(k in obj[0] for k in ("price", "rent", "bedroom", "area")):
                return obj
        if isinstance(obj, dict):
            for key in ("listings", "properties", "hits", "results", "data", "items"):
                if key in obj:
                    result = find_listings(obj[key], depth+1)
                    if result:
                        return result
            for v in obj.values():
                result = find_listings(v, depth+1)
                if result:
                    return result
        return []

    items = find_listings(raw_data)
    for item in items:
        listing = parse_item(item, zone_label)
        if listing:
            listings.append(listing)

    return listings


def parse_item(item: dict, zone_label: str) -> Optional[RentalListing]:
    """Parse un item brut PropertyFinder → RentalListing."""
    try:
        # Prix — PropertyFinder loyers = annuel en AED
        price = (item.get("price") or item.get("rent") or
                 item.get("rentPrice") or item.get("annual_rent") or 0)
        if isinstance(price, dict):
            price = price.get("value") or price.get("amount") or 0
        if isinstance(price, str):
            price = int("".join(c for c in price if c.isdigit()) or "0")
        annual = int(price)

        # Normaliser si mensuel
        if 5_000 <= annual <= 50_000:
            annual *= 12

        if not (80_000 <= annual <= 1_500_000):
            return None

        # Chambres
        beds = int(item.get("bedroom") or item.get("bedrooms") or
                   item.get("rooms") or item.get("beds") or 0)
        if beds not in (3, 4, 5):
            return None

        # Surface
        area = (item.get("area") or item.get("size") or
                item.get("sqft") or item.get("square_footage"))
        if isinstance(area, dict):
            area = area.get("value") or area.get("sqft")
        sqft = int(float(area)) if area else None

        # URL
        slug = (item.get("slug") or item.get("url") or
                item.get("reference") or item.get("id") or "")
        url = (f"https://www.propertyfinder.ae/en/rent/{slug}.html"
               if not str(slug).startswith("http") else str(slug))

        # Titre
        title = (item.get("title") or item.get("name") or
                 item.get("description") or f"Villa {beds}BR {zone_label}")
        if isinstance(title, dict):
            title = title.get("en") or next(iter(title.values()), "")

        # District
        location = (item.get("location") or item.get("area") or
                    item.get("neighbourhood") or zone_label)
        if isinstance(location, dict):
            location = location.get("name") or location.get("title") or zone_label

        # Meublé
        furn = str(item.get("furnishing") or item.get("furnished") or "").lower()
        furnished = (True  if "furnished" in furn and "un" not in furn else
                     False if "unfurnish" in furn else None)

        # Chèques
        cheques_raw = item.get("cheques") or item.get("payment_frequency")
        cheques = int(cheques_raw) if cheques_raw and str(cheques_raw).isdigit() else None

        return RentalListing(
            source="PropertyFinder",
            title=str(title)[:140],
            zone=zone_label,
            district_raw=str(location)[:100],
            rent_annual_aed=annual,
            rent_monthly_aed=annual // 12,
            sqft=sqft,
            rent_per_sqft_annual=round(annual / sqft, 1) if sqft else None,
            bedrooms=beds,
            bathrooms=item.get("bathroom") or item.get("bathrooms"),
            cheques=cheques,
            furnished=furnished,
            url=str(url),
            scraped_at=datetime.now().isoformat(),
            listing_age_days=None,
        )
    except Exception:
        return None


async def scrape_zone(zone: dict) -> list:
    """Scrape une zone sur PropertyFinder."""
    label = zone["label"]
    slug  = zone["slug"]
    listings = []

    for beds in (3, 4, 5):
        try:
            html = fetch_propertyfinder_html(slug, beds)
            found = extract_from_html(html, label)
            listings.extend(found)
            print(f"     {beds}BR: {len(found)} annonces")
            time.sleep(1.5)
        except Exception as e:
            print(f"     {beds}BR: erreur ({e})")
            time.sleep(2)

    return listings


async def run_villa_scraping():
    print("\n🏡 Scraping LOYERS villas 3-5BR — PropertyFinder.ae")
    print("   Aucune clé API requise")
    init_db()

    all_listings = []

    for zone in ZONES:
        print(f"\n  📍 {zone['label']}")
        try:
            found = await scrape_zone(zone)
            all_listings.extend(found)
            print(f"     ✅ {len(found)} annonces valides")
        except Exception as e:
            print(f"     ❌ Erreur zone: {e}")
        time.sleep(2)

    n_saved = save_listings(all_listings)
    save_weekly_snapshot()

    # Résumé
    by_zone: dict[str, list] = {}
    for l in all_listings:
        by_zone.setdefault(l.zone, []).append(l)

    if by_zone:
        print(f"\n  📊 Loyers annuels par zone:")
        for z, lst in sorted(by_zone.items()):
            rents = [l.rent_annual_aed for l in lst]
            print(f"     {z:<18} {len(lst):>3} annonces  "
                  f"moy AED {sum(rents)//len(rents):>9,}/an")
    else:
        print("\n  ⚠️  0 annonces collectées depuis PropertyFinder")
        print("     → Le pipeline continue avec les données existantes en DB")

    print(f"\n  💾 {n_saved}/{len(all_listings)} nouvelles annonces sauvegardées")
    return all_listings


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_villa_scraping())

"""
dubai_agent/scraper_villas.py
Collecte les loyers via "Unofficial Bayut API" (API Universe) sur RapidAPI
"""

import sqlite3, os, json, time
import urllib.request, urllib.parse
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

DB_PATH      = "dubai_realestate.db"
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
API_HOST     = "unofficial-bayut-api.p.rapidapi.com"
BASE_URL     = f"https://{API_HOST}"

# ── IDs Bayut connus pour les zones cibles ────────────────────────────────────
# Format: (label affiché, liste d'IDs Bayut possibles)
# On essaie chaque ID jusqu'à obtenir des résultats
ZONES = [
    {"label": "Jumeirah 1",   "query": "Jumeirah 1 Dubai"},
    {"label": "Jumeirah 2",   "query": "Jumeirah 2 Dubai"},
    {"label": "Jumeirah 3",   "query": "Jumeirah 3 Dubai"},
    {"label": "Umm Suqeim 1", "query": "Umm Suqeim 1 Dubai"},
    {"label": "Umm Suqeim 2", "query": "Umm Suqeim 2 Dubai"},
    {"label": "Al Safa 1",    "query": "Al Safa 1 Dubai"},
    {"label": "Al Safa 2",    "query": "Al Safa 2 Dubai"},
    {"label": "Al Manara",    "query": "Al Manara Dubai"},
    {"label": "Al Wasl",      "query": "Al Wasl Dubai"},
]


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zone_ids_cache (
            zone_label TEXT PRIMARY KEY,
            external_id TEXT,
            updated_at TEXT
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


def api_get(endpoint: str, params: dict) -> dict:
    qs  = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": API_HOST,
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def extract_all_ids(obj, depth=0):
    """Extrait récursivement tous les champs qui ressemblent à un ID numérique."""
    ids = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in ("externalid", "id", "locationid", "areaid") and v:
                ids.append((k, str(v)))
            ids.extend(extract_all_ids(v, depth+1))
    elif isinstance(obj, list):
        for item in obj:
            ids.extend(extract_all_ids(item, depth+1))
    return ids


def get_location_id(zone_label: str, query: str) -> Optional[str]:
    """Appelle /autocomplete et affiche la réponse brute pour debug."""
    # Vérifier cache DB
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute(
        "SELECT external_id FROM zone_ids_cache WHERE zone_label=?",
        (zone_label,)
    ).fetchone()
    conn.close()
    if row:
        return row[0]

    try:
        data = api_get("autocomplete", {"query": query, "lang": "en"})

        # ── Debug : afficher les 2 premiers résultats bruts ──────────────
        top = (data.get("hits") or data.get("results") or
               data.get("data") or data.get("suggestions") or [])
        print(f"     🔍 Autocomplete '{query}' → {len(top)} résultats")
        if top:
            first = top[0]
            print(f"     🔑 Clés disponibles: {list(first.keys())[:10]}")
            # Extraire tous les IDs possibles
            all_ids = extract_all_ids(first)
            print(f"     🆔 IDs trouvés: {all_ids[:5]}")

        # ── Chercher le bon ID ────────────────────────────────────────────
        best_id = None
        for hit in top:
            # Essayer différents noms de champs
            ext_id = (hit.get("externalID") or hit.get("id") or
                      hit.get("locationId") or hit.get("areaId") or
                      hit.get("externalId") or "")
            name   = str(hit.get("name") or hit.get("title") or
                         hit.get("label") or "").lower()
            h_type = str(hit.get("type") or hit.get("category") or "").lower()

            if ext_id:
                # Priorité aux matches exacts par nom
                short_name = zone_label.split()[0].lower()  # ex: "jumeirah"
                if short_name in name:
                    best_id = str(ext_id)
                    print(f"     ✅ Match: '{name}' (type:{h_type}) → ID {best_id}")
                    if any(t in h_type for t in ("area", "community", "sub")):
                        break
                elif not best_id:
                    best_id = str(ext_id)

        if best_id:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                INSERT OR REPLACE INTO zone_ids_cache (zone_label, external_id, updated_at)
                VALUES (?,?,?)
            """, (zone_label, best_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return best_id

        # ── Fallback : afficher réponse complète pour diagnostic ──────────
        print(f"     ⚠️  Aucun ID trouvé. Réponse brute (premiers 300 chars):")
        print(f"     {json.dumps(data)[:300]}")
        return None

    except Exception as e:
        print(f"     ❌ Autocomplete erreur: {e}")
        return None


def fetch_rentals(location_id: str, beds: int) -> list:
    try:
        data = api_get("search", {
            "locationExternalIDs": location_id,
            "purpose":   "for-rent",
            "categories": "residential",
            "rooms":      str(beds),
            "rentFreq":   "yearly",
            "page":       "0",
        })
        return (data.get("hits") or data.get("results") or
                data.get("properties") or data.get("data") or [])
    except Exception as e:
        print(f"       ❌ Search API: {e}")
        return []


def parse_hit(hit: dict, zone_label: str) -> Optional[RentalListing]:
    try:
        price = (hit.get("price") or hit.get("rentPrice") or 0)
        if isinstance(price, str):
            price = int("".join(c for c in price if c.isdigit()) or "0")
        annual = int(price)
        if not (80_000 <= annual <= 1_500_000):
            return None

        beds = int(hit.get("rooms") or hit.get("beds") or 0)
        if beds not in (3, 4, 5):
            return None

        area = hit.get("area") or hit.get("size")
        sqft = int(float(area)) if area else None
        ext_id = str(hit.get("externalID") or hit.get("id") or "")
        url  = hit.get("url") or f"https://www.bayut.com/property/details-{ext_id}.html"

        title_raw = hit.get("title") or {}
        title = (title_raw.get("en") or next(iter(title_raw.values()), "Villa")
                 if isinstance(title_raw, dict) else str(title_raw))

        loc = hit.get("location") or []
        district_raw = (loc[-1].get("name", zone_label)
                        if isinstance(loc, list) and loc else zone_label)

        furn = str(hit.get("furnishingStatus") or "").lower()
        furnished = (True  if "furnished" in furn and "un" not in furn else
                     False if "unfurnish" in furn else None)

        return RentalListing(
            source="Unofficial Bayut API",
            title=str(title)[:140],
            zone=zone_label,
            district_raw=str(district_raw)[:100],
            rent_annual_aed=annual,
            rent_monthly_aed=annual // 12,
            sqft=sqft,
            rent_per_sqft_annual=round(annual / sqft, 1) if sqft else None,
            bedrooms=beds,
            bathrooms=hit.get("baths") or hit.get("bathrooms"),
            cheques=None,
            furnished=furnished,
            url=str(url),
            scraped_at=datetime.now().isoformat(),
            listing_age_days=None,
        )
    except Exception:
        return None


async def run_villa_scraping():
    print("\n🏡 Scraping LOYERS villas 3-5BR — Unofficial Bayut API")
    init_db()

    if not RAPIDAPI_KEY:
        print("  ❌ RAPIDAPI_KEY manquant")
        return []

    all_listings = []

    for zone in ZONES:
        label = zone["label"]
        query = zone["query"]
        print(f"\n  📍 {label}")

        loc_id = get_location_id(label, query)
        if not loc_id:
            continue

        time.sleep(0.3)

        for beds in (3, 4, 5):
            try:
                hits  = fetch_rentals(loc_id, beds)
                count = 0
                for hit in hits:
                    listing = parse_hit(hit, label)
                    if listing:
                        all_listings.append(listing)
                        count += 1
                print(f"     {beds}BR: {count}/{len(hits)} annonces")
                time.sleep(0.4)
            except Exception as e:
                print(f"     {beds}BR: erreur ({e})")

    n_saved = save_listings(all_listings)
    save_weekly_snapshot()

    by_zone: dict[str, list] = {}
    for l in all_listings:
        by_zone.setdefault(l.zone, []).append(l)

    if by_zone:
        print(f"\n  📊 Résumé par zone:")
        for z, lst in sorted(by_zone.items()):
            rents = [l.rent_annual_aed for l in lst]
            print(f"     {z:<18} {len(lst):>3} annonces  "
                  f"moy AED {sum(rents)//len(rents):>9,}/an")

    print(f"\n  💾 {n_saved}/{len(all_listings)} nouvelles annonces")
    return all_listings


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_villa_scraping())

"""
dubai_agent/scraper_villas.py
Collecte les loyers via "Unofficial Bayut API" (API Universe) sur RapidAPI
Endpoint: https://unofficial-bayut-api.p.rapidapi.com/search
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

# ── Zones cibles avec leurs IDs Bayut ────────────────────────────────────────
# Ces IDs sont obtenus via l'endpoint /autocomplete
# On les récupère dynamiquement au premier lancement, puis on les met en cache
ZONE_NAMES = [
    "Jumeirah 1",
    "Jumeirah 2",
    "Jumeirah 3",
    "Umm Suqeim 1",
    "Umm Suqeim 2",
    "Al Safa 1",
    "Al Safa 2",
    "Al Manara",
    "Al Wasl",
]


@dataclass
class RentalListing:
    source:               str
    title:                str
    zone:                 str
    district_raw:         str
    rent_annual_aed:      int
    rent_monthly_aed:     int
    sqft:                 Optional[int]
    rent_per_sqft_annual: Optional[float]
    bedrooms:             int
    bathrooms:            Optional[int]
    cheques:              Optional[int]
    furnished:            Optional[bool]
    url:                  str
    scraped_at:           str
    listing_age_days:     Optional[int]


# ── Database ──────────────────────────────────────────────────────────────────
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
    # Cache des IDs de zones
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zone_ids (
            zone_name TEXT PRIMARY KEY,
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
    print(f"  [DB] Snapshot {week}: {len(rows)} combinaisons zone×chambres")


# ── API helpers ───────────────────────────────────────────────────────────────
def api_get(endpoint: str, params: dict) -> dict:
    qs  = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{endpoint}?{qs}"
    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": API_HOST,
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def get_location_id(zone_name: str) -> Optional[str]:
    """Appelle /autocomplete pour obtenir l'ID numérique d'une zone."""
    # Vérifier le cache DB d'abord
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT external_id FROM zone_ids WHERE zone_name=?", (zone_name,)
    ).fetchone()
    conn.close()
    if row:
        return row[0]

    # Appel API autocomplete
    try:
        data = api_get("autocomplete", {"query": zone_name, "lang": "en"})
        # Chercher dans la réponse — structure typique : hits ou results
        hits = (data.get("hits") or data.get("results") or
                data.get("locationHierarchy") or [])

        # Chercher le meilleur match (type "area" ou "community")
        best_id = None
        for hit in hits:
            hit_type = str(hit.get("type", "")).lower()
            hit_name = str(hit.get("name", "") or
                           hit.get("externalID", "")).lower()
            ext_id   = str(hit.get("externalID") or hit.get("id") or "")

            if ext_id and zone_name.lower() in hit_name:
                best_id = ext_id
                if hit_type in ("area", "community", "subCommunity"):
                    break   # match parfait

        if best_id:
            # Sauvegarder en cache
            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                INSERT OR REPLACE INTO zone_ids (zone_name, external_id, updated_at)
                VALUES (?,?,?)
            """, (zone_name, best_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            print(f"     📍 {zone_name} → ID {best_id}")
            return best_id
        else:
            print(f"     ⚠️  ID introuvable pour {zone_name}")
            return None
    except Exception as e:
        print(f"     ⚠️  Autocomplete échoué pour {zone_name}: {e}")
        return None


def fetch_rentals(location_id: str, rooms: str, page: int = 0) -> list:
    """Appelle /search avec les bons paramètres."""
    try:
        data = api_get("search", {
            "locationExternalIDs": location_id,
            "purpose":   "for-rent",
            "categories": "residential",   # villas incluses
            "rooms":      rooms,           # ex: "3" ou "3,4,5"
            "rentFreq":   "yearly",        # loyer annuel directement
            "page":       str(page),
        })
        return (data.get("hits") or data.get("results") or
                data.get("properties") or data.get("data") or [])
    except Exception as e:
        print(f"       API error: {e}")
        return []


def parse_hit(hit: dict, zone_label: str) -> Optional[RentalListing]:
    """Parse un résultat API → RentalListing."""
    try:
        # Prix annuel (rentFreq=yearly → directement annuel)
        price = (hit.get("price") or hit.get("rentPrice") or
                 hit.get("annualRent") or 0)
        if isinstance(price, str):
            price = int("".join(c for c in price if c.isdigit()) or "0")
        annual = int(price)

        # Sanity check loyer annuel villa Dubai
        if not (80_000 <= annual <= 1_500_000):
            return None

        # Chambres
        beds = int(hit.get("rooms") or hit.get("beds") or
                   hit.get("bedrooms") or 0)
        if beds not in (3, 4, 5):
            return None

        # Surface sqft
        area = hit.get("area") or hit.get("size")
        sqft = int(float(area)) if area else None

        # URL
        ext_id = str(hit.get("externalID") or hit.get("id") or "")
        url    = (hit.get("url") or hit.get("link") or
                  f"https://www.bayut.com/property/details-{ext_id}.html")

        # Titre
        title_raw = hit.get("title") or hit.get("name") or {}
        if isinstance(title_raw, dict):
            title = title_raw.get("en") or next(iter(title_raw.values()), "Villa")
        else:
            title = str(title_raw) or "Villa"

        # Localisation brute
        loc = hit.get("location") or hit.get("locationHierarchy") or []
        district_raw = (loc[-1].get("name", zone_label)
                        if isinstance(loc, list) and loc else zone_label)

        # Meublé
        furn = str(hit.get("furnishingStatus") or hit.get("furnished") or "").lower()
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


# ── Pipeline principal ────────────────────────────────────────────────────────
async def run_villa_scraping():
    print("\n🏡 Scraping LOYERS villas 3-5BR — Unofficial Bayut API")
    init_db()

    if not RAPIDAPI_KEY:
        print("  ❌ RAPIDAPI_KEY manquant — ajoutez ce secret dans GitHub")
        return []

    all_listings = []

    for zone_name in ZONE_NAMES:
        print(f"\n  📍 {zone_name}")

        # Étape 1 : obtenir l'ID de la zone
        loc_id = get_location_id(zone_name)
        if not loc_id:
            print(f"     ⏭️  Zone ignorée (ID introuvable)")
            continue

        time.sleep(0.3)

        # Étape 2 : scraper 3BR, 4BR, 5BR séparément
        for beds in (3, 4, 5):
            try:
                hits  = fetch_rentals(loc_id, str(beds))
                count = 0
                for hit in hits:
                    listing = parse_hit(hit, zone_name)
                    if listing:
                        all_listings.append(listing)
                        count += 1
                print(f"     {beds}BR : {count}/{len(hits)} annonces valides")
                time.sleep(0.4)   # respecter le rate limit
            except Exception as e:
                print(f"     {beds}BR : erreur ({e})")

    # Sauvegarde
    n_saved = save_listings(all_listings)
    save_weekly_snapshot()

    # Résumé
    by_zone: dict[str, list] = {}
    for l in all_listings:
        by_zone.setdefault(l.zone, []).append(l)

    if by_zone:
        print(f"\n  📊 Loyers annuels par zone :")
        for zone, lst in sorted(by_zone.items()):
            rents = [l.rent_annual_aed for l in lst]
            avg   = sum(rents) // len(rents)
            print(f"     {zone:<18} {len(lst):>3} annonces  "
                  f"moy AED {avg:>9,}/an  ({avg//12:,}/mois)")
    else:
        print("\n  ⚠️  Aucune annonce collectée")

    print(f"\n  💾 {n_saved}/{len(all_listings)} nouvelles annonces sauvegardées")
    return all_listings


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_villa_scraping())

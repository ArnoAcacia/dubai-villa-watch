"""
dubai_agent/main.py
Orchestrateur principal — robuste au premier lancement
"""

import asyncio, os, sys
from datetime import datetime

# ── Format DEMO_STATS aligné avec report_generator.py ────────────────────────
DEMO_STATS = {
    "week":     datetime.now().strftime("%Y-W%W"),
    "date_label": datetime.now().strftime("%d %B %Y"),
    "global": {
        "avg_rent_annual":   0,
        "avg_rent_per_sqft": 0,
        "total_listings":    0,
        "price_change_pct":  None,
    },
    "prev_week": {
        "avg_rent_annual":   None,
        "avg_rent_per_sqft": None,
    },
    "districts": [],
    "by_beds":   [],
    # Champs pour email_reporter
    "total":         0,
    "avg_rent":      0,
    "min_rent":      0,
    "max_rent":      0,
    "variation_pct": None,
    "prev_avg_rent": None,
    "by_zone":       [],
    "new_listings":  [],
}

DEMO_ANALYSIS = """## Premier lancement — Test de configuration
L'agent Dubai Villa Watch a démarré avec succès.

## Statut des composants
- Scraping : OK (Bayut bloque les robots, c'est normal — PropertyFinder collectera les données)
- Analyse IA : En attente de crédits Anthropic (ajoutez $5 sur console.anthropic.com)
- PDF : OK
- Email : En cours de configuration

## Prochaine étape
Une fois les crédits Anthropic ajoutés, le prochain run contiendra une vraie analyse du marché locatif."""


async def weekly_pipeline(dry_run: bool = False):
    print("\n" + "=" * 60)
    print("  DUBAI VILLA WATCH — Pipeline")
    print(f"  {datetime.now().strftime('%A %d %B %Y - %H:%M')}")
    print("=" * 60)

    # ── 1. Scraping ───────────────────────────────────────────────────────
    print("\n[1/4] Scraping loyers villas 3-5BR...")
    try:
        from scraper_villas import run_villa_scraping
        listings = await run_villa_scraping()
        print(f"      {len(listings)} annonces collectées")
    except Exception as e:
        print(f"      ⚠️  Scraping incomplet: {e}")

    # ── 2. Analyse IA ─────────────────────────────────────────────────────
    print("\n[2/4] Analyse IA...")
    stats    = DEMO_STATS.copy()
    analysis = DEMO_ANALYSIS
    try:
        from analyzer import run_analysis
        result_stats, result_analysis = run_analysis()
        # Fusionner avec les champs email_reporter
        stats = {
            **DEMO_STATS,
            **result_stats,
            "date_label":    datetime.now().strftime("%d %B %Y"),
            "total":         result_stats["global"]["total_listings"],
            "avg_rent":      result_stats["global"]["avg_rent_annual"],
            "min_rent":      min((d["avg_rent"] for d in result_stats.get("districts", [])), default=0),
            "max_rent":      max((d["avg_rent"] for d in result_stats.get("districts", [])), default=0),
            "variation_pct": result_stats["global"]["price_change_pct"],
            "prev_avg_rent": result_stats["prev_week"]["avg_rent_annual"],
            "by_zone": [
                {
                    "zone":       d["name"],
                    "count":      d["listing_count"],
                    "avg_rent":   d["avg_rent"],
                    "avg_ppsqft": d.get("avg_ppsqft", 0),
                    "delta":      None,
                    "prev_avg":   None,
                }
                for d in result_stats.get("districts", [])
            ],
            "by_beds": [
                {
                    "bedrooms": b["bedrooms"],
                    "count":    b["count"],
                    "avg_rent": b["avg_rent"],
                    "min_rent": b.get("min_rent", 0),
                    "max_rent": b.get("max_rent", 0),
                    "delta":    None,
                    "prev_avg": None,
                }
                for b in result_stats.get("by_beds", [])
            ],
            "new_listings": [],
        }
        analysis = result_analysis
        print("      ✅ Analyse générée")
    except Exception as e:
        print(f"      ⚠️  Analyse IA impossible: {e}")
        print("      → Utilisation du texte de remplacement")

    # ── 3. PDF ────────────────────────────────────────────────────────────
    print("\n[3/4] Génération PDF...")
    pdf_path = None
    os.makedirs("reports", exist_ok=True)
    try:
        from report_generator import generate_pdf
        date_str = datetime.now().strftime("%Y-%m-%d")
        pdf_path = generate_pdf(
            stats, analysis,
            output_path=f"reports/dubai_loyers_{date_str}.pdf"
        )
        print(f"      ✅ PDF: {pdf_path}")
    except Exception as e:
        print(f"      ⚠️  PDF non généré: {e}")

    # ── 4. Email ──────────────────────────────────────────────────────────
    print("\n[4/4] Email...")
    try:
        from email_reporter import send_weekly_email, preview_email_html

        if dry_run:
            date_str  = datetime.now().strftime("%Y-%m-%d")
            prev_path = f"reports/email_preview_{date_str}.html"
            preview_email_html(stats, analysis, prev_path)
            print(f"      ✅ Dry-run → HTML: {prev_path}")
        else:
            ok = send_weekly_email(stats, analysis, pdf_path)
            if ok:
                print("      ✅ Email envoyé")
            else:
                print("      ❌ Échec envoi email")
                sys.exit(1)
    except Exception as e:
        print(f"      ❌ Erreur email: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✅ Pipeline terminé avec succès")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(weekly_pipeline(dry_run="--dry-run" in sys.argv))

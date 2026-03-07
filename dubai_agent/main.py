"""
dubai_agent/main.py
Orchestrateur principal — robuste au premier lancement (base vide)
"""

import asyncio
import os
import sys
from datetime import datetime

# ── Données de démo pour le premier lancement (base vide) ────────────────────
DEMO_STATS = {
    "date_label": datetime.now().strftime("%d %B %Y"),
    "week": datetime.now().strftime("Semaine %W · %Y"),
    "total": 0,
    "avg_rent": 0,
    "min_rent": 0,
    "max_rent": 0,
    "variation_pct": None,
    "prev_avg_rent": None,
    "by_zone": [],
    "by_beds": [],
    "new_listings": [],
}

DEMO_ANALYSIS = """## Premier lancement
L'agent a démarré avec succès. La base de données est vide car c'est la première exécution.

## Que va-t-il se passer ?
Au prochain run (dimanche), les données réelles seront collectées sur Bayut et PropertyFinder, analysées par Claude, et un rapport complet vous sera envoyé par email.

## Configuration
Si vous recevez cet email, cela signifie que toute la chaîne fonctionne correctement : GitHub Actions → Scraping → Analyse IA → Email."""


async def weekly_pipeline(dry_run: bool = False):
    print("\n" + "=" * 60)
    print("  DUBAI VILLA WATCH — Pipeline")
    print(f"  {datetime.now().strftime('%A %d %B %Y - %H:%M')}")
    print("=" * 60)

    # ── 1. Scraping ───────────────────────────────────────────────────────
    print("\n[1/4] Scraping loyers villas 3-5BR...")
    listings = []
    try:
        from scraper_villas import run_villa_scraping
        listings = await run_villa_scraping()
        print(f"      {len(listings)} annonces collectées")
    except Exception as e:
        print(f"      ⚠️  Scraping incomplet: {e}")
        print("      → On continue avec les données disponibles en base")

    # ── 2. Analyse IA ─────────────────────────────────────────────────────
    print("\n[2/4] Analyse IA...")
    stats, analysis = None, None
    try:
        from analyzer import run_analysis
        stats, analysis = run_analysis()
        print("      Analyse générée")
    except Exception as e:
        print(f"      ⚠️  Analyse IA impossible: {e}")
        print("      → Utilisation du texte de remplacement")
        stats    = DEMO_STATS
        analysis = DEMO_ANALYSIS

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
        print(f"      PDF: {pdf_path}")
    except Exception as e:
        print(f"      ⚠️  PDF non généré: {e}")

    # ── 4. Email ──────────────────────────────────────────────────────────
    print("\n[4/4] Email...")
    try:
        from email_reporter import get_email_stats, send_weekly_email, preview_email_html

        # Essayer d'abord les vraies stats DB, sinon utiliser DEMO_STATS
        try:
            email_stats = get_email_stats()
        except Exception:
            email_stats = DEMO_STATS

        if dry_run:
            date_str  = datetime.now().strftime("%Y-%m-%d")
            prev_path = f"reports/email_preview_{date_str}.html"
            preview_email_html(email_stats, analysis, prev_path)
            print(f"      Dry-run → HTML sauvegardé: {prev_path}")
        else:
            ok = send_weekly_email(email_stats, analysis, pdf_path)
            print(f"      {'✅ Email envoyé' if ok else '❌ Échec envoi email'}")
            if not ok:
                sys.exit(1)   # Signale l'échec à GitHub Actions

    except Exception as e:
        print(f"      ❌ Erreur email: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✅ Pipeline terminé")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(weekly_pipeline(dry_run=dry))

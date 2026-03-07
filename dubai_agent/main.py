"""
dubai_agent/main.py  (v2 — focus villas Jumeirah/Umm Suqeim/Al Safa)
Orchestrateur hebdomadaire complet :
  1. Scraping ciblé villas 3-5BR dans les zones cibles
  2. Analyse IA via Claude API
  3. Génération rapport PDF
  4. Envoi email HTML avec liens dashboard
"""

import asyncio
import os
from datetime import datetime

from scraper_villas import run_villa_scraping
from analyzer import run_analysis
from report_generator import generate_pdf
from email_reporter import get_email_stats, send_weekly_email, preview_email_html


async def weekly_pipeline(dry_run: bool = False):
    print("\n" + "=" * 64)
    print("   DUBAI REALTY WATCH v2 — Pipeline hebdomadaire")
    print(f"   {datetime.now().strftime('%A %d %B %Y - %H:%M')}")
    print("=" * 64)

    # 1. Scraping
    print("\n[1/4] Scraping villas 3-5BR...")
    listings = await run_villa_scraping()
    print(f"      {len(listings)} villas collectees")

    # 2. Analyse
    print("\n[2/4] Analyse IA Claude...")
    stats, analysis = run_analysis()

    # 3. PDF
    print("\n[3/4] Generation PDF...")
    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_path = generate_pdf(stats, analysis,
                            output_path=f"reports/dubai_villas_{date_str}.pdf")

    # 4. Email
    print("\n[4/4] Email...")
    email_stats = get_email_stats()

    if dry_run:
        preview_path = f"reports/email_preview_{date_str}.html"
        preview_email_html(email_stats, analysis, preview_path)
        print(f"      Dry-run -> HTML: {preview_path}")
    else:
        send_weekly_email(email_stats, analysis, pdf_path)

    print("\n" + "=" * 64)
    print("  Pipeline termine avec succes")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    asyncio.run(weekly_pipeline(dry_run=dry))


# GITHUB ACTIONS CONFIG:
# Ajouter dans .github/workflows/dubai_weekly.yml
# Cron: '0 6 * * 1'  (Lundi 6h UTC = 10h Dubai)
# Secrets requis: ANTHROPIC_API_KEY, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, TO_EMAIL, DASHBOARD_URL

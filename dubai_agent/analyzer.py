"""
dubai_agent/analyzer.py
Analyse des données locatives via Claude API
Utilise la table rental_listings (et non l'ancienne table listings)
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "dubai_realestate.db"


def get_weekly_stats() -> dict:
    """Récupère les stats de la semaine depuis rental_listings."""
    conn = sqlite3.connect(DB_PATH)

    # Vérifie que la table existe
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    if "rental_listings" not in tables:
        conn.close()
        raise RuntimeError("no data yet — table rental_listings is empty or missing")

    # Stats globales semaine courante
    cur = conn.execute("""
        SELECT AVG(rent_annual_aed), AVG(rent_per_sqft_annual), COUNT(*)
        FROM rental_listings
        WHERE scraped_at >= date('now','-7 days')
    """).fetchone()

    # Stats globales semaine précédente
    prev = conn.execute("""
        SELECT AVG(rent_annual_aed), AVG(rent_per_sqft_annual)
        FROM rental_listings
        WHERE scraped_at >= date('now','-14 days')
          AND scraped_at <  date('now','-7 days')
    """).fetchone()

    # Par zone
    zone_rows = conn.execute("""
        SELECT zone,
               AVG(rent_annual_aed),
               AVG(rent_per_sqft_annual),
               COUNT(*)
        FROM rental_listings
        WHERE scraped_at >= date('now','-7 days')
        GROUP BY zone
        ORDER BY AVG(rent_annual_aed) DESC
    """).fetchall()

    # Par nb de chambres
    beds_rows = conn.execute("""
        SELECT bedrooms,
               AVG(rent_annual_aed),
               MIN(rent_annual_aed),
               MAX(rent_annual_aed),
               COUNT(*)
        FROM rental_listings
        WHERE scraped_at >= date('now','-7 days')
        GROUP BY bedrooms
        ORDER BY bedrooms
    """).fetchall()

    conn.close()

    cur_avg  = cur[1] or 0
    prev_avg = prev[0] if prev[0] else None
    pct_chg  = round((cur_avg - prev_avg) / prev_avg * 100, 2) if prev_avg else None

    return {
        "week": datetime.now().strftime("%Y-W%W"),
        "global": {
            "avg_rent_annual":     round(cur[0] or 0),
            "avg_rent_per_sqft":   round(cur[1] or 0, 1),
            "total_listings":      cur[2],
            "price_change_pct":    pct_chg,
        },
        "prev_week": {
            "avg_rent_annual":     round(prev[0]) if prev[0] else None,
            "avg_rent_per_sqft":   round(prev[1], 1) if prev[1] else None,
        },
        "districts": [
            {
                "name":        r[0],
                "avg_rent":    round(r[1]),
                "avg_ppsqft":  round(r[2] or 0, 1),
                "listing_count": r[3],
            }
            for r in zone_rows
        ],
        "by_beds": [
            {
                "bedrooms": r[0],
                "avg_rent": round(r[1]),
                "min_rent": r[2],
                "max_rent": r[3],
                "count":    r[4],
            }
            for r in beds_rows
        ],
    }


def analyze_with_claude(stats: dict) -> str:
    """Envoie les stats à Claude et retourne l'analyse textuelle."""
    import anthropic
    client = anthropic.Anthropic()   # lit ANTHROPIC_API_KEY depuis l'env

    prompt = f"""Tu es un analyste immobilier expert sur le marché locatif de Dubaï.

Voici les données collectées cette semaine sur les LOYERS de villas 3-5BR
dans les zones Jumeirah 1/2/3, Umm Suqeim 1/2, Al Safa 1/2, Al Manara, Al Wasl :

{json.dumps(stats, indent=2, ensure_ascii=False)}

Rédige une analyse hebdomadaire professionnelle en français comprenant :
1. **Résumé exécutif** (2-3 phrases, chiffres clés de loyers annuels et mensuels)
2. **Tendances par zone** (quels quartiers voient les loyers monter/baisser et pourquoi)
3. **Signaux d'alerte** (anomalies, risques pour le marché locatif)
4. **Opportunités locatives** identifiées cette semaine
5. **Prévision** pour la semaine prochaine

Format : markdown avec émojis. Ton professionnel. Longueur : 350-450 mots.
Exprimer les loyers toujours en AED/an ET en AED/mois."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def run_analysis() -> tuple[dict, str]:
    print("\n🤖 Analyse IA démarrée...")
    stats    = get_weekly_stats()
    print(f"  Stats : {stats['global']['total_listings']} annonces cette semaine")
    analysis = analyze_with_claude(stats)
    print("  ✅ Analyse Claude générée")
    return stats, analysis


if __name__ == "__main__":
    stats, analysis = run_analysis()
    print("\n" + "=" * 60)
    print(analysis)

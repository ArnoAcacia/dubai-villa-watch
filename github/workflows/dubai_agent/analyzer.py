"""
dubai_agent/analyzer.py
Analyse des données immobilières via Claude API
"""

import sqlite3
import json
import anthropic
from datetime import datetime

DB_PATH = "dubai_realestate.db"
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY env var requis

def get_weekly_stats() -> dict:
    """Récupère les stats de la semaine en cours depuis la BDD."""
    conn = sqlite3.connect(DB_PATH)

    # Stats globales
    global_row = conn.execute("""
        SELECT AVG(price_aed), AVG(price_per_sqft), COUNT(*)
        FROM listings
        WHERE scraped_at >= date('now','-7 days')
    """).fetchone()

    # Stats par district
    district_rows = conn.execute("""
        SELECT district,
               AVG(price_aed) as avg_price,
               AVG(price_per_sqft) as avg_ppsqft,
               COUNT(*) as cnt
        FROM listings
        WHERE scraped_at >= date('now','-7 days')
        GROUP BY district
        ORDER BY avg_ppsqft DESC
    """).fetchall()

    # Comparaison semaine précédente
    prev_global = conn.execute("""
        SELECT AVG(price_aed), AVG(price_per_sqft)
        FROM listings
        WHERE scraped_at >= date('now','-14 days')
          AND scraped_at < date('now','-7 days')
    """).fetchone()

    conn.close()

    stats = {
        "week": datetime.now().strftime("%Y-W%W"),
        "global": {
            "avg_price_aed": round(global_row[0] or 0),
            "avg_price_per_sqft": round(global_row[1] or 0, 1),
            "total_listings": global_row[2],
        },
        "prev_week": {
            "avg_price_aed": round(prev_global[0] or 0) if prev_global[0] else None,
            "avg_price_per_sqft": round(prev_global[1] or 0, 1) if prev_global[1] else None,
        },
        "districts": [
            {
                "name": r[0],
                "avg_price_aed": round(r[1]),
                "avg_ppsqft": round(r[2], 1),
                "listings": r[3],
            }
            for r in district_rows
        ],
    }

    # Calcul de variation
    if stats["prev_week"]["avg_price_aed"]:
        pct = ((stats["global"]["avg_price_aed"] - stats["prev_week"]["avg_price_aed"])
               / stats["prev_week"]["avg_price_aed"] * 100)
        stats["global"]["price_change_pct"] = round(pct, 2)

    return stats


def analyze_with_claude(stats: dict) -> str:
    """
    Envoie les stats à Claude et récupère une analyse textuelle riche.
    Retourne le texte de l'analyse.
    """
    prompt = f"""Tu es un analyste immobilier expert sur le marché de Dubaï.

Voici les données collectées cette semaine sur le marché immobilier dubaiote :

{json.dumps(stats, indent=2, ensure_ascii=False)}

Rédige une analyse hebdomadaire professionnelle en français comprenant :
1. **Résumé exécutif** (2-3 phrases, chiffres clés)
2. **Tendances par district** (quels quartiers montent, lesquels baissent, et pourquoi probablement)
3. **Signaux d'alerte** (anomalies, risques à surveiller)
4. **Opportunités d'investissement** identifiées cette semaine
5. **Prévision courte terme** pour la semaine prochaine

Format : markdown avec émojis pour les sections. Ton professionnel mais accessible.
Longueur : 400-500 mots.
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def run_analysis() -> tuple[dict, str]:
    """Point d'entrée : récupère les stats, fait analyser par Claude, retourne les deux."""
    print("\n🤖 Analyse IA démarrée...")
    stats = get_weekly_stats()
    print(f"  Stats récupérées: {stats['global']['total_listings']} annonces cette semaine")

    analysis = analyze_with_claude(stats)
    print("  ✅ Analyse Claude générée")

    return stats, analysis


if __name__ == "__main__":
    stats, analysis = run_analysis()
    print("\n" + "="*60)
    print(analysis)

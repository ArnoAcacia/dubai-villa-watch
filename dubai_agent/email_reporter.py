"""
dubai_agent/email_reporter.py
Email dominical — résumé loyers + évolution semaine vs semaine
"""

import sqlite3, smtplib, ssl, os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from typing import Optional

DB_PATH      = "dubai_realestate.db"
SMTP_HOST    = os.getenv("SMTP_HOST",    "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT") or "465")   # défaut 465 si secret vide ou absent
SMTP_USER    = os.getenv("SMTP_USER",    "votre@gmail.com")
SMTP_PASSWORD= os.getenv("SMTP_PASSWORD","")
TO_EMAIL     = os.getenv("TO_EMAIL",     "destinataire@email.com")
DASHBOARD_URL= os.getenv("DASHBOARD_URL","https://dubai-villa-watch.com")


# ── Stats avec comparaison semaine précédente ─────────────────────────────────
def get_email_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)

    def week_stats(days_ago_start, days_ago_end=0):
        """Loyers annuels moyens pour une fenêtre temporelle."""
        return conn.execute(f"""
            SELECT COUNT(*), AVG(rent_annual_aed), MIN(rent_annual_aed), MAX(rent_annual_aed)
            FROM rental_listings
            WHERE scraped_at >= date('now','-{days_ago_start} days')
              AND scraped_at <  date('now','-{days_ago_end} days')
        """).fetchone()

    def zone_stats(days_ago_start, days_ago_end=0):
        return conn.execute(f"""
            SELECT zone, COUNT(*), AVG(rent_annual_aed), AVG(rent_per_sqft_annual)
            FROM rental_listings
            WHERE scraped_at >= date('now','-{days_ago_start} days')
              AND scraped_at <  date('now','-{days_ago_end} days')
            GROUP BY zone ORDER BY AVG(rent_annual_aed) DESC
        """).fetchall()

    def beds_stats(days_ago_start, days_ago_end=0):
        return conn.execute(f"""
            SELECT bedrooms, COUNT(*), AVG(rent_annual_aed), MIN(rent_annual_aed), MAX(rent_annual_aed)
            FROM rental_listings
            WHERE scraped_at >= date('now','-{days_ago_start} days')
              AND scraped_at <  date('now','-{days_ago_end} days')
            GROUP BY bedrooms ORDER BY bedrooms
        """).fetchall()

    # Semaine courante vs précédente
    cur  = week_stats(7)
    prev = week_stats(14, 7)

    cur_zones  = zone_stats(7)
    prev_zones = {r[0]: r for r in zone_stats(14, 7)}

    cur_beds   = beds_stats(7)
    prev_beds  = {r[0]: r for r in beds_stats(14, 7)}

    # Nouvelles annonces (< 24h)
    new_listings = conn.execute("""
        SELECT title, zone, rent_annual_aed, sqft, bedrooms, furnished, cheques, url
        FROM rental_listings
        WHERE scraped_at >= datetime('now','-24 hours')
        ORDER BY rent_annual_aed ASC LIMIT 5
    """).fetchall()

    conn.close()

    def pct(cur_val, prev_val):
        if not prev_val or not cur_val: return None
        return round((cur_val - prev_val) / prev_val * 100, 1)

    # Construction du dict zones avec delta
    zones_with_delta = []
    for r in cur_zones:
        prev_r = prev_zones.get(r[0])
        delta  = pct(r[2], prev_r[2]) if prev_r else None
        zones_with_delta.append({
            "zone": r[0], "count": r[1],
            "avg_rent": round(r[2] or 0),
            "avg_ppsqft": round(r[3] or 0, 1),
            "delta": delta,
            "prev_avg": round(prev_r[2]) if prev_r else None,
        })

    # Beds avec delta
    beds_with_delta = []
    for r in cur_beds:
        prev_r = prev_beds.get(r[0])
        beds_with_delta.append({
            "beds": r[0], "count": r[1],
            "avg":  round(r[2] or 0),
            "min":  r[3], "max": r[4],
            "delta": pct(r[2], prev_r[2]) if prev_r else None,
            "prev_avg": round(prev_r[2]) if prev_r else None,
        })

    return {
        "date_label":    datetime.now().strftime("%d %B %Y"),
        "week":          datetime.now().strftime("Semaine %W · %Y"),
        "total":         cur[0],
        "avg_rent":      round(cur[1] or 0),
        "min_rent":      cur[2],
        "max_rent":      cur[3],
        "variation_pct": pct(cur[1], prev[1]),
        "prev_avg_rent": round(prev[1]) if prev[1] else None,
        "by_zone":       zones_with_delta,
        "by_beds":       beds_with_delta,
        "new_listings":  [{"title":r[0],"zone":r[1],"rent":r[2],"sqft":r[3],
                           "beds":r[4],"furn":r[5],"cheques":r[6],"url":r[7]}
                          for r in new_listings],
    }


# ── HTML Email ────────────────────────────────────────────────────────────────
def build_html_email(stats: dict, ai_analysis: str, pdf_attached: bool = True) -> str:

    fmt  = lambda n: f"AED {n:,.0f}".replace(",", " ") if n else "N/A"
    fmtK = lambda n: f"AED {n//1000}K" if n else "N/A"
    fmtM = lambda n: f"AED {n//12:,.0f}/mois".replace(",", " ") if n else ""

    vp   = stats.get("variation_pct")
    vp_color  = "#6bbc88" if vp and vp >= 0 else "#c97060"
    vp_arrow  = "▲" if vp and vp >= 0 else "▼"
    vp_label  = f"{vp_arrow} {abs(vp):.1f}% vs semaine précédente" if vp is not None else "Première semaine"
    prev_label= f"Semaine préc. : {fmt(stats.get('prev_avg_rent'))}/an" if stats.get("prev_avg_rent") else ""

    # ── Zone rows ──────────────────────────────────────────────────────────
    zone_rows = ""
    for z in stats["by_zone"]:
        d = z.get("delta")
        d_html = ""
        if d is not None:
            d_color = "#6bbc88" if d >= 0 else "#c97060"
            d_arrow = "▲" if d >= 0 else "▼"
            prev    = f"(préc. AED {z['prev_avg']//1000}K)" if z.get("prev_avg") else ""
            d_html  = f'<span style="color:{d_color};font-size:11px;">{d_arrow} {abs(d):.1f}%</span><br><span style="color:#3a3528;font-size:9px;">{prev}</span>'
        zone_rows += f"""
        <tr>
          <td style="padding:10px 14px;font-family:Georgia,serif;font-size:14px;color:#ddd5c4;border-bottom:1px solid #1e2228;">{z['zone']}</td>
          <td style="padding:10px 14px;font-size:12px;color:#d4a853;text-align:center;border-bottom:1px solid #1e2228;">{z['count']}</td>
          <td style="padding:10px 14px;font-size:13px;color:#ddd5c4;text-align:right;border-bottom:1px solid #1e2228;">{fmtK(z['avg_rent'])}/an<br><span style="color:#7a7060;font-size:10px;">{fmtM(z['avg_rent'])}</span></td>
          <td style="padding:10px 14px;text-align:right;border-bottom:1px solid #1e2228;">{d_html}</td>
        </tr>"""

    # ── Beds rows ──────────────────────────────────────────────────────────
    beds_rows = ""
    bed_icons = {3:"🛏×3", 4:"🛏×4", 5:"🛏×5"}
    for b in stats["by_beds"]:
        d = b.get("delta")
        d_html = ""
        if d is not None:
            d_color = "#6bbc88" if d >= 0 else "#c97060"
            d_arrow = "▲" if d >= 0 else "▼"
            prev    = f"préc. AED {b['prev_avg']//1000}K" if b.get("prev_avg") else ""
            d_html  = f'<span style="color:{d_color};font-weight:600;">{d_arrow} {abs(d):.1f}%</span><br><span style="color:#3a3528;font-size:9px;">{prev}</span>'
        beds_rows += f"""
        <tr>
          <td style="padding:11px 14px;font-family:Georgia,serif;font-size:14px;color:#ddd5c4;border-bottom:1px solid #1e2228;">{bed_icons.get(b['beds'],'')} &nbsp;{b['beds']} chambres</td>
          <td style="padding:11px 14px;font-size:12px;color:#d4a853;text-align:center;border-bottom:1px solid #1e2228;">{b['count']}</td>
          <td style="padding:11px 14px;font-size:13px;color:#d4a853;text-align:right;border-bottom:1px solid #1e2228;">{fmtK(b['avg'])}/an<br><span style="color:#7a7060;font-size:10px;">{fmtM(b['avg'])}</span></td>
          <td style="padding:11px 14px;font-size:11px;color:#6bbc88;text-align:right;border-bottom:1px solid #1e2228;">{fmtK(b['min'])}/an</td>
          <td style="padding:11px 14px;font-size:11px;color:#c97060;text-align:right;border-bottom:1px solid #1e2228;">{fmtK(b['max'])}/an</td>
          <td style="padding:11px 14px;text-align:right;border-bottom:1px solid #1e2228;">{d_html}</td>
        </tr>"""

    # ── New listings ───────────────────────────────────────────────────────
    listing_cards = ""
    for l in stats["new_listings"]:
        url  = l.get("url") or DASHBOARD_URL
        furn = "✓ Meublée" if l.get("furn") else "Non meublée"
        chq  = f"{l['cheques']} chèque{'s' if l['cheques']>1 else ''}" if l.get("cheques") else ""
        listing_cards += f"""
        <tr><td style="padding:0 0 12px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0f12;border:1px solid #2a2820;border-radius:3px;">
            <tr><td style="padding:14px 18px;">
              <table width="100%" cellpadding="0" cellspacing="0"><tr>
                <td>
                  <p style="margin:0 0 4px;font-family:Georgia,serif;font-size:14px;color:#ddd5c4;">{str(l['title'])[:72]}…</p>
                  <p style="margin:0;font-size:10px;color:#5a5040;letter-spacing:1px;">
                    {l['zone'].upper()} &nbsp;·&nbsp; {l['beds']}BR &nbsp;·&nbsp; {furn} &nbsp;·&nbsp; {chq}
                    {f"&nbsp;·&nbsp; {l['sqft']:,} sqft" if l.get('sqft') else ""}
                  </p>
                </td>
                <td style="text-align:right;white-space:nowrap;padding-left:16px;">
                  <p style="margin:0;font-family:Georgia,serif;font-size:18px;color:#d4a853;">{fmtK(l['rent'])}/an</p>
                  <p style="margin:2px 0 0;font-size:10px;color:#7a7060;">{fmtM(l['rent'])}</p>
                  <a href="{url}" style="display:inline-block;margin-top:7px;padding:4px 12px;border:1px solid #d4a853;border-radius:2px;font-size:10px;color:#d4a853;text-decoration:none;letter-spacing:1px;">VOIR →</a>
                </td>
              </tr></table>
            </td></tr>
          </table>
        </td></tr>"""

    # ── AI paragraphs ──────────────────────────────────────────────────────
    ai_html = ""
    for line in ai_analysis.split("\n"):
        line = line.strip()
        if not line: ai_html += '<p style="margin:8px 0;"></p>'; continue
        clean = line.replace("**","").replace("*","").replace("## ","").replace("# ","")
        if line.startswith("##") or (line.startswith("**") and line.endswith("**")):
            ai_html += f'<p style="margin:16px 0 6px;font-size:10px;color:#d4a853;letter-spacing:2px;text-transform:uppercase;">{clean}</p>'
        elif line.startswith(("- ","• ")):
            ai_html += f'<p style="margin:0 0 6px 12px;font-family:Georgia,serif;font-size:13px;color:#a09070;line-height:1.7;">• {clean[2:]}</p>'
        else:
            ai_html += f'<p style="margin:0 0 10px;font-family:Georgia,serif;font-size:13px;color:#a09070;line-height:1.85;">{clean}</p>'

    # ── Dashboard quick links ──────────────────────────────────────────────
    links = [
        ("Vue d'ensemble",  f"{DASHBOARD_URL}#overview",  "📊"),
        ("Évolution loyers",f"{DASHBOARD_URL}#evolution", "📈"),
        ("Jumeirah 1/2/3",  f"{DASHBOARD_URL}#jumeirah",  "🏡"),
        ("Umm Suqeim",      f"{DASHBOARD_URL}#umm",       "🌴"),
        ("Al Safa",         f"{DASHBOARD_URL}#safa",      "🏘️"),
        ("Villas 3BR",      f"{DASHBOARD_URL}#br3",       "🛏"),
        ("Villas 4BR",      f"{DASHBOARD_URL}#br4",       "🛏"),
    ]
    link_cells = "".join(f"""
      <td style="text-align:center;padding:0 5px;">
        <a href="{url}" style="display:inline-block;padding:9px 14px;background:#0d0f12;border:1px solid #1e2228;border-radius:3px;text-decoration:none;">
          <span style="display:block;font-size:17px;margin-bottom:3px;">{icon}</span>
          <span style="font-size:9px;color:#d4a853;letter-spacing:1px;">{lbl.upper()}</span>
        </a>
      </td>""" for lbl,url,icon in links)

    # ── Variation header block ──────────────────────────────────────────────
    var_block = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0f12;border:1px solid #1e2228;border-radius:3px;margin-bottom:4px;">
        <tr>
          <td style="padding:16px 20px;border-right:1px solid #1e2228;text-align:center;width:33%;">
            <p style="margin:0 0 4px;font-size:9px;color:#5a5040;letter-spacing:2px;">LOYER ANNUEL MOYEN</p>
            <p style="margin:0;font-family:Georgia,serif;font-size:24px;color:#d4a853;">{fmtK(stats['avg_rent'])}/an</p>
            <p style="margin:3px 0 0;font-size:11px;color:#7a7060;">{fmtM(stats['avg_rent'])}</p>
          </td>
          <td style="padding:16px 20px;border-right:1px solid #1e2228;text-align:center;width:33%;">
            <p style="margin:0 0 4px;font-size:9px;color:#5a5040;letter-spacing:2px;">ÉVOLUTION HEBDO</p>
            <p style="margin:0;font-family:Georgia,serif;font-size:28px;color:{vp_color};font-weight:bold;">{vp_label}</p>
            <p style="margin:3px 0 0;font-size:10px;color:#5a5040;">{prev_label}</p>
          </td>
          <td style="padding:16px 20px;text-align:center;width:33%;">
            <p style="margin:0 0 4px;font-size:9px;color:#5a5040;letter-spacing:2px;">FOURCHETTE / ANNONCES</p>
            <p style="margin:0;font-size:13px;color:#ddd5c4;">{fmtK(stats['min_rent'])} → {fmtK(stats['max_rent'])}</p>
            <p style="margin:3px 0 0;font-size:11px;color:#d4a853;">{stats['total']} villas scannées</p>
          </td>
        </tr>
      </table>"""

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dubai Villa Watch — {stats['date_label']}</title></head>
<body style="margin:0;padding:0;background:#07080a;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#07080a;">
<tr><td align="center" style="padding:28px 16px;">
<table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;background:#0a0c0e;border:1px solid #1e2228;">

  <!-- GOLD BAR -->
  <tr><td style="height:4px;background:linear-gradient(90deg,#7a5820,#d4a853,#7a5820);"></td></tr>

  <!-- HEADER -->
  <tr><td style="padding:30px 36px 22px;text-align:center;border-bottom:1px solid #1e2228;">
    <p style="margin:0 0 3px;font-size:9px;color:#5a5040;letter-spacing:4px;">DUBAI VILLA WATCH</p>
    <h1 style="margin:0 0 6px;font-family:Georgia,serif;font-size:26px;font-weight:400;color:#ddd5c4;">Rapport Dominical des Loyers</h1>
    <p style="margin:0;font-size:11px;color:#5a5040;">Villas 3–5 ch. · Jumeirah / Umm Suqeim / Al Safa · {stats['date_label']}</p>
    <p style="margin:6px 0 0;font-size:10px;color:#3a3528;">{stats['week']}</p>
  </td></tr>

  <!-- VARIATION BLOCK -->
  <tr><td style="padding:22px 36px 0;">
    <p style="margin:0 0 10px;font-size:9px;color:#d4a853;letter-spacing:3px;">📊 SYNTHÈSE DE LA SEMAINE</p>
    {var_block}
  </td></tr>

  <!-- DASHBOARD LINKS -->
  <tr><td style="padding:18px 36px;border-bottom:1px solid #1e2228;">
    <p style="margin:0 0 12px;font-size:9px;color:#5a5040;letter-spacing:3px;">ACCÈS RAPIDE AU DASHBOARD</p>
    <table cellpadding="0" cellspacing="0"><tr>{link_cells}</tr></table>
  </td></tr>

  <!-- ZONE TABLE -->
  <tr><td style="padding:22px 36px 0;">
    <p style="margin:0 0 14px;font-size:9px;color:#d4a853;letter-spacing:3px;">📍 LOYER ANNUEL PAR ZONE — ÉVOLUTION S/S</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e2228;">
      <tr style="background:#0d0f12;">
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:left;font-weight:400;">ZONE</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:center;font-weight:400;">ANNONCES</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">LOYER MOYEN</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">VS SEM. PRÉC.</th>
      </tr>
      {zone_rows}
    </table>
    <p style="margin:8px 0 20px;text-align:right;">
      <a href="{DASHBOARD_URL}#zones" style="font-size:10px;color:#d4a853;text-decoration:none;letter-spacing:1px;">Voir détail par zone →</a>
    </p>
  </td></tr>

  <!-- BEDS TABLE -->
  <tr><td style="padding:0 36px 0;border-top:1px solid #1e2228;">
    <p style="margin:20px 0 14px;font-size:9px;color:#d4a853;letter-spacing:3px;">🛏 LOYER ANNUEL PAR CONFIGURATION — ÉVOLUTION S/S</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #1e2228;">
      <tr style="background:#0d0f12;">
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:left;font-weight:400;">TYPE</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:center;font-weight:400;">ANNONCES</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">LOYER MOYEN</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">MIN</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">MAX</th>
        <th style="padding:8px 14px;font-size:8px;color:#5a5040;letter-spacing:2px;text-align:right;font-weight:400;">VS SEM. PRÉC.</th>
      </tr>
      {beds_rows}
    </table>
    <p style="margin:8px 0 20px;text-align:right;">
      <a href="{DASHBOARD_URL}#bedrooms" style="font-size:10px;color:#d4a853;text-decoration:none;letter-spacing:1px;">Voir évolution par configuration →</a>
    </p>
  </td></tr>

  <!-- NEW LISTINGS -->
  <tr><td style="padding:0 36px;border-top:1px solid #1e2228;">
    <p style="margin:20px 0 4px;font-size:9px;color:#d4a853;letter-spacing:3px;">💎 NOUVELLES ANNONCES CETTE SEMAINE</p>
    <p style="margin:0 0 14px;font-size:10px;color:#3a3528;">Publiées dans les dernières 24h · loyers les plus accessibles</p>
    <table width="100%" cellpadding="0" cellspacing="0">{listing_cards}</table>
    <p style="margin:4px 0 20px;text-align:right;">
      <a href="{DASHBOARD_URL}#listings" style="font-size:10px;color:#d4a853;text-decoration:none;letter-spacing:1px;">Toutes les annonces →</a>
    </p>
  </td></tr>

  <!-- AI ANALYSIS -->
  <tr><td style="padding:0 36px 22px;border-top:1px solid #1e2228;background:#07080a;">
    <p style="margin:20px 0 14px;font-size:9px;color:#d4a853;letter-spacing:3px;">🤖 ANALYSE IA — CLAUDE SONNET</p>
    <div style="padding:18px 22px;background:#0a0c0e;border-left:2px solid #d4a853;">{ai_html}</div>
    <p style="margin:12px 0 0;text-align:right;">
      <a href="{DASHBOARD_URL}#ai" style="font-size:10px;color:#d4a853;text-decoration:none;letter-spacing:1px;">Analyse complète sur le dashboard →</a>
    </p>
  </td></tr>

  <!-- CTA -->
  <tr><td style="padding:26px 36px;text-align:center;border-top:1px solid #1e2228;">
    <a href="{DASHBOARD_URL}" style="display:inline-block;padding:13px 38px;border:1px solid #d4a853;border-radius:2px;font-size:11px;color:#d4a853;text-decoration:none;letter-spacing:3px;">
      OUVRIR LE DASHBOARD COMPLET →
    </a>
    {"<p style='margin:10px 0 0;font-size:10px;color:#3a3528;'>📎 Rapport PDF en pièce jointe</p>" if pdf_attached else ""}
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="padding:16px 36px;text-align:center;border-top:1px solid #1e2228;">
    <p style="margin:0;font-size:9px;color:#2a2520;line-height:1.9;">
      Dubai Villa Watch · Rapport dominical automatique · {stats['date_label']}<br>
      Sources : Bayut.com · PropertyFinder.ae · Dubizzle.com · Analyse : Claude AI (Anthropic)<br>
      Pour se désabonner, répondre à cet email
    </p>
  </td></tr>
  <tr><td style="height:3px;background:linear-gradient(90deg,#7a5820,#d4a853,#7a5820);"></td></tr>

</table>
</td></tr></table>
</body></html>"""


# ── Send ──────────────────────────────────────────────────────────────────────
def send_weekly_email(stats: dict, ai_analysis: str, pdf_path: Optional[str] = None) -> bool:
    html_body = build_html_email(stats, ai_analysis, bool(pdf_path))
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🏡 Dubai Villa Watch — Loyers semaine du {stats['date_label']}"
    msg["From"]    = f"Dubai Villa Watch <{SMTP_USER}>"
    msg["To"]      = TO_EMAIL

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(f"Dubai Villa Watch — {stats['date_label']}\nLoyer moyen: AED {stats['avg_rent']:,.0f}/an\nDashboard: {DASHBOARD_URL}", "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    if pdf_path:
        try:
            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
                part.add_header("Content-Disposition", "attachment",
                                filename=f"DubaiWatch_{stats['date_label'].replace(' ','_')}.pdf")
                msg.attach(part)
        except Exception as e:
            print(f"  ⚠️  PDF non attaché: {e}")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as srv:
            srv.login(SMTP_USER, SMTP_PASSWORD)
            srv.sendmail(SMTP_USER, TO_EMAIL, msg.as_string())
        print(f"  ✅ Email envoyé → {TO_EMAIL}")
        return True
    except Exception as e:
        print(f"  ❌ Erreur SMTP: {e}")
        return False


def preview_email_html(stats: dict, ai_analysis: str, output_path: str = "email_preview.html") -> str:
    html = build_html_email(stats, ai_analysis, True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Prévisualisation: {output_path}")
    return output_path


# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mock = {
        "date_label": "09 Mars 2026", "week": "Semaine 10 · 2026",
        "total": 135, "avg_rent": 498000, "min_rent": 245000, "max_rent": 1150000,
        "variation_pct": 2.3, "prev_avg_rent": 487000,
        "by_zone": [
            {"zone":"Al Safa 1",    "count":12,"avg_rent":700000,"avg_ppsqft":148,"delta":+4.3,"prev_avg":671000},
            {"zone":"Jumeirah 1",   "count":28,"avg_rent":650000,"avg_ppsqft":141,"delta":+3.1,"prev_avg":630000},
            {"zone":"Umm Suqeim 1", "count":18,"avg_rent":600000,"avg_ppsqft":132,"delta":+2.9,"prev_avg":583000},
            {"zone":"Jumeirah 2",   "count":34,"avg_rent":560000,"avg_ppsqft":128,"delta":+2.4,"prev_avg":547000},
            {"zone":"Al Safa 2",    "count":12,"avg_rent":510000,"avg_ppsqft":118,"delta":+1.6,"prev_avg":502000},
            {"zone":"Al Manara",    "count": 8,"avg_rent":580000,"avg_ppsqft":130,"delta":+2.2,"prev_avg":567000},
            {"zone":"Jumeirah 3",   "count":21,"avg_rent":470000,"avg_ppsqft":112,"delta":+1.8,"prev_avg":462000},
            {"zone":"Umm Suqeim 2", "count":22,"avg_rent":440000,"avg_ppsqft":108,"delta":-0.5,"prev_avg":442000},
        ],
        "by_beds": [
            {"beds":3,"count":48,"avg":316000,"min":245000,"max":450000,"delta":+1.8,"prev_avg":310000},
            {"beds":4,"count":62,"avg":580000,"min":390000,"max":720000,"delta":+2.3,"prev_avg":567000},
            {"beds":5,"count":25,"avg":935000,"min":680000,"max":1150000,"delta":+3.1,"prev_avg":907000},
        ],
        "new_listings": [
            {"title":"Villa 3BR rénovée avec jardin 200m²","zone":"Jumeirah 3","rent":305000,"sqft":2800,"beds":3,"furn":False,"cheques":2,"url":"#"},
            {"title":"Villa 4BR meublée proche école française","zone":"Al Safa 2","rent":490000,"sqft":3200,"beds":4,"furn":True,"cheques":1,"url":"#"},
            {"title":"Villa 3BR avec studio indépendant","zone":"Jumeirah 2","rent":345000,"sqft":2950,"beds":3,"furn":False,"cheques":4,"url":"#"},
        ],
    }
    mock_ai = """## Résumé de la semaine
Progression hebdomadaire de +2,3% sur le loyer annuel moyen des villas 3-5BR dans les zones surveillées. La demande reste structurellement excédentaire face à une offre de 135 annonces actives.

## Tendances par zone
Al Safa 1 affiche la meilleure performance à +4,3%, portée par la tension sur le stock (12 villas seulement). Umm Suqeim 2 est l'unique zone en légère correction à -0,5%.

## Signaux à suivre
- Umm Suqeim 2 : stock en hausse de +18%, surveiller les prochaines semaines.
- Villas 5BR : forte progression (+3,1%) avec de moins en moins d'offres disponibles.

## Opportunité de la semaine
Jumeirah 3 · Villas 3BR : loyers encore sous AED 320 000/an pour des biens rénovés. Dernière zone accessible du corridor Jumeirah."""
    preview_email_html(mock, mock_ai, "/mnt/user-data/outputs/email_preview.html")

"""
dubai_agent/report_generator.py
Génération du rapport PDF hebdomadaire — loyers villas Dubaï
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

REPORTS_DIR = "reports"

# ── Palette ───────────────────────────────────────────────────────────────────
GOLD      = colors.HexColor("#D4A853")
DARK_BG   = colors.HexColor("#07080A")
DARK_CARD = colors.HexColor("#0D0F12")
LIGHT_TXT = colors.HexColor("#DDD5C4")
MID_TXT   = colors.HexColor("#A09070")
DIM_TXT   = colors.HexColor("#5A5040")
GREEN     = colors.HexColor("#6BBC88")
RED       = colors.HexColor("#C97060")


def on_page(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, h - 5, w, 5, fill=1, stroke=0)
    canvas.setFillColor(DIM_TXT)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(
        w / 2, 1.2 * cm,
        f"Dubai Villa Watch  •  Loyers {datetime.now().strftime('%d %B %Y')}  •  Page {doc.page}"
    )
    canvas.setFillColor(GOLD)
    canvas.rect(0, 0.9 * cm, w, 1, fill=1, stroke=0)
    canvas.restoreState()


def build_styles():
    return {
        "title": ParagraphStyle("T",
            fontName="Helvetica-Bold", fontSize=26,
            textColor=LIGHT_TXT, alignment=TA_CENTER, spaceAfter=6),
        "subtitle": ParagraphStyle("ST",
            fontName="Helvetica", fontSize=11,
            textColor=DIM_TXT, alignment=TA_CENTER, spaceAfter=20),
        "section": ParagraphStyle("S",
            fontName="Helvetica-Bold", fontSize=13,
            textColor=GOLD, spaceBefore=18, spaceAfter=8),
        "body": ParagraphStyle("B",
            fontName="Helvetica", fontSize=10,
            textColor=MID_TXT, leading=16, spaceAfter=8),
        "small": ParagraphStyle("Sm",
            fontName="Helvetica", fontSize=8, textColor=DIM_TXT),
    }


def make_kpi_table(stats: dict) -> Table:
    s = build_styles()
    avg  = stats["global"].get("avg_rent_annual", 0)
    pct  = stats["global"].get("price_change_pct")
    tot  = stats["global"].get("total_listings", 0)
    prev = stats["prev_week"].get("avg_rent_annual")

    pct_text  = f"+{pct}%" if pct and pct >= 0 else (f"{pct}%" if pct else "—")
    pct_color = GREEN if pct and pct >= 0 else RED

    def cell(label, value, note=""):
        return [
            Paragraph(label, ParagraphStyle("kl", fontName="Helvetica",
                fontSize=8, textColor=DIM_TXT, alignment=TA_CENTER)),
            Paragraph(value, ParagraphStyle("kv", fontName="Helvetica-Bold",
                fontSize=18, textColor=GOLD, alignment=TA_CENTER)),
            Paragraph(note, ParagraphStyle("kn", fontName="Helvetica",
                fontSize=9, textColor=MID_TXT, alignment=TA_CENTER)),
        ]

    data = [
        cell("LOYER ANNUEL MOYEN",
             f"AED {avg:,.0f}/an".replace(",", " "),
             f"≈ AED {avg//12:,.0f}/mois".replace(",", " ")),
        cell("VARIATION HEBDO",
             pct_text,
             f"Préc. AED {prev:,.0f}".replace(",", " ") if prev else "1ère semaine"),
        cell("VILLAS SCANNÉES",
             str(tot),
             "annonces actives"),
    ]

    col_w = [5.5 * cm, 5.5 * cm, 5.5 * cm]
    t = Table([data], colWidths=col_w, rowHeights=None)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), DARK_CARD),
        ("BOX",          (0, 0), (-1, -1), 1, GOLD),
        ("LINEAFTER",    (0, 0), (1, 0),   0.5, colors.HexColor("#2A2015")),
        ("TOPPADDING",   (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 12),
    ]))
    return t


def make_zone_table(districts: list) -> Table:
    headers = ["ZONE", "LOYER MOYEN / AN", "LOYER / MOIS", "ANNONCES"]
    hstyle  = ParagraphStyle("hh", fontName="Helvetica-Bold",
                              fontSize=8, textColor=GOLD,
                              alignment=TA_CENTER, letterSpacing=1)
    rows = [[Paragraph(h, hstyle) for h in headers]]

    for d in districts:
        avg    = d.get("avg_rent", 0)
        monthly = avg // 12
        rows.append([
            Paragraph(d["name"], ParagraphStyle("dn", fontName="Helvetica-Bold",
                      fontSize=10, textColor=LIGHT_TXT)),
            Paragraph(f"AED {avg:,.0f}".replace(",", " "),
                      ParagraphStyle("dv", fontName="Helvetica", fontSize=10,
                                     textColor=GOLD, alignment=TA_RIGHT)),
            Paragraph(f"AED {monthly:,.0f}".replace(",", " "),
                      ParagraphStyle("dm", fontName="Helvetica", fontSize=9,
                                     textColor=MID_TXT, alignment=TA_RIGHT)),
            Paragraph(str(d.get("listing_count", "—")),
                      ParagraphStyle("dc", fontName="Helvetica", fontSize=10,
                                     textColor=MID_TXT, alignment=TA_CENTER)),
        ])

    col_w = [5 * cm, 4.5 * cm, 4 * cm, 3 * cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1A1505")),
        ("BACKGROUND",   (0, 1), (-1, -1), DARK_CARD),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1),
         [DARK_CARD, colors.HexColor("#0F1008")]),
        ("BOX",          (0, 0), (-1, -1), 1, GOLD),
        ("LINEBELOW",    (0, 0), (-1, 0),  1, GOLD),
        ("INNERGRID",    (0, 1), (-1, -1), 0.3, colors.HexColor("#2A2015")),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def generate_pdf(stats: dict, analysis_text: str,
                 output_path: str = None) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    if not output_path:
        date_str     = datetime.now().strftime("%Y-%m-%d")
        output_path  = os.path.join(REPORTS_DIR, f"dubai_loyers_{date_str}.pdf")

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.8*cm,  bottomMargin=2*cm,
    )
    styles = build_styles()
    story  = []

    # ── Titre ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*cm))
    story.append(Paragraph("DUBAI VILLA WATCH", styles["title"]))
    story.append(Paragraph(
        f"Rapport hebdomadaire des loyers  •  {datetime.now().strftime('%d %B %Y')}",
        styles["subtitle"]
    ))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=GOLD, spaceAfter=16))

    # ── KPIs ─────────────────────────────────────────────────────────────
    story.append(Paragraph("MÉTRIQUES CLÉS", styles["section"]))
    story.append(make_kpi_table(stats))
    story.append(Spacer(1, 16))

    # ── Tableau zones ────────────────────────────────────────────────────
    districts = stats.get("districts", [])
    if districts:
        story.append(Paragraph("LOYERS PAR ZONE", styles["section"]))
        story.append(make_zone_table(districts))
        story.append(Spacer(1, 16))

    # ── Tableau par chambres ─────────────────────────────────────────────
    beds_data = stats.get("by_beds", [])
    if beds_data:
        story.append(Paragraph("LOYERS PAR CONFIGURATION", styles["section"]))
        headers = ["CONFIGURATION", "LOYER MOYEN", "MINIMUM", "MAXIMUM", "ANNONCES"]
        hstyle  = ParagraphStyle("bh", fontName="Helvetica-Bold",
                                  fontSize=8, textColor=GOLD,
                                  alignment=TA_CENTER, letterSpacing=1)
        rows = [[Paragraph(h, hstyle) for h in headers]]
        icons = {3: "🛏×3  3 chambres", 4: "🛏×4  4 chambres", 5: "🛏×5  5 chambres"}
        for b in beds_data:
            rows.append([
                Paragraph(icons.get(b["bedrooms"], f"{b['bedrooms']} ch."),
                          ParagraphStyle("bn", fontName="Helvetica-Bold",
                                         fontSize=10, textColor=LIGHT_TXT)),
                Paragraph(f"AED {b['avg_rent']:,.0f}/an".replace(",", " "),
                          ParagraphStyle("ba", fontName="Helvetica", fontSize=10,
                                         textColor=GOLD, alignment=TA_RIGHT)),
                Paragraph(f"AED {(b.get('min_rent') or 0):,.0f}".replace(",", " "),
                          ParagraphStyle("bmi", fontName="Helvetica", fontSize=9,
                                         textColor=GREEN, alignment=TA_RIGHT)),
                Paragraph(f"AED {(b.get('max_rent') or 0):,.0f}".replace(",", " "),
                          ParagraphStyle("bma", fontName="Helvetica", fontSize=9,
                                         textColor=RED, alignment=TA_RIGHT)),
                Paragraph(str(b.get("count", "—")),
                          ParagraphStyle("bc", fontName="Helvetica", fontSize=10,
                                         textColor=MID_TXT, alignment=TA_CENTER)),
            ])
        col_w = [4.5*cm, 4*cm, 3.5*cm, 3.5*cm, 2.5*cm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1A1505")),
            ("BACKGROUND",    (0, 1), (-1, -1), DARK_CARD),
            ("BOX",           (0, 0), (-1, -1), 1, GOLD),
            ("LINEBELOW",     (0, 0), (-1, 0),  1, GOLD),
            ("INNERGRID",     (0, 1), (-1, -1), 0.3, colors.HexColor("#2A2015")),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 16))

    # ── Analyse IA ───────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("ANALYSE IA — CLAUDE SONNET", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=GOLD, spaceAfter=12))

    for line in analysis_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        clean = (line.replace("**", "").replace("*", "")
                 .replace("## ", "").replace("# ", ""))
        if line.startswith("##") or (line.startswith("**") and line.endswith("**")):
            story.append(Paragraph(clean, ParagraphStyle(
                "ah", fontName="Helvetica-Bold", fontSize=11,
                textColor=GOLD, spaceBefore=12, spaceAfter=4)))
        elif line.startswith(("- ", "• ")):
            story.append(Paragraph(
                "• " + clean[2:],
                ParagraphStyle("ab", fontName="Helvetica", fontSize=9,
                               textColor=MID_TXT, leftIndent=10, leading=14)))
        else:
            story.append(Paragraph(clean, styles["body"]))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=DIM_TXT, spaceAfter=8))
    story.append(Paragraph(
        "Rapport généré automatiquement par Dubai Villa Watch. "
        "Sources : Bayut.com, PropertyFinder.ae. "
        "Analyse : Claude AI (Anthropic). Document à titre informatif uniquement.",
        styles["small"]
    ))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"  ✅ Rapport PDF : {output_path}")
    return output_path


if __name__ == "__main__":
    mock_stats = {
        "week": "2026-W10",
        "global": {
            "avg_rent_annual": 580000, "avg_rent_per_sqft": 132,
            "total_listings": 47, "price_change_pct": 2.1,
        },
        "prev_week": {"avg_rent_annual": 568000, "avg_rent_per_sqft": 129},
        "districts": [
            {"name": "Al Safa 1",    "avg_rent": 700000, "avg_ppsqft": 148, "listing_count": 12},
            {"name": "Jumeirah 1",   "avg_rent": 650000, "avg_ppsqft": 141, "listing_count": 28},
            {"name": "Umm Suqeim 1", "avg_rent": 600000, "avg_ppsqft": 132, "listing_count": 18},
        ],
        "by_beds": [
            {"bedrooms": 3, "avg_rent": 316000, "min_rent": 245000, "max_rent": 450000, "count": 18},
            {"bedrooms": 4, "avg_rent": 580000, "min_rent": 390000, "max_rent": 720000, "count": 22},
            {"bedrooms": 5, "avg_rent": 935000, "min_rent": 680000, "max_rent": 1150000, "count": 7},
        ],
    }
    generate_pdf(mock_stats, "## Test\nAnalyse de test.\n- Signal 1\n- Signal 2",
                 "/mnt/user-data/outputs/test_report.pdf")

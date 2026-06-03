"""
Konvertiert das Pflichtenheft von Markdown zu PDF.
Verwendet markdown + PyMuPDF (fitz) fuer die PDF-Erzeugung.
"""
import markdown
import fitz  # PyMuPDF
import os
import tempfile

INPUT_FILE = r"c:\Users\michimueller\AI\KNX Arranger Test3\Pflichtenheft_KNX_Arranger.md"
OUTPUT_FILE = r"c:\Users\michimueller\AI\KNX Arranger Test3\Pflichtenheft_KNX_Arranger.pdf"

# Markdown einlesen
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    md_text = f.read()

# Markdown -> HTML konvertieren
html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

# CSS
css = """
body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10px;
    line-height: 1.5;
    color: #1a1a1a;
}
h1 { font-size: 22px; color: #2c5f2d; border-bottom: 3px solid #5EA126; padding-bottom: 8px; margin-top: 30px; }
h2 { font-size: 17px; color: #2c5f2d; border-bottom: 2px solid #5EA126; padding-bottom: 5px; margin-top: 25px; }
h3 { font-size: 14px; color: #3a7d3a; margin-top: 20px; }
h4 { font-size: 12px; color: #3a7d3a; margin-top: 15px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9px; }
th { background-color: #5EA126; color: white; padding: 6px 8px; text-align: left; border: 1px solid #4a8a1e; }
td { padding: 5px 8px; border: 1px solid #cccccc; vertical-align: top; }
tr:nth-child(even) { background-color: #f2f8ed; }
code, pre { font-family: Courier, monospace; font-size: 9px; background-color: #f4f4f4; }
pre { padding: 10px; border: 1px solid #ddd; }
strong { color: #2c5f2d; }
hr { border: none; border-top: 2px solid #5EA126; margin: 20px 0; }
"""

full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{html}</body></html>"

# A4
page_width = 595.28
page_height = 841.89
margin = 50

# Temporaere Datei fuer Zwischenergebnis
tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
os.close(tmp_fd)

try:
    # Methode 1: fitz.Story (HTML -> PDF)
    story = fitz.Story(html=full_html)
    content_rect = fitz.Rect(margin, margin, page_width - margin, page_height - margin - 40)
    writer = fitz.DocumentWriter(tmp_path)

    more = True
    while more:
        dev = writer.begin_page(fitz.Rect(0, 0, page_width, page_height))
        more, _ = story.place(content_rect)
        story.draw(dev)
        writer.end_page()

    writer.close()
    print("HTML-Rendering mit Story-API erfolgreich.")

except Exception as e:
    print(f"Story-API fehlgeschlagen: {e}")
    print("Verwende Fallback (Text-basiert)...")

    doc = fitz.open()
    page_w, page_h = page_width, page_height
    margin_l, margin_t, margin_r, margin_b = 50, 50, 50, 60

    lines = md_text.split("\n")
    page = doc.new_page(width=page_w, height=page_h)
    y = margin_t

    for line in lines:
        line_height = 13
        fontsize = 10
        fontname = "helv"
        color = (0.1, 0.1, 0.1)

        stripped = line.strip()

        if stripped.startswith("# "):
            fontsize, color, line_height, fontname = 20, (0.173, 0.373, 0.176), 30, "hebo"
            stripped = stripped[2:]
        elif stripped.startswith("## "):
            fontsize, color, line_height, fontname = 16, (0.173, 0.373, 0.176), 25, "hebo"
            stripped = stripped[3:]
        elif stripped.startswith("### "):
            fontsize, color, line_height, fontname = 13, (0.227, 0.490, 0.227), 22, "hebo"
            stripped = stripped[4:]
        elif stripped.startswith("#### "):
            fontsize, color, line_height, fontname = 11, (0.227, 0.490, 0.227), 18, "hebo"
            stripped = stripped[5:]
        elif stripped.startswith("---"):
            page.draw_line(fitz.Point(margin_l, y+5), fitz.Point(page_w-margin_r, y+5),
                           color=(0.369, 0.631, 0.149), width=1.5)
            y += 15
            continue
        elif stripped.startswith("| "):
            fontsize, line_height = 8, 12
        elif stripped.startswith("- "):
            stripped = "  \u2022 " + stripped[2:]
        elif stripped.startswith("```"):
            continue
        elif stripped == "":
            y += 6
            continue

        cleaned = stripped.replace("**", "").replace("*", "").replace("`", "")

        if y + line_height > page_h - margin_b:
            page = doc.new_page(width=page_w, height=page_h)
            y = margin_t

        if cleaned:
            text_rect = fitz.Rect(margin_l, y, page_w - margin_r, y + line_height + 5)
            page.insert_textbox(text_rect, cleaned, fontsize=fontsize, fontname=fontname, color=color)
            y += line_height

    doc.save(tmp_path)
    doc.close()

# Footer und Seitennummern hinzufuegen, als finale Datei speichern
doc = fitz.open(tmp_path)
total_pages = len(doc)

for i, page in enumerate(doc):
    footer_text = f"Pflichtenheft KNiX Arranger v3.2  |  \u00a9 Michael Mueller SmartHome&EnergieManagement  |  Seite {i+1} von {total_pages}"
    page.draw_line(
        fitz.Point(margin, page_height - 45),
        fitz.Point(page_width - margin, page_height - 45),
        color=(0.369, 0.631, 0.149), width=0.5
    )
    page.insert_textbox(
        fitz.Rect(margin, page_height - 40, page_width - margin, page_height - 20),
        footer_text, fontsize=7, fontname="helv",
        color=(0.4, 0.4, 0.4), align=fitz.TEXT_ALIGN_CENTER
    )

# Speichern als neue Datei
doc.ez_save(OUTPUT_FILE)
doc.close()

# Temp-Datei aufraeumen
try:
    os.remove(tmp_path)
except:
    pass

file_size = os.path.getsize(OUTPUT_FILE)
print(f"\nPDF erfolgreich erstellt: {OUTPUT_FILE}")
print(f"Seiten: {total_pages}")
print(f"Dateigroesse: {file_size / 1024:.0f} KB")

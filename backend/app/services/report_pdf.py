"""
Report exports as PDF: the same columns and rows as the CSV and XLSX (services/report_exports), drawn as a
printable table. Administrators only; the routes check reports:view and reports:export.

How it is drawn (ReportLab's page canvas, not its layout engine: that is several times slower on big tables):
- A4, landscape for wide reports and portrait for narrow ones; the column header repeats on every page; a
  title block on page 1 (report, period, time zone, time made, rows, filter NAMES, masking note); page
  numbers in the footer;
- every value is plain text drawn as it is (never read as markup); long text wraps at spaces and, for a
  word longer than its column, inside the word, so nothing is clipped or drawn over the next cell; a row
  taller than the space left continues on the next page;
- text is shaped with HarfBuzz (uharfbuzz), so Urdu and other Arabic-script text is joined and written
  right to left (right-aligned in its cell). The font is the server's own Arial (or Segoe UI or Tahoma):
  it covers Latin and Urdu, its licence allows embedding, and only the letters used are embedded. No font
  file ships with the application. Without one of these fonts, or without uharfbuzz, PDF export is refused
  (503) before anything is made; CSV and Excel keep working.
  Limitation: a single cell mixing left-to-right and right-to-left words is shaped as one run.

Size: the same row limit as the other formats (checked before anything is drawn). Memory stays small (pages
are compressed as they are finished); time grows with the rows (roughly 7 ms per row of a 16-column
report), so the drawing runs in a worker thread, batch by batch, and never blocks the server.
"""
import asyncio
import os
import re
import tempfile
import threading
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.errors import AppError
from app.services.report_exports import SHEET_TITLES, Column, discard

PDF_TYPE = "application/pdf"
# The same font twice: without shaping for left-to-right text (fast), with HarfBuzz shaping for lines that
# contain right-to-left letters (joined and ordered correctly).
BODY, BOLD, SHAPED = "ReportBody", "ReportBold", "ReportShaped"
# Font files looked for in the server's Fonts folder: regular and bold. All cover Latin and Urdu.
FONT_FILES = [("arial.ttf", "arialbd.ttf"), ("segoeui.ttf", "segoeuib.ttf"), ("tahoma.ttf", "tahomabd.ttf")]
RTL = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")         # Hebrew and Arabic-script letters
_BATCH = 200
_lock = threading.Lock()
_registered = False

# Relative column widths (by header); anything else is 1. The columns themselves are the shared ones.
WIDTHS = {
    "Visit number": 1.25, "Visitor": 1.5, "ID type": 0.6, "ID number (masked)": 1.25, "Phone (masked)": 1.05,
    "ID (masked)": 1.5, "Host": 1.3, "Host not listed": 0.65, "Department": 1.2, "Purpose": 1.5, "Gate": 1.0,
    "Check-in": 1.15, "Check-out": 1.15, "First visit": 1.15, "Last visit": 1.15, "Time": 1.15,
    "Duration (minutes)": 0.95, "Inside for (minutes)": 0.95, "Average duration (minutes)": 1.0, "Status": 1.3,
    "Checked in by": 1.1, "Checked out by": 1.1, "Operator": 1.4, "Watchlist reason": 2.0, "Source": 0.9,
    "Reason": 0.9, "Names from current records": 1.0, "Role": 0.7, "Active": 0.6, "Inside now": 0.7,
    "Visits": 0.7, "Completed visits": 0.8, "Unique visitors": 0.8, "Check-ins": 0.7, "Check-outs": 0.7,
    "Denied entries": 0.8, "Watchlist matches": 0.85,
}


def pdf_unavailable(detail: str) -> AppError:
    return AppError(503, "pdf_unavailable", f"PDF export is not available on this server ({detail}). "
                                            "CSV and Excel exports still work.")


def fonts_folder() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def ensure_fonts() -> None:
    """Registers the report font once (process-wide). Raises pdf_unavailable before anything is made."""
    global _registered
    if _registered:
        return
    with _lock:
        if _registered:
            return
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            import uharfbuzz  # noqa: F401 - text shaping for Urdu
        except ImportError:
            raise pdf_unavailable("text shaping is not installed") from None
        folder = fonts_folder()
        for regular, bold in FONT_FILES:
            if (folder / regular).is_file():
                pdfmetrics.registerFont(TTFont(BODY, str(folder / regular), shapable=False))
                pdfmetrics.registerFont(TTFont(SHAPED, str(folder / regular), shapable=True))
                pdfmetrics.registerFont(TTFont(BOLD, str(folder / (bold if (folder / bold).is_file() else regular)),
                                               shapable=False))
                _registered = True
                return
        raise pdf_unavailable("no Unicode font found")


def pdf_text(value, tz: ZoneInfo) -> str:
    """A cell as text: like the workbook (local date-times, Yes/No), but as plain printed text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    return str(value)


class PdfTable:
    """Draws one report table page by page. Not thread-safe: used by one worker thread at a time."""

    MARGIN = 28.0
    PAD = 2.5

    def __init__(self, path: str, columns: list[Column], *, title: str, about: list[tuple[str, str]]):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen.canvas import Canvas

        self.headers = [c.header for c in columns]
        weights = [WIDTHS.get(h, 1.0) for h in self.headers]
        wide = sum(weights) > 7.5
        self.page_w, self.page_h = landscape(A4) if wide else A4
        self.size = 7.0 if len(columns) > 10 else 8.0
        self.lead = self.size * 1.22
        usable = self.page_w - 2 * self.MARGIN
        self.widths = [usable * w / sum(weights) for w in weights]
        self.title, self.about = title, about
        self.canvas = Canvas(path, pagesize=(self.page_w, self.page_h), pageCompression=1, initialFontName=BODY)
        self.canvas.setTitle(f"Century Gate — {title}")
        self.canvas.setAuthor("Century Gate VMS")
        self.page = 0
        self.rows = 0
        self.y = 0.0
        self.fresh = True
        self._new_page()

    # ------------------------------------------------------------------ text
    def _width(self, text: str, font: str) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(text, font, self.size)

    def _wrap(self, text: str, font: str, width: float) -> list[str]:
        """Lines that fit `width`: at spaces first, then inside a word that is still too long."""
        from reportlab.lib.utils import simpleSplit
        room = width - 2 * self.PAD
        if not text:
            return [""]
        if "\n" not in text and self._width(text, font) <= room:
            return [text]                               # most cells: one measurement, no wrapping
        out: list[str] = []
        for part in text.splitlines() or [""]:
            for line in simpleSplit(part, font, self.size, room) or [""]:
                while self._width(line, font) > room and len(line) > 1:
                    cut = len(line) - 1
                    while cut > 1 and self._width(line[:cut], font) > room:
                        cut -= 1
                    out.append(line[:cut])
                    line = line[cut:]
                out.append(line)
        return out

    # ------------------------------------------------------------------ pages
    def _new_page(self) -> None:
        c = self.canvas
        if self.page:
            c.showPage()
        self.page += 1
        m = self.MARGIN
        top = self.page_h - m
        if self.page == 1:
            c.setFont(BOLD, 14)
            c.drawString(m, top - 14, self.title)
            top -= 22
            c.setFont(BODY, 8)
            for label, text in self.about:
                c.setFont(BOLD, 8)
                c.drawString(m, top - 8, f"{label}:")
                c.setFont(BODY, 8)
                c.drawString(m + 70, top - 8, text)
                top -= 10.5
            top -= 6
        else:
            c.setFont(BOLD, 9)
            c.drawString(m, top - 9, self.title)
            top -= 16
        c.setFont(BODY, 7)
        c.setFillGray(0.35)
        c.drawString(m, m / 2, f"Century Gate VMS · {self.title}")
        c.drawRightString(self.page_w - m, m / 2, f"Page {self.page}")
        c.setFillGray(0)
        self.y = top
        self._draw_row([self._wrap(h, BOLD, w) for h, w in zip(self.headers, self.widths, strict=True)], BOLD,
                       shade=True)

    def _draw_row(self, cells: list[list[str]], font: str, shade: bool = False) -> None:
        """Draws the row's lines that fit on this page; the rest continues on the next one."""
        c = self.canvas
        m = self.MARGIN
        while True:
            room = int((self.y - m - 2 * self.PAD) // self.lead)
            lines = max(len(cell) for cell in cells)
            if room < lines and not self.fresh and not shade:
                self._new_page()                        # does not fit: start it on the next page
                continue
            if room < 1:
                raise RuntimeError("The page has no room for the table.")    # cannot happen with A4 margins
            shown = min(lines, room)                    # on a fresh page a very tall row is split
            height = shown * self.lead + 2 * self.PAD
            if shade:
                c.setFillGray(0.92)
                c.rect(m, self.y - height, self.page_w - 2 * m, height, stroke=0, fill=1)
                c.setFillGray(0)
            c.setFont(font, self.size)
            x = m
            for cell, width in zip(cells, self.widths, strict=True):
                for i, line in enumerate(cell[:shown]):
                    baseline = self.y - self.PAD - self.size - i * self.lead + 1.5
                    if RTL.search(line):                # shaped, right to left, right-aligned
                        c.setFont(SHAPED, self.size)
                        c.drawRightString(x + width - self.PAD, baseline, line)
                        c.setFont(font, self.size)
                    else:
                        c.drawString(x + self.PAD, baseline, line)
                x += width
            self.y -= height
            c.setLineWidth(0.25)
            c.setStrokeGray(0.6)
            c.line(m, self.y, self.page_w - m, self.y)
            self.fresh = shade                          # the header leaves the page "fresh"; a body row does not
            cells = [cell[shown:] for cell in cells]
            if not any(cells):
                return
            self._new_page()

    # ------------------------------------------------------------------ rows
    def add_rows(self, rows: list[list[str]]) -> None:
        for texts in rows:
            self.rows += 1
            self._draw_row([self._wrap(t, BODY, w) for t, w in zip(texts, self.widths, strict=True)], BODY)

    def finish(self) -> None:
        if not self.rows:
            self.canvas.setFont(BODY, self.size + 1)
            self.canvas.drawString(self.MARGIN + self.PAD, self.y - 14, "No rows match this report.")
        self.canvas.save()


async def pdf_file(columns: list[Column], rows: AsyncIterator, *, report: str, tz_name: str,
                   about: list[tuple[str, str]]) -> str:
    """Draws the PDF into a temporary file (returned; the caller deletes it once sent) from the SAME
    columns and rows as the CSV and XLSX. Rows are read here and drawn in a worker thread in batches.
    Anything that fails removes the file; nothing half-made is ever sent."""
    ensure_fonts()
    tz = ZoneInfo(tz_name)
    handle, path = tempfile.mkstemp(prefix="cgvms-report-", suffix=".pdf")
    os.close(handle)
    try:
        table = await asyncio.to_thread(PdfTable, path, columns, title=SHEET_TITLES.get(report, report), about=about)
        batch: list[list[str]] = []
        async for row in rows:
            batch.append([pdf_text(column.value(row), tz) for column in columns])
            if len(batch) >= _BATCH:
                await asyncio.to_thread(table.add_rows, batch)
                batch = []
        if batch:
            await asyncio.to_thread(table.add_rows, batch)
        await asyncio.to_thread(table.finish)
        return path
    except BaseException:
        discard(path)
        raise

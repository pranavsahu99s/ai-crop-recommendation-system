"""A small PDF writer for the downloadable recommendation report.

Uses the PDF base-14 Helvetica fonts, so no font files or third-party
packages are needed. Supports text, wrapped paragraphs, lines, filled
rectangles and multiple A4 pages.
"""
import zlib

A4 = (595.28, 841.89)
_AVG_WIDTH = {False: 0.50, True: 0.55}     # average glyph width in em, for wrapping


def _escape(text):
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return " ".join(f"{int(h[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


class PdfDocument:
    def __init__(self, title="Report", margin=48):
        self.title = title
        self.margin = margin
        self.width, self.height = A4
        self.pages = []
        self.new_page()

    # -- page management -------------------------------------------------
    def new_page(self):
        self.pages.append([])
        self.y = self.height - self.margin

    def ensure_space(self, needed):
        if self.y - needed < self.margin + 24:
            self.new_page()

    # -- drawing primitives ----------------------------------------------
    def text(self, x, y, s, size=10, bold=False, color="#1f2a1f"):
        font = "F2" if bold else "F1"
        self.pages[-1].append(
            b"BT /%s %.1f Tf %s rg %.2f %.2f Td (%s) Tj ET" % (
                font.encode(), size, _rgb(color).encode(), x, y, _escape(s)))

    def line(self, x1, y1, x2, y2, color="#c9cfc4", width=0.6):
        self.pages[-1].append(b"%s RG %.2f w %.2f %.2f m %.2f %.2f l S" % (
            _rgb(color).encode(), width, x1, y1, x2, y2))

    def rect(self, x, y, w, h, fill="#eef2ea"):
        self.pages[-1].append(b"%s rg %.2f %.2f %.2f %.2f re f" % (_rgb(fill).encode(), x, y, w, h))

    # -- flowing layout helpers ------------------------------------------
    @staticmethod
    def wrap(s, size, max_width, bold=False):
        max_chars = max(int(max_width / (size * _AVG_WIDTH[bold])), 10)
        lines, current = [], ""
        for word in s.split():
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def paragraph(self, s, size=10, bold=False, color="#1f2a1f", leading=1.45, indent=0, gap_after=6):
        width = self.width - 2 * self.margin - indent
        for ln in self.wrap(s, size, width, bold):
            self.ensure_space(size * leading)
            self.y -= size * leading
            self.text(self.margin + indent, self.y, ln, size, bold, color)
        self.y -= gap_after

    def heading(self, s, size=12):
        self.ensure_space(40)
        self.y -= 14
        self.paragraph(s, size=size, bold=True, color="#2f5d3a", gap_after=2)
        self.line(self.margin, self.y, self.width - self.margin, self.y)
        self.y -= 8

    def table(self, headers, rows, col_widths, size=9):
        x0 = self.margin
        row_h = size * 2.1
        self.ensure_space(row_h * 2)
        self.rect(x0, self.y - row_h, sum(col_widths), row_h, fill="#e7ece2")
        self._row(headers, col_widths, size, bold=True, row_h=row_h)
        for r in rows:
            wrapped = [self.wrap(str(c), size, w - 8) for c, w in zip(r, col_widths)]
            h = max(len(w) for w in wrapped) * size * 1.35 + size * 0.9
            self.ensure_space(h)
            top = self.y
            for i, (cell_lines, w) in enumerate(zip(wrapped, col_widths)):
                cx = x0 + sum(col_widths[:i]) + 4
                cy = top - size * 1.35
                for ln in cell_lines:
                    self.text(cx, cy, ln, size)
                    cy -= size * 1.35
            self.y = top - h
            self.line(x0, self.y, x0 + sum(col_widths), self.y, color="#dde2d8")
        self.y -= 6

    def _row(self, cells, col_widths, size, bold, row_h):
        x = self.margin
        for c, w in zip(cells, col_widths):
            self.text(x + 4, self.y - row_h + size * 0.75, str(c), size, bold)
            x += w
        self.y -= row_h

    # -- serialisation ----------------------------------------------------
    def output(self, footer=None):
        objects = []

        def add(body):
            objects.append(body)
            return len(objects)

        catalog = add(None)
        pages_id = add(None)
        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        page_ids = []
        total = len(self.pages)
        for n, ops in enumerate(self.pages, start=1):
            ops = list(ops)
            if footer:
                ops.append(b"BT /F1 8 Tf 0.45 0.5 0.45 rg %.2f 28 Td (%s) Tj ET" % (self.margin, _escape(footer)))
            ops.append(b"BT /F1 8 Tf 0.45 0.5 0.45 rg %.2f 28 Td (%s) Tj ET" % (
                self.width - self.margin - 40, _escape(f"Page {n} of {total}")))
            stream = zlib.compress(b"\n".join(ops))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream" % (len(stream), stream))
            page_ids.append(add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (
                    pages_id, self.width, self.height, content, font_regular, font_bold)))
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
        kids = b" ".join(b"%d 0 R" % p for p in page_ids)
        objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
        info = add(b"<< /Title (%s) /Producer (CropAdvisor) >>" % _escape(self.title))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, catalog, info, xref)
        return bytes(out)

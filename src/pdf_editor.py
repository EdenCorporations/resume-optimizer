"""
PdfEditor – Reads, modifies, and saves PDF files while preserving formatting.

Uses PyMuPDF (fitz) for surgical text replacement via redact-and-reinsert,
which preserves fonts, colors, layout, and images. Mirrors the ResumeEditor
interface for consistent usage in the pipeline.
"""

import io
import logging
import re
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)


class PdfEditor:
    """Read, analyze, and edit PDF files with formatting preservation."""

    def __init__(self, pdf_bytes: bytes):
        """
        Load a PDF for editing.

        Args:
            pdf_bytes: Raw bytes of the PDF file
        """
        self.pdf_bytes = pdf_bytes
        self.doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        logger.info("Loaded PDF: %d pages, %d bytes", len(self.doc), len(pdf_bytes))

    def extract_text(self) -> str:
        """
        Extract all text content from the PDF using pdfplumber (better structure).

        Returns:
            Full text content with pages separated by newlines
        """
        text_parts = []
        try:
            with pdfplumber.open(io.BytesIO(self.pdf_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text and isinstance(page_text, str) and page_text.strip():
                        text_parts.append(page_text.strip())
        except Exception as e:
            logger.warning("pdfplumber extraction failed, falling back to PyMuPDF: %s", e)
            # Fallback to PyMuPDF
            for page in self.doc:
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    text_parts.append(page_text.strip())

        return "\n".join(text_parts)

    def apply_suggestions(self, suggestions: list) -> dict:
        """
        Apply text replacement suggestions to the PDF.

        Uses PyMuPDF's redact-and-reinsert technique:
        1. Find the text location (rect + font properties)
        2. Redact (white-out) the original text
        3. Insert replacement text at the same position with matching style

        Args:
            suggestions: List of dicts with 'original_text' and 'replacement_text'

        Returns:
            Dict with counts of applied/failed and details
        """
        applied = 0
        failed = 0
        details = []

        for suggestion in suggestions:
            original = suggestion.get("original_text", "")
            replacement = suggestion.get("replacement_text", "")
            reason = suggestion.get("reason", "")

            if not original or not replacement:
                failed += 1
                details.append({"status": "skipped", "reason": "Empty text"})
                continue

            success = self._find_and_replace(original, replacement)
            if success:
                applied += 1
                details.append({
                    "status": "applied",
                    "original": original[:60] + "..." if len(original) > 60 else original,
                    "reason": reason,
                })
                logger.info("Applied PDF edit: %s...", original[:50])
            else:
                failed += 1
                details.append({
                    "status": "failed",
                    "original": original[:60] + "..." if len(original) > 60 else original,
                    "reason": "Text not found in PDF",
                })
                logger.warning("Not found in PDF: %s...", original[:50])

        return {"applied": applied, "failed": failed, "details": details}

    def _find_and_replace(self, old_text: str, new_text: str) -> bool:
        """
        Find text in the PDF and replace it in-place using redact-then-insert.

        Two-step approach for reliable text placement:
        1. Read span-level font/origin info *before* any mutation.
        2. Redact (white-out) the old text with an empty redaction annotation.
        3. Insert new text at the *exact* baseline origin using ``insert_text``.

        This avoids the unreliable ``add_redact_annot(text=...)`` parameter
        which places replacement text at wrong positions.

        Returns:
            True if replacement was made, False if text not found
        """
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]

            # Try exact search first
            text_instances = page.search_for(old_text)
            if not text_instances:
                # Try normalized whitespace matching
                normalized = re.sub(r'\s+', ' ', old_text).strip()
                text_instances = page.search_for(normalized)

            if not text_instances:
                continue

            # ── Step 1: Collect font info BEFORE redacting ──────────────
            # (Redaction destroys text, so we must capture metadata first)
            all_font_info = []
            for inst_rect in text_instances:
                info = self._get_font_info_at_rect(page, inst_rect)
                all_font_info.append(info)

            font_info = all_font_info[0] if all_font_info else {
                "font": "helv", "size": 11, "color": (0, 0, 0), "origin": None,
            }

            fontname = font_info.get("font", "helv")
            fontsize = font_info.get("size", 11)
            color = font_info.get("color", (0, 0, 0))
            origin = font_info.get("origin")  # fitz.Point or None
            fitz_fontname = self._map_fontname(fontname)

            # Group rects that belong to the same visual match
            # (search_for may split wrapped text into multiple rects)
            match_rects = [text_instances[0]]
            if len(text_instances) > 1:
                last_rect = text_instances[0]
                for r in text_instances[1:]:
                    if abs(r.y0 - last_rect.y1) < fontsize * 2:
                        match_rects.append(r)
                        last_rect = r
                    else:
                        break  # separate occurrence, stop

            # ── Step 2: Redact – remove old text without painting a fill ──
            # Using fill=False avoids leaving a visible white rectangle when
            # the replacement text is shorter than the original.
            for rect in match_rects:
                page.add_redact_annot(
                    rect,
                    text="",
                    fill=False,
                    cross_out=False,
                )

            page.apply_redactions(images=0)  # 0 = don't touch images

            # ── Step 3: Insert new text at exact original baseline ──────
            if origin is None:
                # Fallback: approximate baseline from rect top + font size
                first_rect = match_rects[0]
                origin = fitz.Point(first_rect.x0, first_rect.y0 + fontsize)

            # Calculate available width from origin to right page margin.
            # Mirror the left margin (origin.x) to the right side, with a
            # minimum of 36 pt (0.5 in) so text never touches the edge.
            page_rect = page.rect
            left_margin = origin.x - page_rect.x0
            right_margin_inset = max(left_margin, 36)
            avail_width = page_rect.x1 - origin.x - right_margin_inset

            # Measure how wide the new text would be as a single line
            try:
                text_length = fitz.get_text_length(
                    new_text, fontname=fitz_fontname, fontsize=fontsize
                )
            except Exception:
                text_length = fitz.get_text_length(
                    new_text, fontname="helv", fontsize=fontsize
                )
                fitz_fontname = "helv"

            needs_wrap = text_length > avail_width and avail_width > 0

            if needs_wrap:
                # Use insert_textbox for automatic word-wrapping.
                # Build a rect from origin that extends to the right margin
                # and far enough down to accommodate wrapped lines.
                ascender = fontsize * 0.9   # approximate ascender height
                tb_rect = fitz.Rect(
                    origin.x,
                    origin.y - ascender,            # top = baseline − ascender
                    origin.x + avail_width,
                    page_rect.y1 - 36,              # extend to bottom margin
                )
                try:
                    page.insert_textbox(
                        tb_rect,
                        new_text,
                        fontname=fitz_fontname,
                        fontsize=fontsize,
                        color=color,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
                except Exception:
                    page.insert_textbox(
                        tb_rect,
                        new_text,
                        fontname="helv",
                        fontsize=fontsize,
                        color=color,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
            else:
                # Single line fits — use insert_text at exact baseline
                try:
                    page.insert_text(
                        origin,
                        new_text,
                        fontname=fitz_fontname,
                        fontsize=fontsize,
                        color=color,
                    )
                except Exception:
                    page.insert_text(
                        origin,
                        new_text,
                        fontname="helv",
                        fontsize=fontsize,
                        color=color,
                    )

            logger.info(
                "Replaced text on page %d (%d rects, font=%s, size=%.1f)",
                page_num + 1, len(match_rects), fitz_fontname, fontsize,
            )
            return True

        return False

    def _get_bg_color(self, page, rect: fitz.Rect) -> tuple:
        """
        Try to detect the background color behind a text rect.
        Falls back to white (1,1,1) for most resumes.
        """
        try:
            # Sample a point just outside the text rect for background
            # Check if there are any filled rects/drawings behind the text
            drawings = page.get_drawings()
            for d in drawings:
                if d.get("fill") and d.get("rect"):
                    d_rect = fitz.Rect(d["rect"])
                    if d_rect.contains(rect):
                        fill = d["fill"]
                        if isinstance(fill, (list, tuple)) and len(fill) >= 3:
                            return tuple(fill[:3])
        except Exception:
            pass
        return (1, 1, 1)  # white default

    def _get_font_info_at_rect(self, page, rect: fitz.Rect) -> dict:
        """
        Extract font name, size, color, and baseline origin from text spans
        at the given rect.

        Uses page.get_text("dict") to get detailed span information.
        The ``origin`` value is the text baseline point — the exact coordinate
        that ``page.insert_text()`` needs for correct placement.
        """
        default = {"font": "helv", "size": 11, "color": (0, 0, 0), "origin": None}

        try:
            text_dict = page.get_text("dict", clip=rect)
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font = span.get("font", "helv")
                        size = span.get("size", 11)
                        origin = span.get("origin")  # (x, y_baseline)
                        # Color is an int (sRGB), convert to (r,g,b) tuple 0-1
                        color_int = span.get("color", 0)
                        r = ((color_int >> 16) & 0xFF) / 255.0
                        g = ((color_int >> 8) & 0xFF) / 255.0
                        b = (color_int & 0xFF) / 255.0
                        return {
                            "font": font,
                            "size": size,
                            "color": (r, g, b),
                            "origin": fitz.Point(origin) if origin else None,
                        }
        except Exception as e:
            logger.warning("Failed to extract font info: %s", e)

        return default

    def _map_fontname(self, pdf_fontname: str) -> str:
        """
        Map common PDF font names to PyMuPDF built-in font names.

        PyMuPDF supports: helv (Helvetica), tiro (Times-Roman), cour (Courier),
        and their bold/italic variants.
        """
        name_lower = pdf_fontname.lower()

        if any(k in name_lower for k in ("arial", "helvetica", "helv", "sans")):
            if "bold" in name_lower and "italic" in name_lower:
                return "hebi"
            elif "bold" in name_lower:
                return "hebo"
            elif "italic" in name_lower or "oblique" in name_lower:
                return "heit"
            return "helv"

        if any(k in name_lower for k in ("times", "tiro", "roman", "serif")):
            if "bold" in name_lower and "italic" in name_lower:
                return "tibi"
            elif "bold" in name_lower:
                return "tibo"
            elif "italic" in name_lower:
                return "tiit"
            return "tiro"

        if any(k in name_lower for k in ("courier", "cour", "mono")):
            if "bold" in name_lower and "italic" in name_lower:
                return "cobi"
            elif "bold" in name_lower:
                return "cobo"
            elif "italic" in name_lower or "oblique" in name_lower:
                return "coit"
            return "cour"

        if "bold" in name_lower:
            return "hebo"

        # Default to Helvetica
        return "helv"

    def _insert_multiline_text(
        self, page, rect: fitz.Rect, text: str,
        fontname: str, fontsize: float, color: tuple
    ):
        """Insert multi-line or long text that needs to wrap within the rect area."""
        try:
            # Use insert_textbox for automatic text wrapping
            page.insert_textbox(
                rect,
                text,
                fontname=fontname,
                fontsize=fontsize,
                color=color,
                align=fitz.TEXT_ALIGN_LEFT,
            )
        except Exception as e:
            logger.warning("insert_textbox failed (%s), falling back to simple insert", e)
            point = fitz.Point(rect.x0, rect.y0 + fontsize)
            try:
                page.insert_text(
                    point, text,
                    fontname=fontname, fontsize=fontsize, color=color,
                )
            except Exception:
                page.insert_text(
                    point, text,
                    fontname="helv", fontsize=fontsize, color=color,
                )

    def save_to_bytesio(self) -> io.BytesIO:
        """
        Save the modified PDF to an in-memory BytesIO buffer.

        Returns:
            BytesIO buffer containing the PDF
        """
        buffer = io.BytesIO()
        self.doc.save(buffer)
        buffer.seek(0)
        logger.info("Saved optimized PDF to BytesIO")
        return buffer

    def close(self):
        """Close the underlying PDF document."""
        if self.doc:
            self.doc.close()

    def __del__(self):
        """Ensure document is closed on garbage collection."""
        try:
            self.close()
        except Exception:
            pass

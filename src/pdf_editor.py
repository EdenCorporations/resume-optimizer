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
        Find text in the PDF and replace it in-place using redaction.

        Uses PyMuPDF's atomic redact-with-replacement: the redaction annotation
        itself carries the replacement text, so removing old content and inserting
        new content happen in a single apply_redactions() call — no gap, no blanks.

        Returns:
            True if replacement was made, False if text not found
        """
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]

            # Try exact search first
            text_instances = page.search_for(old_text)
            search_text = old_text
            if not text_instances:
                # Try normalized whitespace matching
                search_text = re.sub(r'\s+', ' ', old_text).strip()
                text_instances = page.search_for(search_text)

            if not text_instances:
                continue

            # Collect font info from ALL matching rects BEFORE redacting
            # (redacting destroys the text, so we must read first)
            all_font_info = []
            for inst_rect in text_instances:
                info = self._get_font_info_at_rect(page, inst_rect)
                all_font_info.append(info)

            # Use the first match's font info as the canonical style
            font_info = all_font_info[0] if all_font_info else {
                "font": "helv", "size": 11, "color": (0, 0, 0)
            }

            fontname = font_info.get("font", "helv")
            fontsize = font_info.get("size", 11)
            color = font_info.get("color", (0, 0, 0))
            fitz_fontname = self._map_fontname(fontname)

            # Detect page background color for fill (most resumes are white)
            bg_color = self._get_bg_color(page, text_instances[0])

            # search_for may return multiple rects for the SAME text occurrence
            # (one rect per line if the text wraps). We need to figure out which
            # rects belong to our single match vs. truly separate occurrences.
            # Strategy: if rects are vertically adjacent (within 2× font height),
            # they're part of the same wrapped text block.
            match_rects = [text_instances[0]]
            if len(text_instances) > 1:
                last_rect = text_instances[0]
                for r in text_instances[1:]:
                    if abs(r.y0 - last_rect.y1) < fontsize * 2:
                        match_rects.append(r)
                        last_rect = r
                    else:
                        break  # separate occurrence, stop

            # Apply redaction to each rect in the match.
            # Put replacement text ONLY on the first rect's annotation.
            for i, rect in enumerate(match_rects):
                if i == 0:
                    # First rect: carry the replacement text
                    try:
                        page.add_redact_annot(
                            rect,
                            text=new_text,
                            fontname=fitz_fontname,
                            fontsize=0,  # 0 = auto-fit to rect height
                            text_color=color,
                            fill=bg_color,
                            cross_out=False,
                        )
                    except Exception:
                        # Fallback: use helv if the mapped font fails
                        page.add_redact_annot(
                            rect,
                            text=new_text,
                            fontname="helv",
                            fontsize=0,
                            text_color=color,
                            fill=bg_color,
                            cross_out=False,
                        )
                else:
                    # Subsequent rects (wrapped lines): just clear them
                    page.add_redact_annot(
                        rect,
                        text="",
                        fill=bg_color,
                        cross_out=False,
                    )

            # Apply all redactions atomically — this removes old text and
            # places replacement text in one operation
            page.apply_redactions(images=0)  # 0 = don't touch images

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
        Extract font name, size, and color from text spans at the given rect.

        Uses page.get_text("dict") to get detailed span information.
        """
        default = {"font": "helv", "size": 11, "color": (0, 0, 0)}

        try:
            text_dict = page.get_text("dict", clip=rect)
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font = span.get("font", "helv")
                        size = span.get("size", 11)
                        # Color is an int (sRGB), convert to (r,g,b) tuple 0-1
                        color_int = span.get("color", 0)
                        r = ((color_int >> 16) & 0xFF) / 255.0
                        g = ((color_int >> 8) & 0xFF) / 255.0
                        b = (color_int & 0xFF) / 255.0
                        return {"font": font, "size": size, "color": (r, g, b)}
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

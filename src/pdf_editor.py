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

        Strategy:
        1. Search each page for the old text
        2. Get font properties from the text spans at that location
        3. Redact the area (removes text, fills with page background)
        4. Insert new text with the same font properties

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

            # Use the first match
            rect = text_instances[0]

            # If multiple rects (multi-line), union them
            if len(text_instances) > 1:
                # Check if they're close together (same text block)
                union_rect = fitz.Rect(rect)
                for r in text_instances[1:]:
                    # Only union nearby rects (within ~50 pts vertically)
                    if abs(r.y0 - rect.y0) < 50:
                        union_rect |= r
                rect = union_rect

            # Get font properties from the text at this location
            font_info = self._get_font_info_at_rect(page, rect)

            # Apply redaction to remove old text
            page.add_redact_annot(rect, text="", fill=(1, 1, 1))  # white fill
            page.apply_redactions(images=0)  # 0 = PDF_REDACT_IMAGE_NONE

            # Insert replacement text with matching font properties
            fontname = font_info.get("font", "helv")
            fontsize = font_info.get("size", 11)
            color = font_info.get("color", (0, 0, 0))

            # Map common PDF font names to fitz built-in names
            fitz_fontname = self._map_fontname(fontname)

            # Calculate insertion point (top-left of the rect + baseline offset)
            insert_point = fitz.Point(rect.x0, rect.y0 + fontsize)

            # For multi-line text, use text writer for better control
            if "\n" in new_text or len(new_text) > 80:
                self._insert_multiline_text(
                    page, rect, new_text, fitz_fontname, fontsize, color
                )
            else:
                try:
                    page.insert_text(
                        insert_point,
                        new_text,
                        fontname=fitz_fontname,
                        fontsize=fontsize,
                        color=color,
                    )
                except Exception as e:
                    logger.warning("insert_text failed (%s), using helv fallback", e)
                    page.insert_text(
                        insert_point,
                        new_text,
                        fontname="helv",
                        fontsize=fontsize,
                        color=color,
                    )

            return True

        return False

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

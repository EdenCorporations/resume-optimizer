"""
PDFEditor – Reads, modifies, and saves .pdf files while attempting to preserve
original typography and placement.

Uses PyMuPDF (fitz) to search for text bounding boxes and replace them via 
redaction annotations (which blank out the old text and insert new text).
"""

import io
import logging
import re
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

logger = logging.getLogger(__name__)


class PDFEditor:
    """Read, analyze, and edit .pdf files with text replacement."""

    def __init__(self, pdf_bytes: bytes):
        """
        Load a .pdf file for editing from bytes.
        """
        if fitz is None:
            raise ImportError("PyMuPDF is required for PDF editing. Install it with: pip install PyMuPDF")

        self.document = fitz.open(stream=pdf_bytes, filetype="pdf")
        logger.info("Loaded PDF document for editing (%d pages)", len(self.document))

    def apply_suggestions(self, suggestions: list) -> dict:
        """
        Apply a list of text replacement suggestions to the document.

        Args:
            suggestions: List of dicts with 'original_text' and 'replacement_text'

        Returns:
            Dict with counts of applied and failed replacements
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
                    "original": original[:60] + "...",
                    "reason": reason,
                })
                logger.info("Applied to PDF: %s...", original[:50])
            else:
                failed += 1
                details.append({
                    "status": "failed",
                    "original": original[:60] + "...",
                    "reason": "Text not found in document",
                })
                logger.warning("Not found in PDF: %s...", original[:50])

        return {"applied": applied, "failed": failed, "details": details}

    def _find_and_replace(self, old_text: str, new_text: str) -> bool:
        """
        Search for old_text across all pages and replace it with new_text.
        Returns True if at least one replacement was made.
        """
        made_replacement = False
        
        for page in self.document:
            # PyMuPDF search_for returns a list of Rect objects where the text is found
            # It handles multiline and whitespace variations fairly well internally.
            rects = page.search_for(old_text)
            
            if rects:
                for rect in rects:
                    # formatting metadata
                    fontname = "helv"
                    fontsize = 11
                    color = (0, 0, 0)
                    
                    span = self._get_text_formatting(page, rect)
                    if span:
                        orig_font = span.get("font", "").lower()
                        if "bold" in orig_font:
                            fontname = "hebo"  # Helvetica-Bold
                        elif "times" in orig_font:
                            fontname = "tiro"  # Times-Roman
                        
                        fontsize = span.get("size", 11)
                        color = self._int_to_rgb(span.get("color", 0))
                    
                    # Add a redation annotation (white fill, original colored text)
                    page.add_redact_annot(
                        rect, 
                        text=new_text, 
                        fontname=fontname,
                        fontsize=fontsize,
                        fill=(1, 1, 1),      # background color (white)
                        text_color=color,    # font color
                        align=0              # 0=left, 1=center, 2=right
                    )
                
                # Apply the redactions for the page
                page.apply_redactions()
                made_replacement = True

        return made_replacement

    def _get_text_formatting(self, page, rect) -> Optional[dict]:
        """
        Attempt to find the exact text span overlapping with the given rect 
        to extract font face, size, and color.
        """
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        span_rect = fitz.Rect(s["bbox"])
                        # If the span vertically aligns with the search rect and overlaps horizontally
                        if abs(span_rect.y0 - rect.y0) < 5 and (span_rect.x0 <= rect.x1 and span_rect.x1 >= rect.x0):
                            return s
        return None

    def _int_to_rgb(self, color_int) -> tuple[float, float, float]:
        """Convert PyMuPDF color int to (r, g, b) floats [0.0 - 1.0]"""
        if color_int is None or not isinstance(color_int, int):
            return (0, 0, 0)
        b = (color_int & 255) / 255.0
        g = ((color_int >> 8) & 255) / 255.0
        r = ((color_int >> 16) & 255) / 255.0
        return (r, g, b)

    def save_to_bytes(self) -> bytes:
        """
        Return the modified PDF as a bytes object.
        """
        return self.document.tobytes()

    def save_to_bytesio(self) -> io.BytesIO:
        """
        Return the modified PDF as a BytesIO object (for blob storage).
        """
        return io.BytesIO(self.save_to_bytes())


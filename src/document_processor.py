"""
DocumentProcessor – Unified ingestion pipeline for PDF and DOCX files.

Routes uploaded files through the appropriate extraction path, handles
embedded image detection, headshot classification, OCR, and outputs
a clean UTF-8 text string ready for the LLM analyzer chain.
"""

import io
import logging
import zipfile
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of document processing — everything downstream consumers need."""

    text: str = ""
    file_type: str = "docx"  # "pdf" or "docx"
    has_images: bool = False
    image_heavy: bool = False
    process_notes: list = field(default_factory=list)
    headshot_data: list = field(default_factory=list)  # [{bytes, mime, location}]
    original_file_bytes: bytes = b""
    auto_apply_override: Optional[bool] = None  # None = no override


class DocumentProcessor:
    """
    Central coordinator for document ingestion.

    Accepts PDF or DOCX bytes, extracts text (native + OCR),
    classifies embedded images, and returns a ProcessingResult.
    """

    def __init__(self, openrouter_api_key: str = "", openrouter_model: str = ""):
        from src.vision_processor import VisionProcessor

        self.vision = VisionProcessor(
            api_key=openrouter_api_key,
            model=openrouter_model or "nvidia/nemotron-nano-12b-v2-vl:free",
        )

    def process(self, file_bytes: bytes, filename: str) -> ProcessingResult:
        """
        Process an uploaded file and return extracted text + metadata.

        Args:
            file_bytes: Raw bytes of the uploaded file
            filename: Original filename (used to detect extension)

        Returns:
            ProcessingResult with text, flags, and notes
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        result = ProcessingResult(original_file_bytes=file_bytes, file_type=ext)

        if ext == "pdf":
            self._process_pdf(file_bytes, result)
        elif ext == "docx":
            self._process_docx(file_bytes, result)
        else:
            raise ValueError(f"Unsupported file type: .{ext}")

        # Final check: if text is still too short, flag it
        if len(result.text.strip()) < 50:
            result.process_notes.append(
                "Very little text could be extracted from your document. "
                "Please ensure it contains readable text content."
            )

        return result

    # ------------------------------------------------------------------ #
    #  PDF Processing
    # ------------------------------------------------------------------ #

    def _process_pdf(self, file_bytes: bytes, result: ProcessingResult):
        """Extract text and images from a PDF."""
        import pdfplumber
        import fitz  # PyMuPDF

        # --- Step 1: Extract native text via pdfplumber (better structure) ---
        native_text_parts = []
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        native_text_parts.append(page_text)
        except Exception as e:
            logger.warning("pdfplumber text extraction failed: %s", e)

        native_text = "\n".join(native_text_parts)
        logger.info("PDF native text: %d characters", len(native_text))

        # --- Step 2: Extract images via PyMuPDF ---
        images_data = []
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images(full=True)
                for img_idx, img_info in enumerate(image_list):
                    xref = img_info[0]
                    try:
                        extracted = doc.extract_image(xref)
                        if extracted and extracted.get("image"):
                            img_bytes = extracted["image"]
                            ext = extracted.get("ext", "png")
                            mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                            # Skip tiny images (icons/bullets) — less than 5KB
                            if len(img_bytes) > 5000:
                                images_data.append({
                                    "bytes": img_bytes,
                                    "mime": mime,
                                    "page": page_num,
                                    "index": img_idx,
                                })
                    except Exception as e:
                        logger.warning("Failed to extract image xref=%d: %s", xref, e)
            doc.close()
        except Exception as e:
            logger.warning("PyMuPDF image extraction failed: %s", e)

        if images_data:
            result.has_images = True
            logger.info("Found %d significant images in PDF", len(images_data))

        # --- Step 3: Classify images and OCR content images ---
        ocr_texts = []
        if images_data:
            ocr_texts = self._classify_and_ocr_images(images_data, result)

        # --- Step 4: Combine text ---
        all_text_parts = []
        if native_text.strip():
            all_text_parts.append(native_text)
        if ocr_texts:
            all_text_parts.append("\n".join(ocr_texts))

        # If native text is minimal but we got OCR text, the doc is image-heavy
        if len(native_text.strip()) < 100 and ocr_texts:
            result.image_heavy = True
            result.process_notes.append(
                "Your resume was image-heavy. We have rebuilt a clean, "
                "ATS-compliant version for you."
            )
            result.auto_apply_override = False
        elif images_data and len(ocr_texts) > len(images_data) * 0.5:
            # More than half the images contained text
            result.image_heavy = True
            result.process_notes.append(
                "Your resume contained significant image-based content. "
                "We extracted the text for ATS compatibility."
            )

        result.text = "\n".join(all_text_parts)

    # ------------------------------------------------------------------ #
    #  DOCX Processing
    # ------------------------------------------------------------------ #

    def _process_docx(self, file_bytes: bytes, result: ProcessingResult):
        """Extract text and inspect images from a DOCX."""
        from docx import Document

        # --- Step 1: Extract text via python-docx ---
        doc = Document(io.BytesIO(file_bytes))
        text_parts = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                text_parts.append(text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = para.text.strip()
                        if text:
                            text_parts.append(text)

        native_text = "\n".join(text_parts)
        logger.info("DOCX native text: %d characters", len(native_text))

        # --- Step 2: Extract embedded images from the DOCX zip ---
        images_data = []
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                for name in zf.namelist():
                    # Images are in word/media/
                    if name.startswith("word/media/"):
                        ext = name.rsplit(".", 1)[-1].lower()
                        if ext in ("png", "jpg", "jpeg", "bmp", "tiff", "gif"):
                            img_bytes = zf.read(name)
                            # Skip tiny images (icons/bullets)
                            if len(img_bytes) > 5000:
                                mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                                images_data.append({
                                    "bytes": img_bytes,
                                    "mime": mime,
                                    "name": name,
                                })
        except Exception as e:
            logger.warning("DOCX image extraction failed: %s", e)

        if images_data:
            result.has_images = True
            logger.info("Found %d significant images in DOCX", len(images_data))

        # --- Step 3: Classify images and OCR content images ---
        ocr_texts = []
        if images_data:
            ocr_texts = self._classify_and_ocr_images(images_data, result)

        # --- Step 4: Combine text ---
        all_text_parts = []
        if native_text.strip():
            all_text_parts.append(native_text)
        if ocr_texts:
            all_text_parts.append("\n".join(ocr_texts))

        if len(native_text.strip()) < 100 and ocr_texts:
            result.image_heavy = True
            result.process_notes.append(
                "Your resume was image-heavy. We have rebuilt a clean, "
                "ATS-compliant version for you."
            )
            result.auto_apply_override = False
        elif images_data and len(ocr_texts) > len(images_data) * 0.5:
            result.image_heavy = True
            result.process_notes.append(
                "Your resume contained significant image-based content. "
                "We extracted the text for ATS compatibility."
            )

        result.text = "\n".join(all_text_parts)

    # ------------------------------------------------------------------ #
    #  Image Classification & OCR
    # ------------------------------------------------------------------ #

    def _classify_and_ocr_images(self, images_data: list, result: ProcessingResult) -> list:
        """
        Classify each image and OCR the ones containing resume content.

        Args:
            images_data: List of {"bytes", "mime", ...} dicts
            result: ProcessingResult to update with headshot info

        Returns:
            List of OCR'd text strings from content images
        """
        ocr_texts = []

        for img in images_data:
            # Step A: Classify
            classification = self.vision.classify_image(
                img["bytes"], img.get("mime", "image/png")
            )
            img_type = classification["type"]

            if img_type == "headshot":
                # Keep headshot data for preservation during editing
                result.headshot_data.append({
                    "bytes": img["bytes"],
                    "mime": img.get("mime", "image/png"),
                    "location": img.get("name") or f"page_{img.get('page', 0)}",
                })
                logger.info("Image classified as headshot — preserving as-is")

            elif img_type == "resume_content":
                # OCR the text out of the image
                text = self.vision.ocr_image(
                    img["bytes"], img.get("mime", "image/png")
                )
                if text.strip():
                    ocr_texts.append(text)
                    logger.info("OCR extracted %d chars from content image", len(text))

            else:
                # "other" — decorative, skip
                logger.info("Image classified as 'other' — skipping")

        return ocr_texts

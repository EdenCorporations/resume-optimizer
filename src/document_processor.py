"""
DocumentProcessor – Unified ingestion gateway for .docx and .pdf resumes.

Handles:
- Native text extraction from PDF and DOCX
- Embedded image extraction from both formats
- OCR via Tesseract (local) or OpenRouter Vision LLM (Vercel/cloud)
- Image classification (headshot vs resume content) via OpenRouter Vision LLM
- Compliance flagging (auto_apply override for image-heavy resumes)

Output: raw UTF-8 text string ready for the LLMAnalyzer chain.
"""

import base64
import io
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from typing import Optional

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Lazy imports — these are optional heavy deps that might not be installed
# ---------------------------------------------------------------------------

_fitz = None
_pytesseract = None
_tesseract_checked = False


def _get_fitz():
    """Lazy-import PyMuPDF."""
    global _fitz
    if _fitz is None:
        try:
            import fitz  # PyMuPDF
            _fitz = fitz
        except ImportError:
            raise ImportError(
                "PyMuPDF is required for PDF processing. "
                "Install it with: pip install PyMuPDF"
            )
    return _fitz


def _get_tesseract():
    """
    Lazy-import pytesseract. Returns None if not available (non-fatal).
    This allows the system to fall back to Vision LLM OCR on Vercel.
    """
    global _pytesseract, _tesseract_checked
    if _tesseract_checked:
        return _pytesseract
    _tesseract_checked = True
    try:
        import pytesseract
        pytesseract.get_tesseract_version()  # verify binary exists
        _pytesseract = pytesseract
        logger.info("Tesseract OCR available")
    except Exception as e:
        _pytesseract = None
        logger.info("Tesseract OCR not available (%s) — will use Vision LLM for OCR", e)
    return _pytesseract


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

# Minimum average characters per page to consider a PDF as "text-native"
MIN_CHARS_PER_PAGE = 80

# OpenRouter config for headshot classification + OCR
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_VISION_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"

# Image size thresholds
MIN_IMAGE_AREA = 2500          # ignore tiny thumbnails (< 50x50)
MAX_IMAGE_DIM_FOR_OCR = 4000   # downscale huge images before OCR

HEADSHOT_CLASSIFICATION_PROMPT = (
    "You are an image classifier for a resume processing system. "
    "Look at the image and determine if it is a HEADSHOT (portrait photo of a person, "
    "like a professional headshot, ID photo, or selfie) or RESUME_CONTENT "
    "(text, tables, charts, diagrams, or any resume section rendered as an image). "
    "Respond with ONLY one word: either HEADSHOT or RESUME_CONTENT. "
    "Nothing else."
)

VISION_OCR_PROMPT = (
    "You are an OCR engine for a resume processing system. "
    "Extract ALL text from this image exactly as it appears. "
    "Preserve the original formatting, line breaks, and structure as much as possible. "
    "Output ONLY the extracted text, nothing else. No commentary, no explanations."
)


# ---------------------------------------------------------------------------
#  Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ProcessingResult:
    """Result of document processing — the contract between ingestion and LLM analysis."""
    text: str                                      # raw UTF-8 resume text
    source_type: str = "unknown"                   # pdf_native, pdf_ocr, docx_text, docx_ocr
    images_found: int = 0                          # count of embedded images
    headshot_detected: bool = False                 # whether a headshot was found & preserved
    auto_apply_override: Optional[bool] = None     # False = force off, None = no override
    process_notes: list = field(default_factory=list)  # human-readable notes


@dataclass
class ClassifiedImage:
    """An image extracted from a document with its classification."""
    image: Image.Image
    classification: str = "unknown"   # "headshot" or "content"
    ocr_text: str = ""


# ---------------------------------------------------------------------------
#  Main Processor
# ---------------------------------------------------------------------------

class DocumentProcessor:
    """
    Unified document ingestion gateway.

    Usage:
        processor = DocumentProcessor(openrouter_api_key="sk-...")
        result = processor.process(file_bytes, "resume.pdf")
        resume_text = result.text  # → feed into LLMAnalyzer

    OCR strategy (auto-selected):
        - Local dev: uses Tesseract if installed (fast, free, offline)
        - Vercel/cloud: uses OpenRouter Vision LLM (no binary needed)
    """

    def __init__(self, openrouter_api_key: str = ""):
        self.openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def process(self, file_bytes: bytes, filename: str) -> ProcessingResult:
        """
        Process an uploaded document and return standardised text output.

        Args:
            file_bytes: raw bytes of the uploaded file
            filename:   original filename (used to detect extension)

        Returns:
            ProcessingResult with extracted text and metadata
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "pdf":
            return self._process_pdf(file_bytes)
        elif ext == "docx":
            return self._process_docx(file_bytes)
        else:
            raise ValueError(f"Unsupported file type: .{ext}")

    # ------------------------------------------------------------------ #
    #  PDF Processing
    # ------------------------------------------------------------------ #

    def _process_pdf(self, file_bytes: bytes) -> ProcessingResult:
        """
        Process a PDF file:
        1. Attempt native text extraction.
        2. If text is sparse, fall back to page-image OCR.
        3. Scan for embedded images, classify them.
        """
        fitz = _get_fitz()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        result = ProcessingResult(text="", source_type="pdf_native")

        # --- Step 1: Native text extraction ---
        page_texts = []
        for page in doc:
            page_texts.append(page.get_text("text"))
        native_text = "\n".join(page_texts).strip()

        total_chars = len(native_text.replace(" ", "").replace("\n", ""))
        avg_chars = total_chars / max(len(doc), 1)
        logger.info(
            "PDF native text: %d chars, %d pages, avg %.0f chars/page",
            total_chars, len(doc), avg_chars,
        )

        # --- Step 2: Extract & classify embedded images ---
        all_images = self._extract_images_from_pdf(doc)
        result.images_found = len(all_images)

        classified = self._classify_images(all_images) if all_images else []
        headshots = [c for c in classified if c.classification == "headshot"]
        content_images = [c for c in classified if c.classification == "content"]

        if headshots:
            result.headshot_detected = True
            logger.info("Headshot detected in PDF — preserving")

        # --- Step 3: Decide text path ---
        if avg_chars >= MIN_CHARS_PER_PAGE:
            # Good native text — use it
            result.text = native_text
            result.source_type = "pdf_native"
            logger.info("Using native PDF text extraction")
        else:
            # Sparse text — OCR the full pages
            logger.info("Sparse PDF text (avg %.0f chars/page), falling back to OCR", avg_chars)
            result.source_type = "pdf_ocr"
            ocr_texts = []
            for page_num, page in enumerate(doc):
                try:
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    page_ocr = self._ocr_image(img)
                    if page_ocr.strip():
                        ocr_texts.append(page_ocr)
                        logger.info("OCR page %d: %d chars", page_num + 1, len(page_ocr))
                except Exception as e:
                    logger.warning("OCR failed on PDF page %d: %s", page_num + 1, e)
            result.text = "\n\n".join(ocr_texts)

        # --- Step 4: Merge OCR text from content images ---
        if content_images:
            extra_ocr = []
            for ci in content_images:
                if ci.ocr_text.strip():
                    extra_ocr.append(ci.ocr_text)
            if extra_ocr and result.source_type == "pdf_native":
                # Append OCR'd image text to native text
                result.text += "\n\n" + "\n\n".join(extra_ocr)
                logger.info("Appended OCR text from %d content images", len(extra_ocr))

        # --- Step 5: Compliance ---
        if content_images or result.source_type == "pdf_ocr":
            result.auto_apply_override = False
            result.process_notes.append(
                "Your resume was image-heavy. We have rebuilt a clean, "
                "ATS-compliant version for you."
            )

        doc.close()
        return result

    # ------------------------------------------------------------------ #
    #  DOCX Processing
    # ------------------------------------------------------------------ #

    def _process_docx(self, file_bytes: bytes) -> ProcessingResult:
        """
        Process a DOCX file:
        1. Extract text via python-docx.
        2. Scan word/media/ for embedded images.
        3. Classify images and OCR content images.
        """
        from docx import Document

        result = ProcessingResult(text="", source_type="docx_text")

        # --- Step 1: Text extraction ---
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        # Also get table text
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        text = para.text.strip()
                        if text:
                            paragraphs.append(text)
        result.text = "\n".join(paragraphs)

        # --- Step 2: Scan for embedded images ---
        images = self._extract_images_from_docx(file_bytes)
        result.images_found = len(images)

        if not images:
            logger.info("DOCX has no embedded images — pure text path")
            return result

        logger.info("DOCX has %d embedded images — classifying", len(images))

        # --- Step 3: Classify images ---
        classified = self._classify_images(images)
        headshots = [c for c in classified if c.classification == "headshot"]
        content_images = [c for c in classified if c.classification == "content"]

        if headshots:
            result.headshot_detected = True
            logger.info("Headshot detected in DOCX — keeping as-is")

        # --- Step 4: OCR content images & merge ---
        if content_images:
            result.source_type = "docx_ocr"
            extra_ocr = []
            for ci in content_images:
                if ci.ocr_text.strip():
                    extra_ocr.append(ci.ocr_text)
            if extra_ocr:
                result.text += "\n\n" + "\n\n".join(extra_ocr)
                logger.info("Appended OCR text from %d content images", len(extra_ocr))

            result.auto_apply_override = False
            result.process_notes.append(
                "Your resume was image-heavy. We have rebuilt a clean, "
                "ATS-compliant version for you."
            )

        # If native text was too short, we may need full OCR
        if len(result.text.strip()) < 50 and images:
            logger.info("DOCX has minimal text — running full OCR on all images")
            result.source_type = "docx_ocr"
            all_ocr = []
            for img in images:
                ocr_text = self._ocr_image(img)
                if ocr_text.strip():
                    all_ocr.append(ocr_text)
            if all_ocr:
                result.text = "\n\n".join(all_ocr)
            result.auto_apply_override = False
            result.process_notes.append(
                "Your resume was image-heavy. We have rebuilt a clean, "
                "ATS-compliant version for you."
            )

        return result

    # ------------------------------------------------------------------ #
    #  Image Extraction
    # ------------------------------------------------------------------ #

    def _extract_images_from_pdf(self, doc) -> list:
        """Extract raster images from all PDF pages using PyMuPDF."""
        fitz = _get_fitz()
        images = []

        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

                    # Ignore tiny images (icons, bullets, etc.)
                    w, h = pil_img.size
                    if w * h < MIN_IMAGE_AREA:
                        continue

                    images.append(pil_img)
                    logger.debug(
                        "Extracted image from PDF page %d, xref %d: %dx%d",
                        page_num + 1, xref, w, h,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to extract image xref %d from PDF page %d: %s",
                        xref, page_num + 1, e,
                    )

        logger.info("Extracted %d images from PDF", len(images))
        return images

    def _extract_images_from_docx(self, file_bytes: bytes) -> list:
        """Extract images from the word/media/ directory inside the .docx ZIP."""
        images = []
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                media_files = [
                    name for name in zf.namelist()
                    if name.startswith("word/media/")
                    and not name.endswith("/")
                ]
                for media_path in media_files:
                    try:
                        img_data = zf.read(media_path)
                        pil_img = Image.open(io.BytesIO(img_data)).convert("RGB")

                        w, h = pil_img.size
                        if w * h < MIN_IMAGE_AREA:
                            continue

                        images.append(pil_img)
                        logger.debug("Extracted image from DOCX: %s (%dx%d)", media_path, w, h)
                    except Exception as e:
                        logger.warning("Could not open DOCX media %s: %s", media_path, e)
        except zipfile.BadZipFile:
            logger.warning("Could not read DOCX as ZIP for image extraction")

        logger.info("Extracted %d images from DOCX", len(images))
        return images

    # ------------------------------------------------------------------ #
    #  Image Classification (OpenRouter Vision LLM)
    # ------------------------------------------------------------------ #

    def _classify_images(self, images: list) -> list:
        """
        Classify a list of PIL Images as 'headshot' or 'content'.
        Uses OpenRouter Vision LLM when API key is available, falls back to heuristics.
        Also runs OCR on content images.
        """
        classified = []
        for idx, img in enumerate(images):
            classification = self._classify_single_image(img, idx)
            ci = ClassifiedImage(image=img, classification=classification)

            # OCR content images
            if classification == "content":
                try:
                    ci.ocr_text = self._ocr_image(img)
                except Exception as e:
                    logger.warning("OCR failed on content image %d: %s", idx, e)

            classified.append(ci)

        headshot_count = sum(1 for c in classified if c.classification == "headshot")
        content_count = sum(1 for c in classified if c.classification == "content")
        logger.info(
            "Classified %d images: %d headshots, %d content",
            len(classified), headshot_count, content_count,
        )
        return classified

    def _classify_single_image(self, img: Image.Image, idx: int = 0) -> str:
        """
        Classify a single image using OpenRouter Vision LLM.
        Falls back to heuristic classification if API is unavailable.
        """
        # Try LLM vision classification first
        if self.openrouter_api_key:
            try:
                return self._classify_with_vision_llm(img, idx)
            except Exception as e:
                logger.warning(
                    "Vision LLM classification failed for image %d, "
                    "falling back to heuristics: %s", idx, e
                )

        # Fallback: heuristic classification
        return self._classify_heuristic(img)

    def _classify_with_vision_llm(self, img: Image.Image, idx: int = 0) -> str:
        """
        Use OpenRouter Vision API with nvidia/nemotron-nano to classify an image.
        """
        # Resize for API efficiency (max 512px on longest side)
        thumb = img.copy()
        thumb.thumbnail((512, 512), Image.LANCZOS)

        # Convert to base64
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=80)
        b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "model": OPENROUTER_VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": HEADSHOT_CLASSIFICATION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 10,
            "temperature": 0.0,
        }

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://resume-optimizer.vercel.app",
            "X-Title": "Resume Optimizer",
        }

        response = httpx.post(
            OPENROUTER_BASE_URL,
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        answer = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
            .upper()
        )

        if "HEADSHOT" in answer:
            logger.info("Vision LLM classified image %d as HEADSHOT", idx)
            return "headshot"
        else:
            logger.info("Vision LLM classified image %d as CONTENT", idx)
            return "content"

    def _classify_heuristic(self, img: Image.Image) -> str:
        """
        Fallback heuristic classifier based on aspect ratio and size.

        Headshot indicators:
        - Roughly square (aspect ratio 0.6–1.4)
        - Relatively small (< 500x500)
        - Not too large relative to the page

        Content indicators:
        - Wide/landscape or very tall
        - Large area (likely a scanned page region)
        """
        w, h = img.size
        aspect = w / max(h, 1)
        area = w * h

        is_squarish = 0.6 <= aspect <= 1.5
        is_small = area < 250_000  # ~500x500

        if is_squarish and is_small:
            logger.info(
                "Heuristic: image %dx%d (aspect %.2f, area %d) → headshot",
                w, h, aspect, area,
            )
            return "headshot"
        else:
            logger.info(
                "Heuristic: image %dx%d (aspect %.2f, area %d) → content",
                w, h, aspect, area,
            )
            return "content"

    # ------------------------------------------------------------------ #
    #  OCR — Dual-engine: Tesseract (local) or Vision LLM (Vercel/cloud)
    # ------------------------------------------------------------------ #

    def _ocr_image(self, img: Image.Image) -> str:
        """
        Extract text from an image using the best available OCR engine.

        Strategy (auto-selected):
          1. If Tesseract binary is installed → use it (fast, offline)
          2. If OpenRouter API key is set → use Vision LLM OCR (works on Vercel)
          3. If neither → return empty string with a warning

        Pre-processes: convert to grayscale, resize if too large.
        """
        # Try Tesseract first (faster, offline, free)
        tesseract = _get_tesseract()
        if tesseract is not None:
            return self._ocr_with_tesseract(img, tesseract)

        # Fall back to Vision LLM OCR (works on Vercel where tesseract isn't installed)
        if self.openrouter_api_key:
            return self._ocr_with_vision_llm(img)

        logger.warning(
            "No OCR engine available: tesseract not installed and no OPENROUTER_API_KEY set. "
            "Install tesseract (brew install tesseract) or set OPENROUTER_API_KEY in .env"
        )
        return ""

    def _ocr_with_tesseract(self, img: Image.Image, tesseract) -> str:
        """Run Tesseract OCR on a PIL Image."""
        # Pre-process
        processed = img.convert("L")  # grayscale

        # Downscale very large images
        w, h = processed.size
        if max(w, h) > MAX_IMAGE_DIM_FOR_OCR:
            ratio = MAX_IMAGE_DIM_FOR_OCR / max(w, h)
            new_size = (int(w * ratio), int(h * ratio))
            processed = processed.resize(new_size, Image.LANCZOS)

        try:
            text = tesseract.image_to_string(processed, lang="eng")
            return text.strip()
        except Exception as e:
            logger.warning("Tesseract OCR failed: %s", e)
            return ""

    def _ocr_with_vision_llm(self, img: Image.Image) -> str:
        """
        Use OpenRouter Vision LLM to extract text from an image.
        This is the cloud fallback for environments without Tesseract (e.g. Vercel).
        """
        # Resize for API — higher res than classification for better OCR
        thumb = img.copy()
        thumb.thumbnail((1024, 1024), Image.LANCZOS)

        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=90)
        b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "model": OPENROUTER_VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_OCR_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.0,
        }

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://resume-optimizer.vercel.app",
            "X-Title": "Resume Optimizer",
        }

        try:
            response = httpx.post(
                OPENROUTER_BASE_URL,
                json=payload,
                headers=headers,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            logger.info("Vision LLM OCR extracted %d chars", len(text))
            return text
        except Exception as e:
            logger.warning("Vision LLM OCR failed: %s", e)
            return ""

    # ------------------------------------------------------------------ #
    #  Utility: Check if Tesseract is available
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_tesseract_available() -> bool:
        """Check if Tesseract binary is installed and accessible."""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

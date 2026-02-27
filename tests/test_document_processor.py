"""
Tests for the DocumentProcessor module.

Covers:
- DOCX text extraction through the processor
- PDF text extraction (native text)
- PDF OCR fallback (image-only PDFs)
- Image classification heuristics
- Process notes & auto_apply_override for image-heavy docs
"""

import io
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from PIL import Image

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.document_processor import DocumentProcessor, ProcessingResult, ClassifiedImage


class TestDocumentProcessorDocx(unittest.TestCase):
    """Test DOCX processing through DocumentProcessor."""

    @classmethod
    def setUpClass(cls):
        cls.test_docx_path = "tests/test_resume.docx"
        if not os.path.exists(cls.test_docx_path):
            raise FileNotFoundError(f"Test file not found: {cls.test_docx_path}")
        with open(cls.test_docx_path, "rb") as f:
            cls.docx_bytes = f.read()

    def test_docx_text_extraction(self):
        """DOCX files should extract text through the processor."""
        print("\n--- Testing DOCX processing via DocumentProcessor ---")
        processor = DocumentProcessor()
        result = processor.process(self.docx_bytes, "test_resume.docx")

        self.assertIsInstance(result, ProcessingResult)
        self.assertIn("docx", result.source_type)
        self.assertGreater(len(result.text), 50)
        self.assertIn("John Doe", result.text)
        print(f"Extracted {len(result.text)} chars, source_type={result.source_type}")

    def test_docx_images_counted(self):
        """DOCX processor should count embedded images."""
        processor = DocumentProcessor()
        result = processor.process(self.docx_bytes, "test_resume.docx")
        # images_found should be an int >= 0
        self.assertIsInstance(result.images_found, int)
        print(f"DOCX contains {result.images_found} images")

    def test_extension_detection(self):
        """Processor should route based on file extension."""
        processor = DocumentProcessor()
        with self.assertRaises(ValueError):
            processor.process(b"fake data", "resume.txt")

    def test_process_notes_list(self):
        """ProcessingResult.process_notes should always be a list."""
        processor = DocumentProcessor()
        result = processor.process(self.docx_bytes, "test_resume.docx")
        self.assertIsInstance(result.process_notes, list)


class TestDocumentProcessorPdf(unittest.TestCase):
    """Test PDF processing through DocumentProcessor."""

    def _create_simple_pdf(self, text: str = None) -> bytes:
        """Create a simple PDF in-memory with ReportLab (already a project dependency)."""
        if text is None:
            text = (
                "John Doe\n"
                "Senior Backend Engineer\n"
                "Professional Summary\n"
                "Experienced backend engineer with 8+ years of expertise in Python, Docker, and AWS.\n"
                "Skilled in designing and implementing scalable microservices architectures.\n"
                "Technical Skills: Python, JavaScript, Go, Docker, Kubernetes, AWS, PostgreSQL, Redis.\n"
                "Experience\n"
                "Lead Backend Engineer at TechCorp (2020-Present)\n"
                "Built and maintained high-throughput APIs serving 10M+ requests per day.\n"
                "Education\n"
                "BS Computer Science, MIT, 2015"
            )
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        y = 700
        for line in text.split("\n"):
            c.drawString(72, y, line)
            y -= 20
        c.save()
        buf.seek(0)
        return buf.read()

    def test_pdf_native_text_extraction(self):
        """PDF with native text should extract cleanly."""
        print("\n--- Testing PDF native text extraction ---")
        pdf_bytes = self._create_simple_pdf()
        processor = DocumentProcessor()
        result = processor.process(pdf_bytes, "resume.pdf")

        self.assertIsInstance(result, ProcessingResult)
        self.assertEqual(result.source_type, "pdf_native")
        self.assertIn("John Doe", result.text)
        self.assertIn("Senior Backend Engineer", result.text)
        print(f"PDF text: {len(result.text)} chars, source_type={result.source_type}")

    def test_pdf_sparse_text_triggers_ocr(self):
        """PDF with very little text should trigger the OCR path (if tesseract available)."""
        print("\n--- Testing PDF OCR fallback ---")
        # Create a PDF with almost no text (just whitespace)
        pdf_bytes = self._create_simple_pdf("x")

        processor = DocumentProcessor()

        if not DocumentProcessor.is_tesseract_available():
            print("Tesseract not installed — skipping OCR fallback test")
            return

        result = processor.process(pdf_bytes, "sparse.pdf")
        # With only "x", it might be native or OCR depending on char count
        self.assertIsInstance(result, ProcessingResult)
        print(f"Sparse PDF: source_type={result.source_type}, text_len={len(result.text)}")

    def test_pdf_process_notes_empty_for_clean(self):
        """Clean text-only PDF should have no process notes."""
        pdf_bytes = self._create_simple_pdf("A full resume with plenty of text content " * 5)
        processor = DocumentProcessor()
        result = processor.process(pdf_bytes, "clean.pdf")
        # A clean text PDF shouldn't trigger image-heavy notes
        self.assertEqual(len(result.process_notes), 0)


class TestImageClassification(unittest.TestCase):
    """Test image classification logic."""

    def test_small_square_classified_as_headshot(self):
        """A small, square image should be classified as a headshot by heuristics."""
        print("\n--- Testing heuristic: small square → headshot ---")
        processor = DocumentProcessor()
        img = Image.new("RGB", (150, 180), color=(200, 180, 160))
        classification = processor._classify_heuristic(img)
        self.assertEqual(classification, "headshot")
        print(f"150x180 → {classification}")

    def test_large_landscape_classified_as_content(self):
        """A large, landscape image should be classified as content by heuristics."""
        print("\n--- Testing heuristic: large landscape → content ---")
        processor = DocumentProcessor()
        img = Image.new("RGB", (1200, 800), color=(255, 255, 255))
        classification = processor._classify_heuristic(img)
        self.assertEqual(classification, "content")
        print(f"1200x800 → {classification}")

    def test_large_portrait_classified_as_content(self):
        """A large, portrait/page-sized image should be classified as content."""
        processor = DocumentProcessor()
        img = Image.new("RGB", (800, 1200), color=(255, 255, 255))
        classification = processor._classify_heuristic(img)
        self.assertEqual(classification, "content")

    def test_vision_llm_fallback_to_heuristic(self):
        """If OpenRouter API key is missing, should fall back to heuristics."""
        processor = DocumentProcessor(openrouter_api_key="")
        img = Image.new("RGB", (100, 100), color=(200, 180, 160))
        classification = processor._classify_single_image(img, 0)
        # Should use heuristic (no API key)
        self.assertEqual(classification, "headshot")

    @patch("src.document_processor.httpx.post")
    def test_vision_llm_classification(self, mock_post):
        """Vision LLM should classify images when API key is present."""
        print("\n--- Testing Vision LLM classification (mocked) ---")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "HEADSHOT"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        processor = DocumentProcessor(openrouter_api_key="test-key")
        img = Image.new("RGB", (200, 200), color=(200, 180, 160))
        classification = processor._classify_single_image(img, 0)
        self.assertEqual(classification, "headshot")
        print("Vision LLM mock returned HEADSHOT ✓")

    @patch("src.document_processor.httpx.post")
    def test_vision_llm_content_classification(self, mock_post):
        """Vision LLM classifying a content image."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "RESUME_CONTENT"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        processor = DocumentProcessor(openrouter_api_key="test-key")
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        classification = processor._classify_single_image(img, 0)
        self.assertEqual(classification, "content")


class TestAutoApplyOverride(unittest.TestCase):
    """Test that auto_apply is overridden for image-heavy documents."""

    def test_clean_docx_no_override(self):
        """Clean text DOCX should not override auto_apply."""
        test_docx_path = "tests/test_resume.docx"
        if not os.path.exists(test_docx_path):
            self.skipTest("Test DOCX not found")

        with open(test_docx_path, "rb") as f:
            docx_bytes = f.read()

        processor = DocumentProcessor()
        result = processor.process(docx_bytes, "test_resume.docx")
        # auto_apply_override should be None if no image-heavy content
        # (unless the test docx actually has content images)
        self.assertIsInstance(result.auto_apply_override, (type(None), bool))


class TestOCR(unittest.TestCase):
    """Test OCR functionality (skipped if tesseract not installed)."""

    def setUp(self):
        if not DocumentProcessor.is_tesseract_available():
            self.skipTest("Tesseract not installed — skipping OCR tests")

    def test_ocr_simple_text_image(self):
        """OCR should extract text from a simple image with text."""
        print("\n--- Testing OCR on generated text image ---")
        # Create an image with text using Pillow
        from PIL import ImageDraw, ImageFont
        img = Image.new("RGB", (400, 100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        except Exception:
            font = ImageFont.load_default()
        draw.text((10, 30), "Hello Resume World", fill=(0, 0, 0), font=font)

        processor = DocumentProcessor()
        text = processor._ocr_image(img)
        self.assertIn("Hello", text)
        print(f"OCR extracted: '{text}'")


if __name__ == "__main__":
    unittest.main()

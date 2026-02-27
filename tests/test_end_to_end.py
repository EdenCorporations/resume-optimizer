
import unittest
import os
import io
import json
from unittest.mock import patch, MagicMock

# Add src to python path if needed, but relative imports should work if structured correctly
# Assuming running from project root
import sys
sys.path.append(os.getcwd())

from src.research_engine import ResearchEngine
from src.llm_analyzer import LLMAnalyzer
from src.resume_editor import ResumeEditor
from src.pdf_generator import PDFGenerator
from src.vision_processor import VisionProcessor
from src.document_processor import DocumentProcessor, ProcessingResult
from docx import Document

class TestResumeOptimizer(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Config
        cls.test_docx_path = "tests/test_resume.docx"
        cls.output_dir = "tests/test_outputs"
        os.makedirs(cls.output_dir, exist_ok=True)
        
        # Test Data
        cls.job_title = "Senior Python Engineer"
        cls.job_description = "We are looking for a Senior Python Engineer to build scalable APIs."
        cls.company_name = "TechCorp"
        
        # Verify test file exists
        if not os.path.exists(cls.test_docx_path):
            raise FileNotFoundError(f"Test file not found: {cls.test_docx_path}")

    def test_1_research_engine_mock(self):
        """Test ResearchEngine with mocked search results."""
        print("\n--- Testing Research Engine (Mocked) ---")
        
        re = ResearchEngine()
        
        # Mock the internal search methods to avoid actual network calls and rate limits
        with patch.object(re, '_safe_search') as mock_search:
            mock_search.side_effect = [
                "Responsibility: Write clean Python code.", # role
                "Trend: Microservices and Kubernetes.",    # tech
                "Value: Innovation and integrity.",        # values
                "News: Launched new AI product.",          # news
                "Competitor: RivalCorp.",                  # competitors
                "Skill: FastAPI, Docker.",                 # shadow skills
            ]
            
            profile = re.research(self.job_title, self.job_description, self.company_name)
            
            self.assertEqual(profile['job_title'], self.job_title)
            self.assertIn("Python", profile['role_responsibilities'])
            self.assertEqual(profile['company_name'], self.company_name)
            print("Research Engine Profile Built Successfully.")

    def test_2_resume_parsing(self):
        """Test parsing of the .docx file."""
        print("\n--- Testing Document Parsing ---")
        editor = ResumeEditor(self.test_docx_path)
        text = editor.extract_text()
        self.assertIn("John Doe", text)
        self.assertIn("Backend Engineer", text)
        print("Resume text extracted successfully.")
        return text

    def test_3_llm_analyzer_mock(self):
        """Test LLM Analyzer with mocked Groq responses."""
        print("\n--- Testing LLM Analyzer (Mocked) ---")
        
        # Fake successes profile for testing
        success_profile = {
            "role_responsibilities": "Write code",
            "tech_trends": "AI",
            "company_values": "Kindness",
            "recent_news": "None",
            "competitors": "None",
            "shadow_skills": "None",
            "cultural_tone": "balanced"
        }
        
        analyzer = LLMAnalyzer(api_key="fake-key", model="fake-model")
        
        # Define expected responses mapped to prompts or just sequential with debug
        responses_iter = iter([
            # 1. Gap Analysis
            "The candidate has strong Python skills but lacks Kubernetes knowledge.",
            
            # 2. Section Scores
            json.dumps({"skills": 85, "experience": 90, "impact": 75}),
            
            # 3. Match Scores
            json.dumps({"technical_match": 88, "cultural_match": 80}),
            
            # 4. ATS Sim
            json.dumps({"score": 92, "warnings": ["Avoid columns"]}),
            
            # 5. Suggestions
            json.dumps([
                {
                    "section": "Experience",
                    "original_text": "microservices architecture",
                    "replacement_text": "scalable microservices architecture on AWS",
                    "reason": "Add cloud context"
                }
            ]),
            
            # 6. Interview Questions
            json.dumps(["Describe your experience with microservices?"]),
            
            # 7. Cover Letter
            "Dear Hiring Manager,\n\nI am excited to apply...",
            
            # 8. Talking Points
            json.dumps(["I expanded the architecture to handle 2x traffic."])
        ])

        def side_effect(system, user, **kwargs):
            try:
                return next(responses_iter)
            except StopIteration:
                return ""

        with patch.object(analyzer, '_call_groq', side_effect=side_effect):
            result = analyzer.analyze(
                resume_text="Mock resume text", 
                job_title=self.job_title,
                job_description=self.job_description,
                success_profile=success_profile
            )
            
            self.assertEqual(result['scores']['skills'], 85)
            self.assertEqual(result['ats_score'], 92)
            self.assertEqual(len(result['suggestions']), 1)
            self.assertEqual(result['suggestions'][0]['original_text'], "microservices architecture")
            print("LLM Analyzer returned structured results successfully.")
            return result

    def test_4_resume_editing_preservation(self):
        """Test in-place editing preserves formatting."""
        print("\n--- Testing Resume Editor (Formatting Preservation) ---")
        
        editor = ResumeEditor(self.test_docx_path)
        
        # We want to replace "microservices architecture" which was created in the setup
        # It was: item1.add_run("microservices architecture").bold = True
        
        suggestions = [{
            "original_text": "microservices architecture",
            "replacement_text": "distributed cloud systems", # Change content
            "reason": "Testing replacement"
        }]
        
        result = editor.apply_suggestions(suggestions)
        
        self.assertEqual(result['applied'], 1, "Should have applied 1 suggestion")
        
        # Save and verify
        output_path = f"{self.output_dir}/test_optimized.docx"
        editor.save(output_path)
        print(f"Saved optimized resume to {output_path}")
        
        # Verification: Open the saved doc and check properties
        doc = Document(output_path)
        found_new_text = False
        is_bold = False
        
        for p in doc.paragraphs:
            for r in p.runs:
                if "distributed cloud systems" in r.text:
                    found_new_text = True
                    if r.bold:
                        is_bold = True
        
        self.assertTrue(found_new_text, "New text not found in document")
        self.assertTrue(is_bold, "Formatting lost! New text should be bold like the original.")
        print("Formatting preservation verified: Text replaced and Bold style kept.")

    def test_5_pdf_generation(self):
        """Test PDF generation for Interview Prep and Cover Letter."""
        print("\n--- Testing PDF Generation ---")
        
        gen = PDFGenerator()
        
        # Interview Prep
        questions = ["Q1: Explain Python GIL?", "Q2: How do you handle merge conflicts?"]
        int_path = f"{self.output_dir}/test_interview_prep.pdf"
        gen.generate_interview_prep(questions, self.job_title, int_path)
        self.assertTrue(os.path.exists(int_path))
        print(f"Generated {int_path}")
        
        # Cover Letter
        cl_text = "This is a test cover letter.\n\nIt has multiple paragraphs."
        cl_path = f"{self.output_dir}/test_cover_letter.pdf"
        gen.generate_cover_letter(cl_text, self.job_title, self.company_name, cl_path)
        self.assertTrue(os.path.exists(cl_path))
        print(f"Generated {cl_path}")

        # Talking Points PDF
        suggestions = [{
            "original_text": "Before text",
            "replacement_text": "After text",
            "reason": "Better word",
            "talking_point": "I improved X to Y.",
            "section": "Experience"
        }]
        tp_path = f"{self.output_dir}/test_talking_points.pdf"
        gen.generate_talking_points_pdf(suggestions, self.job_title, tp_path)
        self.assertTrue(os.path.exists(tp_path))
        print(f"Generated {tp_path}")

    def test_6_vision_processor_classification(self):
        """Test VisionProcessor image classification with mocked OpenRouter."""
        print("\n--- Testing Vision Processor (Classification, Mocked) ---")

        vp = VisionProcessor(api_key="fake-key", model="nvidia/nemotron-nano-12b-v2-vl:free")

        # Mock the HTTP call
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"type": "headshot", "confidence": 0.95}'}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = vp.classify_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")

            self.assertEqual(result["type"], "headshot")
            self.assertGreater(result["confidence"], 0.9)
            print(f"Classification result: {result}")

    def test_7_vision_processor_ocr(self):
        """Test VisionProcessor OCR with mocked OpenRouter."""
        print("\n--- Testing Vision Processor (OCR, Mocked) ---")

        vp = VisionProcessor(api_key="fake-key", model="nvidia/nemotron-nano-12b-v2-vl:free")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "John Doe\nSenior Software Engineer\n- Python, Docker"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            text = vp.ocr_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")

            self.assertIn("John Doe", text)
            self.assertIn("Senior Software Engineer", text)
            print(f"OCR extracted text: {text[:100]}")

    def test_8_vision_processor_disabled(self):
        """Test VisionProcessor graceful fallback when no API key."""
        print("\n--- Testing Vision Processor (No API Key) ---")

        vp = VisionProcessor(api_key="", model="")

        result = vp.classify_image(b"\x89PNG" + b"\x00" * 100)
        self.assertEqual(result["type"], "resume_content")
        self.assertEqual(result["confidence"], 0.5)

        text = vp.ocr_image(b"\x89PNG" + b"\x00" * 100)
        self.assertEqual(text, "")
        print("Graceful fallback works correctly.")

    def test_9_document_processor_docx(self):
        """Test DocumentProcessor with DOCX file."""
        print("\n--- Testing Document Processor (DOCX) ---")

        if not os.path.exists(self.test_docx_path):
            self.skipTest("Test DOCX not found")

        with open(self.test_docx_path, "rb") as f:
            docx_bytes = f.read()

        # Use processor with no OpenRouter key (skips vision)
        processor = DocumentProcessor(openrouter_api_key="", openrouter_model="")
        result = processor.process(docx_bytes, "test_resume.docx")

        self.assertEqual(result.file_type, "docx")
        self.assertIn("John Doe", result.text)
        self.assertIsInstance(result.process_notes, list)
        print(f"DOCX processed: {len(result.text)} chars, images={result.has_images}")

    def test_10_document_processor_pdf_mock(self):
        """Test DocumentProcessor PDF path with mocked libraries."""
        print("\n--- Testing Document Processor (PDF, Mocked) ---")

        processor = DocumentProcessor(openrouter_api_key="", openrouter_model="")

        # Create a minimal mock for the PDF processing
        fake_pdf_bytes = b"%PDF-1.4 fake"

        with patch("pdfplumber.open") as mock_plumber, \
             patch("fitz.open") as mock_fitz:

            # Mock pdfplumber
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Jane Smith\nSoftware Developer\nPython, React"
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            mock_plumber.return_value = mock_pdf

            # Mock PyMuPDF (no images)
            mock_doc = MagicMock()
            mock_doc.__len__ = MagicMock(return_value=1)
            mock_fitz_page = MagicMock()
            mock_fitz_page.get_images.return_value = []
            mock_doc.__getitem__ = MagicMock(return_value=mock_fitz_page)
            mock_doc.close = MagicMock()
            mock_fitz.return_value = mock_doc

            result = processor.process(fake_pdf_bytes, "resume.pdf")

            self.assertEqual(result.file_type, "pdf")
            self.assertIn("Jane Smith", result.text)
            self.assertFalse(result.has_images)
            print(f"PDF processed: {len(result.text)} chars")


if __name__ == '__main__':
    unittest.main()

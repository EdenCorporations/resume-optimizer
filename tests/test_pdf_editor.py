import io
import unittest
from lxml import etree
import fitz

from src.pdf_editor import PDFEditor
from reportlab.pdfgen import canvas

class TestPDFEditor(unittest.TestCase):
    def setUp(self):
        # Create a simple PDF in memory using reportlab
        self.buffer = io.BytesIO()
        c = canvas.Canvas(self.buffer)
        c.setFont("Helvetica", 12)
        c.drawString(100, 700, "This is a resume bullet.")
        c.drawString(100, 680, "Managed a team of 5 people.")
        c.save()
        self.pdf_bytes = self.buffer.getvalue()

    def test_apply_suggestions(self):
        editor = PDFEditor(self.pdf_bytes)
        
        suggestions = [
            {
                "original_text": "Managed a team of 5 people.",
                "replacement_text": "Led a cross-functional team of 5 software engineers.",
                "reason": "More specificity"
            },
            {
                "original_text": "Not in the document",
                "replacement_text": "Should fail",
                "reason": "Test failure case"
            }
        ]
        
        results = editor.apply_suggestions(suggestions)
        
        # Verify results dict
        self.assertEqual(results["applied"], 1)
        self.assertEqual(results["failed"], 1)
        self.assertEqual(len(results["details"]), 2)
        
        # Check that the modified PDF contains the new text
        modified_bytes = editor.save_to_bytes()
        doc = fitz.open(stream=modified_bytes, filetype="pdf")
        text = doc[0].get_text()
        
        self.assertIn("Led a cross-functional team", text)
        self.assertNotIn("Managed a team of 5 people.", text)
        self.assertIn("This is a resume bullet.", text)

if __name__ == '__main__':
    unittest.main()

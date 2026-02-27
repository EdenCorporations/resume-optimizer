"""
Resume Optimizer – Flask Application

Main entry point for the web application. Handles file uploads,
orchestrates the analysis pipeline, and serves results.

Works on both local development (filesystem) and Vercel (Blob storage).
"""

import os
import io
import uuid
import logging
import traceback
import urllib.parse
import requests
from flask import Flask, request, jsonify, send_file, render_template, redirect, Response

from config import Config
from src.blob_storage import BlobStorage
from src.document_processor import DocumentProcessor
from src.research_engine import ResearchEngine
from src.llm_analyzer import LLMAnalyzer
from src.resume_editor import ResumeEditor
from src.pdf_generator import PDFGenerator

# ------------------------------------------------------------------ #
#  Setup
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH
app.config["SECRET_KEY"] = Config.SECRET_KEY

# Initialize blob storage (auto-detects Vercel vs local)
blob_storage = BlobStorage()

ALLOWED_EXTENSIONS = {"docx", "pdf"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ------------------------------------------------------------------ #
#  Routes
# ------------------------------------------------------------------ #


@app.route("/")
def index():
    """Serve the main UI page."""
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Full analysis pipeline:
    1. Read uploaded .docx (in-memory or disk depending on env)
    2. Extract text
    3. Run web research
    4. Run LLM analysis
    5. Optionally apply suggestions
    6. Generate PDFs (in-memory)
    7. Upload all outputs to Blob / save locally
    8. Return results JSON with download URLs
    """
    try:
        # --- Validate inputs ---
        if "resume" not in request.files:
            return jsonify({"error": "No resume file uploaded"}), 400

        file = request.files["resume"]
        if file.filename == "" or not allowed_file(file.filename):
            return jsonify({"error": "Please upload a .docx or .pdf file"}), 400

        job_title = request.form.get("job_title", "").strip()
        job_description = request.form.get("job_description", "").strip()
        company_name = request.form.get("company_name", "").strip() or None
        auto_apply = request.form.get("auto_apply", "false").lower() == "true"

        if not job_title:
            return jsonify({"error": "Job title is required"}), 400
        if not job_description:
            return jsonify({"error": "Job description is required"}), 400

        # --- Validate API key ---
        if not Config.GROQ_API_KEY:
            return jsonify({
                "error": "GROQ_API_KEY not configured. Add it to your .env file."
            }), 500

        # Ensure directories exist (no-op on Vercel)
        Config.validate()

        # --- Read uploaded file into memory ---
        session_id = str(uuid.uuid4())[:8]
        original_name = file.filename.replace(" ", "_")
        # Keep only safe chars
        original_name = "".join(c for c in original_name if c.isalnum() or c in "._-")
        file_bytes = file.read()
        logger.info("Read uploaded file: %s (%d bytes)", original_name, len(file_bytes))

        # --- Step 1: Process document (PDF/DOCX → text + image analysis) ---
        processor = DocumentProcessor(
            openrouter_api_key=Config.OPENROUTER_API_KEY,
        )
        processing_result = processor.process(file_bytes, original_name)
        resume_text = processing_result.text
        logger.info(
            "Processed document: %d chars, source=%s, images=%d",
            len(resume_text), processing_result.source_type,
            processing_result.images_found,
        )

        # Override auto_apply if processor flagged image-heavy content
        if processing_result.auto_apply_override is not None:
            auto_apply = processing_result.auto_apply_override
            if not auto_apply:
                logger.info("auto_apply disabled by DocumentProcessor (image-heavy resume)")

        if len(resume_text) < 50:
            return jsonify({
                "error": "The uploaded document appears to be empty or too short. "
                         "If this is a scanned/image PDF, ensure Tesseract OCR is installed."
            }), 400

        # Keep a ResumeEditor for DOCX auto-apply (PDF can't be edited in-place)
        file_ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
        editor = ResumeEditor(file_bytes) if file_ext == 'docx' else None

        # --- Step 2: Web Research ---
        research_engine = ResearchEngine()
        success_profile = research_engine.research(
            job_title=job_title,
            job_description=job_description,
            company_name=company_name,
        )

        # --- Step 3: LLM Analysis ---
        analyzer = LLMAnalyzer(
            api_key=Config.GROQ_API_KEY,
            model=Config.GROQ_MODEL,
            gateway_api_key=Config.AI_GATEWAY_API_KEY,
        )
        analysis = analyzer.analyze(
            resume_text=resume_text,
            job_title=job_title,
            job_description=job_description,
            success_profile=success_profile,
        )

        # --- Step 4: Apply suggestions (if auto-apply, DOCX only) ---
        optimized_resume_url = None
        edit_results = None
        if auto_apply and analysis.get("suggestions") and editor is not None:
            edit_results = editor.apply_suggestions(analysis["suggestions"])

            # Save optimized resume to BytesIO, then upload
            optimized_buffer = editor.save_to_bytesio()
            optimized_filename = f"{session_id}_optimized_{original_name}"
            optimized_resume_url = blob_storage.save_docx(optimized_buffer, optimized_filename)
            logger.info("Optimized resume stored: %s", optimized_resume_url)

        # --- Step 5: Generate PDFs (all in-memory) ---
        interview_prep_url = None
        cover_letter_url = None
        talking_points_url = None
        pdf_gen = PDFGenerator()

        if analysis.get("interview_questions"):
            interview_buffer = pdf_gen.generate_interview_prep(
                questions=analysis["interview_questions"],
                job_title=job_title,
            )
            interview_filename = f"{session_id}_interview_prep.pdf"
            interview_prep_url = blob_storage.save_pdf(interview_buffer, interview_filename)

        if analysis.get("cover_letter"):
            cover_letter_buffer = pdf_gen.generate_cover_letter(
                cover_letter_text=analysis["cover_letter"],
                job_title=job_title,
                company_name=company_name or "Target Company",
            )
            cover_letter_filename = f"{session_id}_cover_letter.pdf"
            cover_letter_url = blob_storage.save_pdf(cover_letter_buffer, cover_letter_filename)

        # Generate talking points as a SEPARATE PDF
        if analysis.get("suggestions"):
            tp_buffer = pdf_gen.generate_talking_points_pdf(
                suggestions=analysis["suggestions"],
                job_title=job_title,
            )
            tp_filename = f"{session_id}_talking_points.pdf"
            talking_points_url = blob_storage.save_pdf(tp_buffer, tp_filename)

        # --- Build download URLs ---
        downloads = {
            "optimized_resume": blob_storage.get_download_url(optimized_resume_url) if optimized_resume_url else None,
            "interview_prep": blob_storage.get_download_url(interview_prep_url) if interview_prep_url else None,
            "cover_letter": blob_storage.get_download_url(cover_letter_url) if cover_letter_url else None,
            "talking_points": blob_storage.get_download_url(talking_points_url) if talking_points_url else None,
        }

        # --- Build response ---
        response = {
            "success": True,
            "scores": analysis.get("scores", {}),
            "ats_score": analysis.get("ats_score", 0),
            "ats_warnings": analysis.get("ats_warnings", []),
            "gap_analysis": analysis.get("gap_analysis", ""),
            "suggestions": analysis.get("suggestions", []),
            "interview_questions": analysis.get("interview_questions", []),
            "cover_letter": analysis.get("cover_letter", ""),
            "overall_summary": analysis.get("overall_summary", ""),
            "auto_applied": auto_apply,
            "edit_results": edit_results,
            "downloads": downloads,
            "research_summary": {
                "company": company_name or "Not specified",
                "cultural_tone": success_profile.get("cultural_tone", "balanced"),
            },
            "process_notes": processing_result.process_notes,
            "source_type": processing_result.source_type,
        }

        return jsonify(response)

    except Exception as e:
        logger.error("Analysis failed: %s\n%s", str(e), traceback.format_exc())
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500


@app.route("/download/<filename>")
def download(filename):
    """Serve generated output files for download (local dev only)."""
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    file_path = os.path.join(Config.OUTPUT_FOLDER, safe_name)

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    return send_file(file_path, as_attachment=True, download_name=safe_name)


@app.route("/api/proxy-download")
def proxy_download():
    """
    Proxy a Vercel Blob URL and serve it as an attachment download.
    Query params: url (blob URL), name (desired filename).
    """
    blob_url = request.args.get("url", "")
    name = request.args.get("name", "download")

    if not blob_url:
        return jsonify({"error": "url parameter required"}), 400

    # Security: only proxy from known blob domains
    from urllib.parse import urlparse
    parsed = urlparse(blob_url)
    allowed_hosts = (
        "blob.vercel-storage.com",
        ".public.blob.vercel-storage.com",
    )
    if not any(parsed.hostname and (parsed.hostname == h or parsed.hostname.endswith(h)) for h in allowed_hosts):
        return jsonify({"error": "Invalid URL"}), 403

    try:
        resp = requests.get(blob_url, timeout=30, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "application/octet-stream")

        return Response(
            resp.iter_content(chunk_size=8192),
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-cache",
            },
        )
    except Exception as e:
        logger.error("Proxy download failed: %s", e)
        return jsonify({"error": "Download failed"}), 502


@app.route("/whatsapp-share", methods=["POST"])
def whatsapp_share():
    """
    Generate a WhatsApp share URL for a file.

    Accepts JSON: { "file_url": "...", "filename": "..." }
    Returns: { "whatsapp_url": "https://wa.me/?text=..." }
    """
    try:
        data = request.get_json()
        file_url = data.get("file_url", "")
        filename = data.get("filename", "My Optimized Resume")

        if not file_url:
            return jsonify({"error": "file_url is required"}), 400

        message = f"Check out my optimized resume: {filename}\n{file_url}"
        encoded_message = urllib.parse.quote(message)
        whatsapp_url = f"https://wa.me/?text={encoded_message}"

        return jsonify({"whatsapp_url": whatsapp_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cleanup", methods=["POST"])
def cleanup():
    """Cleanup old files (called by cron or manually)."""
    try:
        result = blob_storage.cleanup_old_files(max_age_hours=24)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/llm-status", methods=["GET"])
def llm_status():
    """Return status of all LLM endpoints (for debugging round-robin)."""
    try:
        from src.llm_provider import LLMProvider

        provider = LLMProvider(
            groq_api_key=Config.GROQ_API_KEY,
            gateway_api_key=Config.AI_GATEWAY_API_KEY,
        )
        return jsonify({
            "endpoint_count": provider.endpoint_count,
            "endpoints": provider.get_status(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    Config.validate()
    logger.info("Starting Resume Optimizer on http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001)

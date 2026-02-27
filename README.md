# 🚀 Resume Optimizer

**AI-Powered Deep Research & Auto-Edit Resume Tool**

> **Ideated by [Fredrick Xavier](https://www.linkedin.com/in/fredrickxavier)**

📦 **GitHub:** [github.com/EdenCorporations/resume-optimizer](https://github.com/EdenCorporations/resume-optimizer)

Upload your `.docx` or `.pdf` resume, provide a target job description, and let Llama-4-Maverick analyze, score, and intelligently optimize your resume — while preserving every bit of original formatting.

## Features

- **PDF & DOCX Support** — Upload either format; PDFs get in-place editing via PyMuPDF
- **Visual Intelligence** — Embedded images are classified (headshot vs. resume content) using AI vision
- **Smart OCR** — Image-heavy resumes are automatically OCR'd and rebuilt for ATS compliance
- **Deep Research Agent** — Live web research on role, industry trends, company culture
- **Gap Analysis** — AI-driven comparison of your resume vs. a "Success Profile"
- **Section Scoring** — Skills, Experience, Impact rated 0-100
- **Technical & Cultural Match** — Split scoring when a target company is provided
- **ATS Simulator** — Warns about format issues that confuse Applicant Tracking Systems
- **Auto-Optimize** — In-place editing that preserves bold, fonts, margins, layouts
- **Interview Prep PDF** — Likely questions based on your resume's weaknesses
- **Cover Letter Drafter** — References specific research findings
- **Interview Talking Points** — Defend every auto-applied edit (download separate PDF)

## Quick Start
            
```bash
# Clone
git clone https://github.com/EdenCorporations/resume-optimizer.git
cd resume-optimizer

# Virtual Env (Recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# Run
python app.py
```

Open [http://localhost:5001](http://localhost:5001) in your browser.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ Yes | Groq API key for LLM calls |
| `OPENROUTER_API_KEY` | Optional | OpenRouter key for vision OCR & image classification (free model) |
| `BLOB_READ_WRITE_TOKEN` | For Vercel | Vercel Blob storage token |
| `AI_GATEWAY_API_KEY` | Optional | Vercel AI Gateway key |
| `BRAVE_API_KEY` | Optional | Brave Search API for deep research |
| `FIRECRAWL_API_KEY` | Optional | Firecrawl API for deep research |

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Groq SDK → Llama-4-Maverick |
| Vision / OCR | OpenRouter → nvidia/nemotron-nano-12b-v2-vl (free) |
| DOCX Processing | python-docx (run-level editing) |
| PDF Processing | PyMuPDF (in-place redact-and-reinsert) + pdfplumber |
| Image Analysis | Pillow + Vision LLM classification |
| PDF Generation | ReportLab |
| Web Research | DuckDuckGo Search |
| Web Framework | Flask |
| Deployment | Vercel (Python serverless) |
| UI | Vanilla HTML/CSS/JS (dark mode) |

## Credits

- **Ideated by** [Fredrick Xavier](https://www.linkedin.com/in/fredrickxavier)
- **Built by** [EdenCORP](https://github.com/EdenCorporations)

## License

MIT

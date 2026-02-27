# 🚀 Resume Optimizer

**AI-Powered Deep Research & Auto-Edit Resume Tool**

Upload your `.docx` resume, provide a target job description, and let Llama-4-Maverick analyze, score, and intelligently optimize your resume — while preserving every bit of original formatting.

## Features

- **Deep Research Agent** — Live web research on role, industry trends, company culture
- **Gap Analysis** — AI-driven comparison of your resume vs. a "Success Profile"
- **Section Scoring** — Skills, Experience, Impact rated 0-100
- **Technical & Cultural Match** — Split scoring when a target company is provided
- **ATS Simulator** — Warns about format issues that confuse Applicant Tracking Systems
- **Auto-Optimize** — In-place `.docx` editing that preserves bold, fonts, margins
- **Interview Prep PDF** — Likely questions based on your resume's weaknesses
- **Cover Letter Drafter** — References specific research findings
- **Interview Talking Points** — Defend every auto-applied edit (download separate PDF)

## Quick Start
            
```bash
# Clone
git clone https://github.com/x-TheFox/resume-optimizer.git
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

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Groq SDK → Llama-4-Maverick |
| Doc Processing | python-docx (run-level editing) |
| Web Research | DuckDuckGo Search |
| PDF Generation | ReportLab |
| Web Framework | Flask |
| UI | Vanilla HTML/CSS/JS (dark mode) |

## License

MIT

---

## Credits

- **Ideated by:** [Fredrick Xavier](https://www.linkedin.com/in/fredrickxavier)
- **Built by:** [EdenCorporations](https://github.com/EdenCorporations)

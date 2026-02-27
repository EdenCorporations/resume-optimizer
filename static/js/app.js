/**
 * Resume Optimizer — Client-Side Application Logic
 *
 * Handles drag-and-drop, form submission, loading states,
 * score ring animations, and dynamic result rendering.
 */

(function () {
    'use strict';

    // ============================================================
    //  DOM References
    // ============================================================
    const DOM = {
        // Sections
        uploadSection: document.getElementById('uploadSection'),
        loadingSection: document.getElementById('loadingSection'),
        resultsSection: document.getElementById('resultsSection'),
        errorSection: document.getElementById('errorSection'),

        // Form
        form: document.getElementById('analyzeForm'),
        dropZone: document.getElementById('dropZone'),
        resumeInput: document.getElementById('resumeInput'),
        fileSelected: document.getElementById('fileSelected'),
        fileName: document.getElementById('fileName'),
        fileRemove: document.getElementById('fileRemove'),
        analyzeBtn: document.getElementById('analyzeBtn'),
        autoApply: document.getElementById('autoApply'),

        // Loader
        loaderTitle: document.getElementById('loaderTitle'),
        steps: [
            document.getElementById('step1'),
            document.getElementById('step2'),
            document.getElementById('step3'),
            document.getElementById('step4'),
            document.getElementById('step5'),
        ],

        // Results
        resultsSummary: document.getElementById('resultsSummary'),
        scoresGrid: document.getElementById('scoresGrid'),

        // Score rings
        atsScoreRing: document.getElementById('atsScoreRing'),
        atsScoreValue: document.getElementById('atsScoreValue'),
        skillsScoreRing: document.getElementById('skillsScoreRing'),
        skillsScoreValue: document.getElementById('skillsScoreValue'),
        experienceScoreRing: document.getElementById('experienceScoreRing'),
        experienceScoreValue: document.getElementById('experienceScoreValue'),
        impactScoreRing: document.getElementById('impactScoreRing'),
        impactScoreValue: document.getElementById('impactScoreValue'),
        techMatchScoreRing: document.getElementById('techMatchScoreRing'),
        techMatchScoreValue: document.getElementById('techMatchScoreValue'),
        culturalMatchScoreRing: document.getElementById('culturalMatchScoreRing'),
        culturalMatchScoreValue: document.getElementById('culturalMatchScoreValue'),

        // Panels
        atsWarningsPanel: document.getElementById('atsWarningsPanel'),
        atsWarningsList: document.getElementById('atsWarningsList'),
        gapAnalysisContent: document.getElementById('gapAnalysisContent'),
        suggestionsCount: document.getElementById('suggestionsCount'),
        suggestionsList: document.getElementById('suggestionsList'),
        interviewPanel: document.getElementById('interviewPanel'),
        interviewList: document.getElementById('interviewList'),
        coverLetterPanel: document.getElementById('coverLetterPanel'),
        coverLetterContent: document.getElementById('coverLetterContent'),

        // Downloads
        downloadsBar: document.getElementById('downloadsBar'),
        downloadsButtons: document.getElementById('downloadsButtons'),

        // Process Notes
        processNotesPanel: document.getElementById('processNotesPanel'),
        processNotesText: document.getElementById('processNotesText'),

        // Buttons
        restartBtn: document.getElementById('restartBtn'),
        errorRetryBtn: document.getElementById('errorRetryBtn'),
        errorMessage: document.getElementById('errorMessage'),
    };

    let selectedFile = null;

    // ============================================================
    //  Section Visibility
    // ============================================================
    function showSection(section) {
        [DOM.uploadSection, DOM.loadingSection, DOM.resultsSection, DOM.errorSection]
            .forEach(s => { s.style.display = 'none'; });
        section.style.display = 'block';
        section.style.animation = 'none';
        section.offsetHeight; // trigger reflow
        section.style.animation = '';
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // ============================================================
    //  Drag & Drop
    // ============================================================
    DOM.dropZone.addEventListener('click', () => DOM.resumeInput.click());

    DOM.dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        DOM.dropZone.classList.add('drag-over');
    });

    DOM.dropZone.addEventListener('dragleave', () => {
        DOM.dropZone.classList.remove('drag-over');
    });

    DOM.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        DOM.dropZone.classList.remove('drag-over');
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFile(files[0]);
    });

    DOM.resumeInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFile(e.target.files[0]);
    });

    DOM.fileRemove.addEventListener('click', (e) => {
        e.stopPropagation();
        clearFile();
    });

    function handleFile(file) {
        const name = file.name.toLowerCase();
        if (!name.endsWith('.docx') && !name.endsWith('.pdf')) {
            alert('Please upload a .docx or .pdf file');
            return;
        }
        selectedFile = file;
        DOM.dropZone.querySelector('.drop-zone-content').style.display = 'none';
        DOM.fileSelected.style.display = 'flex';
        DOM.fileName.textContent = file.name;
    }

    function clearFile() {
        selectedFile = null;
        DOM.resumeInput.value = '';
        DOM.dropZone.querySelector('.drop-zone-content').style.display = 'flex';
        DOM.fileSelected.style.display = 'none';
    }

    // ============================================================
    //  Form Submission
    // ============================================================
    DOM.form.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!selectedFile) {
            alert('Please upload your resume (.docx or .pdf)');
            return;
        }

        const jobTitle = document.getElementById('jobTitle').value.trim();
        const jobDescription = document.getElementById('jobDescription').value.trim();

        if (!jobTitle || !jobDescription) {
            alert('Please fill in the Job Title and Job Description');
            return;
        }

        // Build FormData
        const formData = new FormData();
        formData.append('resume', selectedFile);
        formData.append('job_title', jobTitle);
        formData.append('job_description', jobDescription);
        formData.append('company_name', document.getElementById('companyName').value.trim());
        formData.append('auto_apply', DOM.autoApply.checked ? 'true' : 'false');

        // Show loading
        showSection(DOM.loadingSection);
        DOM.analyzeBtn.disabled = true;
        startLoadingAnimation();

        try {
            const response = await fetch('/analyze', {
                method: 'POST',
                body: formData,
            });

            const data = await response.json();

            if (!response.ok || data.error) {
                throw new Error(data.error || 'Analysis failed');
            }

            renderResults(data);
            showSection(DOM.resultsSection);
        } catch (err) {
            DOM.errorMessage.textContent = err.message;
            showSection(DOM.errorSection);
        } finally {
            DOM.analyzeBtn.disabled = false;
        }
    });

    // ============================================================
    //  Loading Animation
    // ============================================================
    let loadingInterval;

    function startLoadingAnimation() {
        let currentStep = 0;
        const titles = [
            'Uploading your resume...',
            'Researching job market & company...',
            'Running AI gap analysis...',
            'Scoring & generating suggestions...',
            'Building optimized documents...',
        ];
        const durations = [1500, 8000, 12000, 10000, 5000];

        DOM.steps.forEach(s => { s.className = 'loader-step'; });
        DOM.steps[0].classList.add('active');
        DOM.loaderTitle.textContent = titles[0];

        function advanceStep() {
            if (currentStep < DOM.steps.length - 1) {
                DOM.steps[currentStep].classList.remove('active');
                DOM.steps[currentStep].classList.add('done');
                currentStep++;
                DOM.steps[currentStep].classList.add('active');
                DOM.loaderTitle.textContent = titles[currentStep];

                if (currentStep < DOM.steps.length - 1) {
                    loadingInterval = setTimeout(advanceStep, durations[currentStep]);
                }
            }
        }

        loadingInterval = setTimeout(advanceStep, durations[0]);
    }

    // ============================================================
    //  Render Results
    // ============================================================
    function renderResults(data) {
        clearTimeout(loadingInterval);

        // Process Notes (image-heavy warnings, etc.)
        const notes = data.process_notes || [];
        if (notes.length > 0 && DOM.processNotesPanel) {
            DOM.processNotesPanel.style.display = 'block';
            DOM.processNotesText.innerHTML = notes.map(n => `<p>${escapeHtml(n)}</p>`).join('');
        } else if (DOM.processNotesPanel) {
            DOM.processNotesPanel.style.display = 'none';
        }

        // Summary
        const company = data.research_summary?.company || 'your target role';
        const tone = data.research_summary?.cultural_tone || 'balanced';
        DOM.resultsSummary.textContent =
            `Analysis complete for ${company} • Cultural tone: ${tone}`;

        // Scores
        const scores = data.scores || {};
        animateScore(DOM.atsScoreRing, DOM.atsScoreValue, data.ats_score || 0);
        animateScore(DOM.skillsScoreRing, DOM.skillsScoreValue, scores.skills || 0);
        animateScore(DOM.experienceScoreRing, DOM.experienceScoreValue, scores.experience || 0);
        animateScore(DOM.impactScoreRing, DOM.impactScoreValue, scores.impact || 0);
        animateScore(DOM.techMatchScoreRing, DOM.techMatchScoreValue, scores.technical_match || 0);
        animateScore(DOM.culturalMatchScoreRing, DOM.culturalMatchScoreValue, scores.cultural_match || 0);

        // ATS Warnings
        const warnings = data.ats_warnings || [];
        if (warnings.length > 0) {
            DOM.atsWarningsPanel.style.display = 'block';
            DOM.atsWarningsList.innerHTML = warnings
                .map(w => `<li>${escapeHtml(w)}</li>`).join('');
        } else {
            DOM.atsWarningsPanel.style.display = 'none';
        }

        // Gap Analysis
        DOM.gapAnalysisContent.innerHTML = formatMarkdown(data.gap_analysis || 'No gap analysis available.');

        // Suggestions
        const suggestions = data.suggestions || [];
        DOM.suggestionsCount.textContent = `${suggestions.length} suggestions`;
        DOM.suggestionsList.innerHTML = suggestions.map((s, i) => `
            <div class="suggestion-item" style="animation-delay: ${i * 0.05}s">
                <div class="suggestion-section">${escapeHtml(s.section || 'General')}</div>
                <div class="suggestion-diff">
                    <div class="diff-old">${escapeHtml(s.original_text || '')}</div>
                    <div class="diff-new">${escapeHtml(s.replacement_text || '')}</div>
                </div>
                <div class="suggestion-reason">${escapeHtml(s.reason || '')}</div>
                ${s.talking_point ? `<div class="suggestion-talking-point">${escapeHtml(s.talking_point)}</div>` : ''}
            </div>
        `).join('');

        // Interview Questions
        const questions = data.interview_questions || [];
        if (questions.length > 0) {
            DOM.interviewPanel.style.display = 'block';
            DOM.interviewList.innerHTML = questions
                .map(q => `<li>${escapeHtml(q)}</li>`).join('');
        }

        // Cover Letter
        if (data.cover_letter) {
            DOM.coverLetterPanel.style.display = 'block';
            DOM.coverLetterContent.textContent = data.cover_letter;
        }

        // Downloads
        const dl = data.downloads || {};
        const downloadLinks = [];

        // Helper: build a download link that triggers actual file download
        function dlHref(url, label) {
            // For blob URLs, proxy through our endpoint to force Content-Disposition: attachment
            if (url.includes('blob.vercel-storage.com') || url.includes('.public.blob.vercel-storage.com')) {
                const name = label.replace(/[^a-zA-Z0-9_.-]/g, '_');
                return `/api/proxy-download?url=${encodeURIComponent(url)}&name=${encodeURIComponent(name)}`;
            }
            return url; // local /download/ paths already serve as attachment
        }

        if (dl.optimized_resume) {
            const fileType = data.file_type || 'docx';
            const ext = fileType === 'pdf' ? '.pdf' : '.docx';
            const icon = fileType === 'pdf' ? '📄' : '📄';
            const label = fileType === 'pdf' ? 'Optimized Resume (PDF)' : 'Optimized Resume';
            downloadLinks.push(
                `<a href="${dlHref(dl.optimized_resume, 'Optimized_Resume' + ext)}" class="btn-download" download>${icon} ${label}</a>`
            );
            downloadLinks.push(
                `<button class="btn-whatsapp" onclick="shareToWhatsApp('${dl.optimized_resume}', 'Optimized Resume')">
                    <svg class="whatsapp-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                    WhatsApp
                </button>`
            );
        }
        if (dl.interview_prep) {
            downloadLinks.push(
                `<a href="${dlHref(dl.interview_prep, 'Interview_Prep.pdf')}" class="btn-download" download>🎤 Interview Prep PDF</a>`
            );
            downloadLinks.push(
                `<button class="btn-whatsapp" onclick="shareToWhatsApp('${dl.interview_prep}', 'Interview Prep')">
                    <svg class="whatsapp-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                    WhatsApp
                </button>`
            );
        }
        if (dl.cover_letter) {
            downloadLinks.push(
                `<a href="${dlHref(dl.cover_letter, 'Cover_Letter.pdf')}" class="btn-download" download>✉️ Cover Letter PDF</a>`
            );
            downloadLinks.push(
                `<button class="btn-whatsapp" onclick="shareToWhatsApp('${dl.cover_letter}', 'Cover Letter')">
                    <svg class="whatsapp-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                    WhatsApp
                </button>`
            );
        }
        if (dl.talking_points) {
            downloadLinks.push(
                `<a href="${dlHref(dl.talking_points, 'Talking_Points.pdf')}" class="btn-download" download>🗣️ Talking Points PDF</a>`
            );
            downloadLinks.push(
                `<button class="btn-whatsapp" onclick="shareToWhatsApp('${dl.talking_points}', 'Talking Points')">
                    <svg class="whatsapp-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                    WhatsApp
                </button>`
            );
        }
        if (downloadLinks.length > 0) {
            DOM.downloadsBar.style.display = 'block';
            DOM.downloadsButtons.innerHTML = downloadLinks.join('');
        }
    }

    // ============================================================
    //  Score Ring Animation
    // ============================================================
    function animateScore(ringEl, valueEl, targetScore) {
        const circumference = 326.73; // 2 * π * 52
        const fillCircle = ringEl.querySelector('.score-ring-fill');
        const offset = circumference - (circumference * targetScore / 100);

        // Color based on score
        let color;
        if (targetScore >= 80) color = 'var(--score-excellent)';
        else if (targetScore >= 60) color = 'var(--score-good)';
        else if (targetScore >= 40) color = 'var(--score-average)';
        else color = 'var(--score-poor)';

        fillCircle.style.stroke = color;
        valueEl.style.color = color;

        // Animate after a small delay
        setTimeout(() => {
            fillCircle.style.strokeDashoffset = offset;
        }, 200);

        // Count up number
        let current = 0;
        const duration = 1500;
        const increment = targetScore / (duration / 16);
        const counter = setInterval(() => {
            current += increment;
            if (current >= targetScore) {
                current = targetScore;
                clearInterval(counter);
            }
            valueEl.textContent = Math.round(current);
        }, 16);
    }

    // ============================================================
    //  Utilities
    // ============================================================
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatMarkdown(text) {
        // Simple markdown → HTML for bold, headers, lists
        let html = escapeHtml(text);

        // Headers
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Bold
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

        // Lists
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');

        // Wrap consecutive <li> in <ul>
        html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

        // Paragraphs (double newline)
        html = html.replace(/\n\n/g, '</p><p>');
        html = '<p>' + html + '</p>';

        // Single newlines
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    // ============================================================
    //  Restart / Retry
    // ============================================================
    DOM.restartBtn.addEventListener('click', () => {
        showSection(DOM.uploadSection);
        clearFile();

        // Reset results panels
        DOM.atsWarningsPanel.style.display = 'none';
        DOM.interviewPanel.style.display = 'none';
        DOM.coverLetterPanel.style.display = 'none';
        DOM.downloadsBar.style.display = 'none';
        if (DOM.processNotesPanel) DOM.processNotesPanel.style.display = 'none';
    });

    DOM.errorRetryBtn.addEventListener('click', () => {
        showSection(DOM.uploadSection);
    });

})();

// ============================================================
//  WhatsApp Share (global scope for onclick handlers)
// ============================================================
function shareToWhatsApp(fileUrl, filename) {
    const message = `Check out my optimized resume document: ${filename}\n${fileUrl}`;
    const encoded = encodeURIComponent(message);
    window.open(`https://wa.me/?text=${encoded}`, '_blank');
}

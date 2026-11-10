# Friendly Handover — V5 AI Upgrade

This version upgrades the AI/document-analysis backend while preserving the existing V4 user interface, authority and employee workflows, upload controls, permission process, and report download flow.

## What changed in V5

### AI analysis (`ai_engine.py`)
- Multi-topic evidence retrieval before report generation.
- Document chunking with overlap so long files are not cut off at a single fixed character limit.
- Request-scoped ChromaDB vector storage with OpenAI embeddings for semantic retrieval.
- Local keyword retrieval fallback if ChromaDB or embedding retrieval is unavailable.
- Structured JSON analysis, validated and rendered into a consistent report.
- Dedicated analysis of project status, completed/pending work, documented decisions, possible interpretations, timeline, risks, dependencies, open questions, next actions, conflicts and limitations.
- Source citations include the approved document ID, filename and page/slide location when available.
- Confidence labels are evidence-quality assessments, not guarantees.
- Structured project memory and analysis history are saved in SQLite. Previous memory is used only as continuity context; current report claims must still cite currently approved evidence.
- The no-key/API-failure fallback is explicitly labelled as a non-AI report and does not pretend to have performed AI reasoning.
- Uploaded source content is treated as untrusted data, not as instructions to the AI.

### Document extraction (`document_processor.py`)
- Better page, slide, paragraph, row and sheet location markers.
- Optional OCR attempt for scanned PDF pages using pytesseract.
- Existing PDF, Word, PowerPoint, Excel, CSV, Markdown and text support remains.
- Legacy `.doc` and `.ppt` conversion still requires LibreOffice.

### Database (`db.py`)
- Added `project_memory`, `ai_analysis_history` and `human_corrections` tables.
- Existing tables and records are preserved; tables are created automatically on app startup.
- Human corrections are stored separately so original evidence is not overwritten. The existing UI does not yet expose a correction editor.

### Existing functionality intentionally unchanged
- Login and account roles.
- Authority Mode and User Mode.
- Handover request and permission-confirmation flow.
- Individual supporting-file and supporting-folder uploads.
- Document approval controls.
- Existing report display and PDF download.
- Existing API-integration controls and other non-AI frontend screens.

## Setup (Windows / VS Code)

1. Extract this ZIP and open the extracted folder in VS Code.
2. Open a terminal in the project folder.
3. Create a virtual environment:

   ```powershell
   python -m venv .venv
   ```

4. Activate it:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt instead:

   ```cmd
   .venv\Scripts\activate.bat
   ```

5. Upgrade pip and install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

6. Copy `.env.example` to `.env` and add your own OpenAI API key:

   ```text
   OPENAI_API_KEY=your_api_key_here
   ```

   Keep `.env` private. Do not upload it or share it. The model and embedding model can be changed in `.env` if your account has access to different models.

7. Run the app:

   ```powershell
   python -m streamlit run app.py
   ```

   Or use `run_windows.bat` after activating the virtual environment.

## OCR setup (optional)

Normal text-based PDFs work without extra OCR setup. For scanned PDFs, install the Tesseract OCR application for Windows and ensure `tesseract.exe` is available on PATH. The Python packages `pytesseract` and `Pillow` are installed from `requirements.txt`. If Tesseract is not installed or OCR fails, the app continues with ordinary text extraction and reports that page text may be unavailable.

## AI behaviour and costs

- A valid OpenAI API key and model access are required for AI analysis.
- Semantic retrieval uses the OpenAI embeddings API and therefore may incur API usage charges in addition to report-generation usage.
- ChromaDB stores request-scoped vector data locally in `vector_store/`.
- Without an API key, or if AI processing fails, Handoverly generates a clearly labelled non-AI fallback report.
- Only authority-approved documents and task records allowed by the request's task-sharing setting are included.
- Evidence retrieval improves access to long documents but cannot guarantee that every relevant passage is retrieved. Review the generated report and its source references before relying on it.

## Data and backups

- SQLite data is stored in `employee_handover.db`.
- Uploaded files are stored in `uploads/`.
- Semantic vectors are stored in `vector_store/`.
- Back up these items securely if you need to retain project data. Do not share them publicly.
- The database schema additions are created automatically by `init_db()` without deleting existing V4 records.

## Demo sign-in

| Account | Name | Employee ID | Password |
|---|---|---|---|
| Authority | Authority Admin | AUTH-001 | admin123 |
| Incoming employee | 123 | EMP-123 | user123 |

These are prototype credentials. Change them before any real deployment.

## Important prototype limitations

- This is still a local Streamlit prototype, not a production security certification.
- Human correction records have database support but no correction-management screen yet.
- The interactive employee Q&A assistant is not added in this backend-only upgrade; it would require a new frontend interaction. The V4 screens and workflows have deliberately been left unchanged.
- OCR currently attempts scanned PDF pages; it does not perform full OCR of every embedded image in Word or PowerPoint files.
- Real production use requires stronger authentication/password hashing, secure deployment, backups, access-control testing, and review of organisational privacy requirements.

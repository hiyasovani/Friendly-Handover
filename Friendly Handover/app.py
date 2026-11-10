import os
import re
import base64
from pathlib import Path, PureWindowsPath
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from dotenv import load_dotenv

from db import (
    init_db, get_connection, get_user_by_login, get_user_by_id, get_employees,
    get_projects, get_tasks, create_request, add_document,
    get_requests_for_employee, get_all_requests, get_request, get_documents,
    approve_request, reject_request, get_report, log_action
)
from document_processor import extract_text, safe_filename
from ai_engine import generate_report
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

APP_DIR = Path(__file__).parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ORG_ID = "friendly-handover-local"

st.set_page_config(page_title="Friendly Handover", page_icon="🤝", layout="wide")
load_dotenv(APP_DIR / ".env")


def load_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] {font-family:Inter,sans-serif;}
    .stApp {background:#f5f7fc;color:#17233d;}
    .block-container {max-width:1180px;padding-top:1.6rem;padding-bottom:3rem;}
    header[data-testid="stHeader"] {background:rgba(245,247,252,.94);}
    h1,h2,h3 {color:#17233d;}
    .brandline {font-size:22px;font-weight:800;color:#20346f;letter-spacing:-.5px;}
    .hero {background:linear-gradient(120deg,#243b83,#4059b9);color:white;padding:28px 30px;border-radius:18px;}
    .hero h2,.hero p {color:white;}
    .subtle {color:#64748b;font-size:13px;}
    div[data-testid="stFileUploader"] {background:#fff;border:1px dashed #9aaed2;border-radius:12px;padding:10px;}
    .stButton>button {border-radius:9px;min-height:40px;}
    .stButton>button[kind="primary"] {background:#3855bd;border:0;}
    [data-testid="stMetric"] {background:white;border:1px solid #e4e9f2;padding:12px;border-radius:12px;}
    </style>
    """, unsafe_allow_html=True)

def header():
    st.markdown('<div class="brandline">🤝 Friendly Handover</div>', unsafe_allow_html=True)
    st.caption("A permission-first workspace for clear, evidence-based employee transitions.")

def logout():
    for key in list(st.session_state.keys()):
        if key not in ("_streamlit"):
            st.session_state.pop(key, None)
    st.rerun()

def login_screen():
    header()
    st.write("")
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown("""
        <div class="hero">
          <div style="font-size:13px;letter-spacing:1.5px;font-weight:700;">WORK CONTINUITY, MADE CLEAR</div>
          <h2 style="font-size:32px;margin-top:22px;">A smoother handover starts here.</h2>
          <p style="line-height:1.8;">Collect authorised project material, review access, and prepare a useful handover for the next person.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        st.info("The authority controls which files and connected sources may be included in each handover.")
    with right:
        with st.container(border=True):
            st.subheader("Sign in")
            mode = st.radio("Account type", ["Employee", "Authority"], horizontal=True)
            with st.form("login_form"):
                st.caption("Demo sign-in details are given below the sign-in box in the format: Name | Employee ID | Password.")
                name = st.text_input("Name", placeholder="e.g. 123 or Authority Admin")
                employee_id = st.text_input("Employee ID", placeholder="e.g. EMP-123 or AUTH-001")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if submitted:
                role = "authority" if mode == "Authority" else "employee"
                user = get_user_by_login(employee_id, name, password, role)
                if user:
                    st.session_state.user = user
                    log_action(user["id"], "Login", f"{role} login")
                    st.rerun()
                else:
                    st.error("The details do not match an active account.")
        with st.expander("Demo sign-in details"):
            st.write("Authority: Authority Admin | AUTH-001 | admin123")
            st.write("Incoming employee: 123 | EMP-123 | user123")


def report_pdf_bytes(report_text: str, request_id: int) -> bytes:
    """Render the saved handover report as a downloadable PDF."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=19*mm, leftMargin=19*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title=f"Friendly Handover Report - Request {request_id}"
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitleFH", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=19, leading=23, textColor=colors.HexColor("#20346f"),
        alignment=TA_CENTER, spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name="ReportH2FH", parent=styles["Heading2"], fontSize=12,
        leading=15, textColor=colors.HexColor("#263b78"),
        spaceBefore=10, spaceAfter=5
    ))
    styles.add(ParagraphStyle(
        name="ReportBodyFH", parent=styles["BodyText"], fontSize=9,
        leading=13, spaceAfter=5
    ))
    story = [
        Paragraph("Friendly Handover Report", styles["ReportTitleFH"]),
        Paragraph(f"Request #{request_id}", styles["ReportBodyFH"]),
        HRFlowable(width="100%", color=colors.HexColor("#d7deed")),
        Spacer(1, 8)
    ]
    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["ReportTitleFH"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["ReportH2FH"]))
        elif line.startswith(("- ", "* ")):
            body = escape(line[2:])
            body = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", body)
            story.append(Paragraph("&#8226; " + body, styles["ReportBodyFH"]))
        else:
            body = escape(line)
            body = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", body)
            body = re.sub(r"\*(.*?)\*", r"<i>\1</i>", body)
            story.append(Paragraph(body, styles["ReportBodyFH"]))
    doc.build(story)
    return buffer.getvalue()

def resolve_stored_document_path(stored_path: str):
    """Resolve document paths saved on this machine or an earlier Windows machine."""
    if not stored_path:
        return None
    candidate = Path(stored_path)
    if candidate.is_file():
        return candidate
    # Older database rows may contain absolute Windows paths from the machine
    # on which the project was first run. The ZIP carries the files in uploads/.
    old_basename = PureWindowsPath(str(stored_path)).name or candidate.name
    for name in (old_basename, candidate.name):
        if name:
            fallback = UPLOAD_DIR / name
            if fallback.is_file():
                return fallback
    return None


def render_pdf_preview(pdf_bytes: bytes, height: int = 620):
    """Show an inline PDF preview in the employee dashboard."""
    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    html = (
        '<iframe src="data:application/pdf;base64,' + encoded + '" '
        'width="100%" height="' + str(height) + 'px" '
        'style="border:1px solid #d9deea;border-radius:10px;" '
        'type="application/pdf"></iframe>'
    )
    components.html(html, height=height + 12, scrolling=True)


def employee_workspace(user):
    header()
    st.title(f"Welcome, {user['name']}")
    st.write("Create one or more handover requests. The authority will upload and review the material for each request.")
    projects = get_projects()
    if not projects:
        st.warning("No project has been configured yet.")
        return
    project = projects[0]
    employees = get_employees()
    existing_requests = get_requests_for_employee(user["id"])
    tasks = get_tasks(project["id"], user["employee_id"])
    # Determine the outgoing employee from project task ownership rather than
    # asking the incoming employee to choose someone from a dropdown.
    project_tasks = get_tasks(project["id"])
    ownership_counts = {}
    for task in project_tasks:
        owner_id = task.get("owner_employee_id")
        if owner_id and owner_id != user["employee_id"]:
            ownership_counts[owner_id] = ownership_counts.get(owner_id, 0) + 1
    outgoing_id = max(ownership_counts, key=ownership_counts.get) if ownership_counts else None
    outgoing = next((e for e in employees if e["employee_id"] == outgoing_id), None)
    with st.container(border=True):
        st.subheader("Role transition")
        st.caption("Your responsibilities and the roles of colleagues in your department")
        st.write(f"**Your role:** {user.get('designation') or 'Employee'} · **Department:** {user.get('department') or 'Not specified'}")
        st.markdown("**Department team roles**")
        team = [e for e in employees if e["department"] == user.get("department")]
        if team:
            st.dataframe(pd.DataFrame([{'Employee': e['name'], 'Role / Designation': e['designation'], 'Department': e['department']} for e in team]), use_container_width=True, hide_index=True)
        else:
            st.write("No other employee roles are currently listed for this department.")
        st.markdown("**Your current project tasks**")
        if tasks:
            for task in tasks:
                st.write(f"**{task['title']}** · {task['status']}")
        else:
            st.write("No task records are currently available.")
    with st.container(border=True):
        st.subheader("Request a handover")
        if not outgoing:
            st.info("No employee has been assigned as the outgoing owner of this project yet. Please ask the authority to configure the project task ownership.")
        else:
            st.markdown("**Employee to be replaced**")
            st.write(f"{outgoing['name']} — {outgoing['designation'] or 'Designation not specified'}")
            st.caption("The outgoing employee is identified from the current project task ownership. You do not need to select an employee.")
            st.caption("Files and folders are uploaded by the authority after reviewing your request.")
            if st.button("Request Handover data", type="primary", use_container_width=True):
                st.session_state["confirm_handover_request"] = True
            if st.session_state.get("confirm_handover_request", False):
                @st.dialog("Confirm handover data request")
                def confirm_request_dialog():
                    st.write(f"Send a request to the authority for handover data from **{outgoing['name']}** ({outgoing['designation'] or 'Designation not specified'})?")
                    st.caption("You may submit more than one request. Each request will be tracked separately.")
                    yes, no = st.columns(2)
                    if yes.button("Confirm request", type="primary", use_container_width=True):
                        request_id = create_request(user["id"], outgoing["employee_id"], project["id"])
                        log_action(user["id"], "Handover request created", f"Request {request_id}")
                        st.session_state["confirm_handover_request"] = False
                        st.rerun()
                    if no.button("Cancel", use_container_width=True):
                        st.session_state["confirm_handover_request"] = False
                        st.rerun()
                confirm_request_dialog()
    st.subheader("Your handover requests")
    requests = get_requests_for_employee(user["id"])
    if not requests:
        st.info("You have not submitted a request yet.")
    for req in requests:
        with st.expander(f"Request #{req['id']} · {req['project_name']} · {req['status']}"):
            st.write(f"Outgoing employee: {req['outgoing_name']}")
            st.write(f"Submitted: {req['created_at']}")
            if req["status"] == "Pending":
                st.info("Waiting for the authority to upload and approve the sources.")
            elif req["status"] == "Rejected":
                st.error("The authority did not approve this request.")
            else:
                st.success("Permission granted")
                st.markdown(
                    f"<style>.st-key-employee_permission_granted_{req['id']} button "
                    "{background:#16a34a !important;color:white !important;"
                    "border:1px solid #16a34a !important;opacity:1 !important;}"
                    "</style>", unsafe_allow_html=True
                )
                st.button(
                    "Permission Granted", disabled=True, use_container_width=True,
                    key=f"employee_permission_granted_{req['id']}"
                )
                # Only documents explicitly approved by the authority are visible
                # and downloadable by the incoming employee.
                approved_docs = [d for d in get_documents(req["id"]) if d.get("approved")]
                if approved_docs:
                    st.markdown("**Approved handover documents**")
                    for doc in approved_docs:
                        doc_path = resolve_stored_document_path(doc.get("stored_path", ""))
                        if doc_path is not None:
                            try:
                                file_data = doc_path.read_bytes()
                                file_ext = doc_path.suffix.lower()
                                mime_type = "application/pdf" if file_ext == ".pdf" else "application/octet-stream"
                                st.download_button(
                                    f"Download {doc['filename']}",
                                    data=file_data,
                                    file_name=Path(doc["filename"]).name,
                                    mime=mime_type,
                                    key=f"employee_doc_{req['id']}_{doc['id']}"
                                )
                                if file_ext == ".pdf":
                                    with st.expander(f"View PDF: {doc['filename']}", expanded=False):
                                        render_pdf_preview(file_data)
                            except OSError:
                                st.warning(f"The file {doc['filename']} could not be read. Please ask the authority to upload it again.")
                        else:
                            st.warning(f"The file {doc['filename']} could not be found in the project's uploads folder. Please ask the authority to upload it again.")
                else:
                    st.info("No individual handover documents were approved for download.")
                report = get_report(req["id"])
                if report:
                    st.markdown(report["report_text"])
                    st.download_button(
                        "Download handover report (PDF)",
                        data=report_pdf_bytes(report["report_text"], req["id"]),
                        file_name=f"friendly_handover_{req['id']}.pdf",
                        mime="application/pdf",
                        key=f"employee_report_pdf_{req['id']}"
                    )
                else:
                    st.info("AI is working... Your handover PDF will appear here as soon as the report is ready.")

def save_authority_uploads(request_id, user_id, handover_file, supporting_files=None, supporting_folder_files=None):
    """Save the handover paper plus individual supporting files and folder contents."""
    uploaded = []
    if handover_file is not None:
        uploaded.append((handover_file, True))
    uploaded.extend((f, False) for f in (supporting_files or []))
    uploaded.extend((f, False) for f in (supporting_folder_files or []))
    if not uploaded:
        return 0
    saved = 0
    for item, is_paper in uploaded:
        original_name = safe_filename(item.name)
        unique = f"req{request_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{original_name}"
        path = UPLOAD_DIR / unique
        raw = item.getvalue()
        path.write_bytes(raw)
        try:
            extracted = extract_text(str(path), path.suffix.lower())
        except Exception as exc:
            extracted = f"[Text extraction failed: {type(exc).__name__}]"
        add_document(request_id, user_id, item.name, str(path), path.suffix.lower(),
                     extracted, is_handover_paper=is_paper)
        saved += 1
    return saved


def authority_workspace(user):
    header()
    st.title("Authority dashboard")
    st.caption("Add handover material and grant permission before a report is prepared.")
    requests = get_all_requests()
    pending = [r for r in requests if r["status"] == "Pending"]
    approved = [r for r in requests if r["status"] == "Approved"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Total requests", len(requests))
    c2.metric("Pending review", len(pending))
    c3.metric("Approved", len(approved))
    if not requests:
        st.info("No handover requests have been submitted.")
        return

    labels = {
        f"Request #{r['id']} · {r['requester_name']} ({r['requester_employee_id']}) · {r['status']}": r["id"]
        for r in requests
    }
    label = st.selectbox("Choose a handover request", list(labels))
    request_id = labels[label]
    req = get_request(request_id)
    docs = get_documents(request_id)
    st.divider()
    st.subheader(f"Request #{request_id}")
    a, b, c = st.columns(3)
    a.write(f"**Incoming:** {req['requester_name']}")
    b.write(f"**Outgoing:** {req['outgoing_employee_id']}")
    c.write(f"**Project:** {req['project_name']}")

    # The authority who uploaded the source material can always review it here,
    # regardless of whether the request is pending or already approved.
    with st.container(border=True):
        st.subheader("Documents sent by the authority")
        if not docs:
            st.info("No documents have been uploaded for this request yet.")
        else:
            st.caption("You can preview PDF files and download every document attached to this request.")
            for doc in docs:
                doc_path = resolve_stored_document_path(doc.get("stored_path", ""))
                with st.expander(f"{doc['filename']}  ·  {'Handover paper' if doc['is_handover_paper'] else 'Supporting document'}", expanded=False):
                    if doc_path and doc_path.is_file():
                        try:
                            file_bytes = doc_path.read_bytes()
                            suffix = doc_path.suffix.lower()
                            mime_type = {
                                ".pdf": "application/pdf",
                                ".doc": "application/msword",
                                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                ".txt": "text/plain",
                                ".md": "text/markdown",
                                ".csv": "text/csv",
                                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                ".ppt": "application/vnd.ms-powerpoint",
                                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            }.get(suffix, "application/octet-stream")
                            st.download_button(
                                "Download document", data=file_bytes,
                                file_name=doc["filename"], mime=mime_type,
                                key=f"authority_download_{request_id}_{doc['id']}"
                            )
                            if suffix == ".pdf":
                                st.markdown("**PDF preview**")
                                render_pdf_preview(file_bytes, height=650)
                            else:
                                st.caption("Inline preview is available for PDF files. Download this file to open it in its supported application.")
                        except OSError as exc:
                            st.error(f"Could not read this document: {exc}")
                    else:
                        st.warning("This document could not be found in the project's uploads folder. Please upload it again.")

    # Approved requests are handled by the main request workflow below as well,
    # so show the saved AI report here rather than in a later unreachable elif.
    if req["status"] == "Approved":
        st.markdown(
            f"<style>.st-key-permission_granted_{request_id} button "
            "{background:#16a34a !important;color:white !important;"
            "border:1px solid #16a34a !important;opacity:1 !important;}"
            "</style>", unsafe_allow_html=True
        )
        st.button("Permission Granted", disabled=True, use_container_width=True,
                  key=f"permission_granted_{request_id}")
        report = get_report(request_id)
        if report:
            st.divider()
            st.subheader("Generated handover report")
            st.markdown(report["report_text"])
            pdf_data = report_pdf_bytes(report["report_text"], request_id)
            st.download_button(
                "Download handover report (PDF)",
                data=pdf_data,
                file_name=f"friendly_handover_{request_id}.pdf",
                mime="application/pdf",
                key=f"admin_pdf_{request_id}"
            )
            with st.expander("Preview generated PDF", expanded=True):
                render_pdf_preview(pdf_data, height=700)
        else:
            st.warning("Permission was granted, but the report is not available yet.")
            if st.button("Prepare handover report", type="primary", key=f"prepare_report_{request_id}"):
                with st.spinner("AI is working... Compiling the handover summary and preparing the PDF."):
                    generate_report(request_id)
                st.success("Handover report is ready.")
                st.rerun()

    # API connections are intentionally disabled in this version.
    st.checkbox(
        "API integrations permission (currently not functioning)",
        value=False, disabled=True, key=f"api_disabled_{request_id}"
    )

    if req["status"] in ("Pending", "Approved"):
        if req["status"] == "Approved":
            st.info("This request is already approved. You may upload additional material and update the approved document selection by granting permission again.")
        with st.container(border=True):
            st.subheader("Add handover material")
            st.caption("Upload the handover paper, multiple individual supporting files, or an entire supporting folder. Supporting material is optional. Google Docs and Slides should be downloaded/exported as Word (.docx) or PowerPoint (.pptx) files first.")
            st.caption("Accepted file types: PDF, DOC, DOCX, TXT, MD, CSV, XLSX, PPT, PPTX")
            handover_file = st.file_uploader(
                "Handover paper — drag and drop or browse",
                type=["pdf", "doc", "docx", "txt", "md", "csv", "xlsx", "ppt", "pptx"],
                key=f"paper_{request_id}"
            )
            supporting_files = st.file_uploader(
                "Supporting individual files (optional) — select multiple files",
                type=["pdf", "doc", "docx", "txt", "md", "csv", "xlsx", "ppt", "pptx"],
                accept_multiple_files=True, key=f"supporting_files_{request_id}"
            )
            supporting_folder_files = st.file_uploader(
                "Supporting folder (optional) — select an entire folder",
                type=["pdf", "doc", "docx", "txt", "md", "csv", "xlsx", "ppt", "pptx"],
                accept_multiple_files="directory", key=f"supporting_folder_{request_id}"
            )
            if st.button("Upload material", type="primary", key=f"save_upload_{request_id}"):
                if handover_file is None:
                    st.error("Please add the handover paper. Supporting files are optional.")
                else:
                    st.session_state[f"confirm_upload_{request_id}"] = True
            if st.session_state.get(f"confirm_upload_{request_id}", False):
                @st.dialog("Confirm upload material")
                def confirm_upload_dialog():
                    st.write("Confirm that you want to save the selected handover paper, individual supporting files, and folder contents for this request?")
                    yes, no = st.columns(2)
                    if yes.button("Confirm upload", type="primary", use_container_width=True):
                        saved = save_authority_uploads(
                            request_id, user["id"], handover_file,
                            supporting_files, supporting_folder_files
                        )
                        log_action(user["id"], "Authority uploaded sources", f"Request {request_id}; {saved} files")
                        st.session_state[f"confirm_upload_{request_id}"] = False
                        st.rerun()
                    if no.button("Cancel", use_container_width=True):
                        st.session_state[f"confirm_upload_{request_id}"] = False
                        st.rerun()
                confirm_upload_dialog()

        docs = get_documents(request_id)
        handover_docs = [d for d in docs if d["is_handover_paper"]]
        if docs:
            st.caption("Files added to this request:")
            for doc in docs:
                st.write(f"• {doc['filename']}")

        with st.container(border=True):
            st.subheader("Grant permission")
            st.caption("All material added to this request will be processed only after you confirm permission.")
            if not handover_docs:
                st.warning("Upload a handover paper before granting permission.")
            selected_doc_ids = [d["id"] for d in docs]
            can_grant = bool(handover_docs)
            if st.button("Grant permission", type="primary", disabled=not can_grant,
                         key=f"grant_start_{request_id}"):
                st.session_state[f"grant_confirm_pending_{request_id}"] = True
                st.rerun()

            if st.session_state.get(f"grant_confirm_pending_{request_id}", False):
                st.warning(
                    "Please confirm: the selected handover paper and supporting documents "
                    "will be processed to prepare a report for the incoming employee."
                )
                grant_check = st.checkbox(
                    "I confirm that the selected documents may be processed and shared for this handover.",
                    key=f"grant_check_{request_id}"
                )
                if st.button("Confirm permission", type="primary", key=f"grant_final_{request_id}"):
                    if not grant_check:
                        st.error("Please tick the confirmation box before proceeding.")
                    else:
                        try:
                            approve_request(request_id, user["id"], selected_doc_ids, share_tasks=True)
                            log_action(
                                user["id"], "Permission granted",
                                f"Request {request_id}; documents={selected_doc_ids}; API integrations disabled"
                            )
                            st.session_state[f"grant_confirm_pending_{request_id}"] = False
                            with st.spinner("AI is working... Compiling the handover summary and preparing the PDF."):
                                report_text = generate_report(request_id)
                                pdf_data = report_pdf_bytes(report_text, request_id)
                            st.success("Permission granted. The handover report is ready for both admin and employee.")
                            if not os.getenv("OPENAI_API_KEY", "").strip():
                                st.info(
                                    "OpenAI API key is not configured. The app used its built-in "
                                    "evidence-based report generator. Add OPENAI_API_KEY to enable "
                                    "LLM-generated analysis."
                                )
                            st.download_button(
                                "Download handover report (PDF)",
                                data=pdf_data,
                                file_name=f"friendly_handover_{request_id}.pdf",
                                mime="application/pdf",
                                key=f"admin_pdf_{request_id}"
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Report preparation failed: {type(exc).__name__}: {exc}")
                            st.info("Check the uploaded documents and try granting permission again.")
            if st.button("Reject request", key=f"reject_{request_id}"):
                reject_request(request_id, user["id"])
                log_action(user["id"], "Permission rejected", f"Request {request_id}")
                st.rerun()

    else:
        st.error("This request was rejected.")

    with st.expander("Recent activity log"):
        conn = get_connection()
        rows = conn.execute(
            """SELECT a.created_at,u.name AS actor,a.action,a.details
            FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id
            ORDER BY a.id DESC LIMIT 30"""
        ).fetchall()
        conn.close()
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)
        else:
            st.caption("No activity recorded.")

def main():
    init_db()
    load_css()
    if "user" not in st.session_state:
        login_screen()
        return
    user = get_user_by_id(st.session_state.user["id"])
    if not user or not user["is_active"]:
        st.session_state.pop("user", None)
        st.error("This account is inactive. Sign in again.")
        st.rerun()
    with st.sidebar:
        st.markdown("## 🤝 Friendly Handover")
        st.write(user["name"])
        st.caption(user["role"].title())
        if st.button("Log out", use_container_width=True):
            logout()
    if user["role"] == "authority":
        authority_workspace(user)
    else:
        employee_workspace(user)

if __name__ == "__main__":
    main()

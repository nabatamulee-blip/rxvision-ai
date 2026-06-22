from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class PrescriptionRecord(Base):
    __tablename__ = "prescription_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    ai_json: Mapped[str] = mapped_column(Text)
    verified_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

class MedicineAlternative(BaseModel):
    name: str
    confidence: int = Field(ge=0, le=100)

class MedicineItem(BaseModel):
    raw_observed_text: str
    predicted_name: str
    confidence: int = Field(ge=0, le=100)
    alternatives: List[MedicineAlternative] = []
    dosage: str = ""
    frequency: str = ""
    duration: str = ""
    route: str = ""
    remarks: str = ""
    uncertainty_reason: str = ""

class PrescriptionResult(BaseModel):
    patient_name: str = ""
    doctor_name: str = ""
    date: str = ""
    overall_confidence: int = Field(ge=0, le=100)
    medicines: List[MedicineItem] = []
    warning_flags: List[str] = []
    clarification_questions: List[str] = []
    summary: str = ""

class AnalyzeResponse(BaseModel):
    record_id: int
    filename: str
    preview_url: str
    result: PrescriptionResult

class VerifyRequest(BaseModel):
    result: PrescriptionResult

app = FastAPI(title="RxVision AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def save_upload(file: UploadFile, content: bytes) -> Path:
    ext = Path(file.filename or "upload").suffix.lower()
    safe_name = f"{uuid.uuid4().hex}{ext or '.bin'}"
    out_path = UPLOAD_DIR / safe_name
    out_path.write_bytes(content)
    return out_path

def convert_pdf_first_page_to_image(pdf_bytes: bytes) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count == 0:
        raise ValueError("PDF has no pages")
    page = doc.load_page(0)
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    png_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")

def bytes_to_pil(file: UploadFile, content: bytes) -> Image.Image:
    name = (file.filename or "").lower()
    if name.endswith(".pdf") or file.content_type == "application/pdf":
        img = convert_pdf_first_page_to_image(content)
    else:
        img = Image.open(io.BytesIO(content)).convert("RGB")
    
    # Resize image to speed up upload and Gemini processing
    img.thumbnail((1600, 1600), Image.Resampling.BILINEAR)
    return img

def build_prompt() -> str:
    return """
You are RxVision AI, a prescription interpretation assistant for pharmacists.

Task:
Read the uploaded prescription image carefully and extract the most likely medicines and instructions.

Rules:
- Do not hallucinate.
- If unsure, provide alternatives and reduce confidence.
- Extract only what is visible or strongly inferable from the prescription.
- Keep output strictly aligned to the JSON schema.
- For each medicine, include:
  raw_observed_text
  predicted_name
  confidence (0-100)
  alternatives (list of up to 3)
  dosage
  frequency
  duration
  route
  remarks
  uncertainty_reason
- If patient or doctor name is not visible, leave blank.
- Add warning flags if handwriting is too unclear, dose seems unusual, or multiple interpretations are possible.
- Add clarification questions only if necessary.
- Never advise dispensing without human confirmation.
- Return concise, clinically useful structured data only.
""".strip()

def analyze_with_gemini(image: Image.Image) -> PrescriptionResult:
    if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_API_KEY_HERE":
        # Return mock data for demonstration
        return PrescriptionResult(
            patient_name="John Doe (Mock)",
            doctor_name="Dr. Smith",
            date="2026-06-20",
            overall_confidence=75,
            medicines=[
                MedicineItem(
                    raw_observed_text="Amoxicillin 500mg",
                    predicted_name="Amoxicillin",
                    confidence=80,
                    dosage="500mg",
                    frequency="1 tablet 3 times a day",
                    duration="7 days",
                    route="Oral",
                    remarks="Take after meals",
                    uncertainty_reason="Handwriting slightly blurred"
                )
            ],
            warning_flags=["API Key missing - using mock data"],
            clarification_questions=[],
            summary="Mock prescription successfully analyzed."
        )

    client = genai.Client(api_key=GOOGLE_API_KEY)

    schema = PrescriptionResult

           response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[image, build_prompt()],
        config=types.GenerateContentConfig(
            temperature=0.0,  # 0.0 forces 100% deterministic output
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
            build_prompt()
        ],
        config=types.GenerateContentConfig(
            temperature=0.0,  # 0.0 forces 100% deterministic output (stops changing scores!)
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )

    raw = response.text or "{}"
    try:
        return PrescriptionResult.model_validate_json(raw)
    except Exception:
        # Fallback: try to extract first JSON object
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return PrescriptionResult.model_validate_json(raw[start : end + 1])
        raise

@app.get("/health")
def health():
    return {"status": "ok", "service": "RxVision AI"}

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    try:
        image = bytes_to_pil(file, content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unsupported or invalid file: {e}")

    saved_path = save_upload(file, content)
    result = analyze_with_gemini(image)

    db = SessionLocal()
    try:
        record = PrescriptionRecord(
            filename=file.filename,
            file_path=str(saved_path),
            mime_type=file.content_type or "application/octet-stream",
            ai_json=result.model_dump_json(),
            verified=False,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return AnalyzeResponse(
            record_id=record.id,
            filename=record.filename,
            preview_url=f"/files/{record.id}",
            result=result,
        )
    finally:
        db.close()

@app.get("/files/{record_id}")
def get_file(record_id: int):
    db = SessionLocal()
    try:
        record = db.get(PrescriptionRecord, record_id)
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        return JSONResponse(
            {
                "record_id": record.id,
                "filename": record.filename,
                "file_path": record.file_path,
                "mime_type": record.mime_type,
            }
        )
    finally:
        db.close()

@app.get("/records")
def list_records():
    db = SessionLocal()
    try:
        rows = db.query(PrescriptionRecord).order_by(PrescriptionRecord.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "filename": r.filename,
                "verified": r.verified,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        db.close()

@app.get("/records/{record_id}")
def get_record(record_id: int):
    db = SessionLocal()
    try:
        r = db.get(PrescriptionRecord, record_id)
        if not r:
            raise HTTPException(status_code=404, detail="Record not found")
        return {
            "id": r.id,
            "filename": r.filename,
            "verified": r.verified,
            "created_at": r.created_at.isoformat(),
            "ai_json": json.loads(r.ai_json),
            "verified_json": json.loads(r.verified_json) if r.verified_json else None,
        }
    finally:
        db.close()

@app.post("/records/{record_id}/confirm")
def confirm_record(record_id: int, body: VerifyRequest):
    db = SessionLocal()
    try:
        r = db.get(PrescriptionRecord, record_id)
        if not r:
            raise HTTPException(status_code=404, detail="Record not found")
        r.verified_json = body.result.model_dump_json()
        r.verified = True
        db.add(r)
        db.commit()
        return {"status": "saved", "record_id": record_id}
    finally:
        db.close()

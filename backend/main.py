import io
import os
import fitz
import uuid
import json
from pathlib import Path
from typing import List, Optional
from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
from google import genai
from google.genai import types

# ---- Config & DB Setup ----
class Settings(BaseSettings):
    google_api_key: str = "YOUR_API_KEY_HERE"
    database_url: str = "sqlite:///./rxvision.db"
    frontend_origin: str = "http://localhost:5173"
    gemini_model: str = "gemini-1.5-flash"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", settings.google_api_key)
DATABASE_URL = os.getenv("DATABASE_URL", settings.database_url)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", settings.frontend_origin)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", settings.gemini_model)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PrescriptionRecord(Base):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    file_path = Column(String)
    mime_type = Column(String)
    ai_json = Column(String)
    verified_json = Column(String, nullable=True)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ---- Models ----
class MedicineItem(BaseModel):
    raw_observed_text: str = Field(..., description="Exact text seen on image")
    predicted_name: str = Field(..., description="Likely standard name of the medicine")
    confidence: int = Field(..., description="0-100 confidence score")
    alternatives: List[str] = Field(default_factory=list, description="Alternative interpretations if unclear")
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    route: Optional[str] = None
    remarks: Optional[str] = None
    uncertainty_reason: Optional[str] = None

class PrescriptionResult(BaseModel):
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    date: Optional[str] = None
    overall_confidence: int
    medicines: List[MedicineItem]
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
            temperature=0.0,
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

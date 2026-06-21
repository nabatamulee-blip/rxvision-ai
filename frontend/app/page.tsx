"use client";

import { useMemo, useState } from "react";

type Alternative = {
  name: string;
  confidence: number;
};

type MedicineItem = {
  raw_observed_text: string;
  predicted_name: string;
  confidence: number;
  alternatives: Alternative[];
  dosage: string;
  frequency: string;
  duration: string;
  route: string;
  remarks: string;
  uncertainty_reason: string;
};

type PrescriptionResult = {
  patient_name: string;
  doctor_name: string;
  date: string;
  overall_confidence: number;
  medicines: MedicineItem[];
  warning_flags: string[];
  clarification_questions: string[];
  summary: string;
};

type AnalyzeResponse = {
  record_id: number;
  filename: string;
  preview_url: string;
  result: PrescriptionResult;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://10.175.138.27:8000";

function confidenceClass(score: number) {
  if (score >= 85) return "bg-emerald-100 text-emerald-800 border-emerald-200";
  if (score >= 60) return "bg-amber-100 text-amber-800 border-amber-200";
  return "bg-rose-100 text-rose-800 border-rose-200";
}

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [recordId, setRecordId] = useState<number | null>(null);
  const [result, setResult] = useState<PrescriptionResult | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const overallClass = useMemo(
    () => (result ? confidenceClass(result.overall_confidence) : ""),
    [result]
  );

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] || null;
    setError("");
    setResult(null);
    setRecordId(null);
    setFile(selected);

    if (selected) {
      const url = URL.createObjectURL(selected);
      setPreview(url);
    } else {
      setPreview("");
    }
  }

  function compressImage(file: File): Promise<Blob> {
    return new Promise((resolve) => {
      if (!file.type.startsWith("image/")) {
        resolve(file);
        return;
      }
      const img = new Image();
      img.src = URL.createObjectURL(file);
      img.onload = () => {
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d");
        const MAX_WIDTH = 1200;
        const MAX_HEIGHT = 1200;
        let width = img.width;
        let height = img.height;

        if (width > height) {
          if (width > MAX_WIDTH) {
            height *= MAX_WIDTH / width;
            width = MAX_WIDTH;
          }
        } else {
          if (height > MAX_HEIGHT) {
            width *= MAX_HEIGHT / height;
            height = MAX_HEIGHT;
          }
        }
        canvas.width = width;
        canvas.height = height;
        ctx?.drawImage(img, 0, 0, width, height);
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else resolve(file);
        }, "image/jpeg", 0.7);
      };
      img.onerror = () => resolve(file);
    });
  }

  async function analyze() {
    if (!file) {
      setError("Please upload a prescription image or PDF.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const compressedBlob = await compressImage(file);
      const form = new FormData();
      form.append("file", compressedBlob, file.name);

      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || "Analysis failed");
      }

      const data = (await res.json()) as AnalyzeResponse;
      setRecordId(data.record_id);
      setResult(data.result);
    } catch (err: any) {
      setError(err?.message || "Something went wrong during analysis.");
    } finally {
      setLoading(false);
    }
  }

  function updateMedicine(index: number, field: keyof MedicineItem, value: string) {
    if (!result) return;
    const next = { ...result };
    const meds = [...next.medicines];
    meds[index] = { ...meds[index], [field]: value } as MedicineItem;
    next.medicines = meds;
    setResult(next);
  }

  async function saveVerified() {
    if (!result || recordId == null) return;
    setSaving(true);
    setError("");

    try {
      const res = await fetch(`${API_BASE}/records/${recordId}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result }),
      });

      if (!res.ok) throw new Error("Could not save verified prescription.");
      alert("Verified prescription saved.");
    } catch (err: any) {
      setError(err?.message || "Could not save verified prescription.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-3">
            <p className="text-sm font-semibold uppercase tracking-wide text-sky-600">
              RxVision AI
            </p>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">
              Prescription Interpreter for Pharmacists
            </h1>
            <p className="max-w-3xl text-slate-600">
              Upload a handwritten prescription, review the AI interpretation,
              correct anything uncertain, and save the verified version.
            </p>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-4">
              <h2 className="text-lg font-semibold text-slate-900">1. Upload prescription</h2>
              <p className="text-sm text-slate-500">
                JPG, PNG, WEBP, or PDF. The first page of a PDF will be scanned.
              </p>
            </div>

            <label className="flex min-h-[240px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-6 text-center hover:border-sky-400 hover:bg-sky-50">
              <input
                type="file"
                accept="image/*,application/pdf"
                className="hidden"
                onChange={onFileChange}
              />
              <div className="max-w-md">
                <div className="mb-3 text-4xl">📄</div>
                <p className="text-base font-medium text-slate-800">
                  Drop a prescription here or click to browse
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  Best results: clear photo, flat surface, good lighting.
                </p>
              </div>
            </label>

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                onClick={analyze}
                disabled={loading || !file}
                className="rounded-xl bg-sky-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {loading ? "Analyzing... (can take 10-20s)" : "Scan Prescription"}
              </button>

              <button
                onClick={() => {
                  setFile(null);
                  setPreview("");
                  setResult(null);
                  setRecordId(null);
                  setError("");
                }}
                className="rounded-xl border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                Reset
              </button>
            </div>

            {error && (
              <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                {error}
              </div>
            )}

            <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-slate-100">
              {preview ? (
                <img
                  src={preview}
                  alt="Prescription preview"
                  className="h-[420px] w-full object-contain"
                />
              ) : (
                <div className="flex h-[420px] items-center justify-center text-slate-500">
                  Preview will appear here.
                </div>
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">2. Review interpretation</h2>
                <p className="text-sm text-slate-500">
                  Verify medicines before saving.
                </p>
              </div>
              {result && (
                <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${overallClass}`}>
                  Overall confidence: {result.overall_confidence}%
                </span>
              )}
            </div>

            {!result && !loading && (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-600">
                No analysis yet. Upload a prescription and click <b>Scan Prescription</b>.
              </div>
            )}

            {loading && (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-600">
                <div className="mb-3 font-medium text-slate-800">Working on it...</div>
                <div className="space-y-2">
                  <div className="h-2 w-full animate-pulse rounded-full bg-slate-200" />
                  <div className="h-2 w-5/6 animate-pulse rounded-full bg-slate-200" />
                  <div className="h-2 w-4/6 animate-pulse rounded-full bg-slate-200" />
                </div>
              </div>
            )}

            {result && (
              <div className="space-y-6">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Patient" value={result.patient_name || "—"} />
                  <Field label="Doctor" value={result.doctor_name || "—"} />
                  <Field label="Date" value={result.date || "—"} />
                  <Field label="Record ID" value={recordId?.toString() || "—"} />
                </div>

                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <h3 className="mb-2 text-sm font-semibold text-slate-900">Summary</h3>
                  <p className="text-sm text-slate-700">{result.summary || "No summary available."}</p>
                </div>

                {!!result.warning_flags?.length && (
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                    <h3 className="mb-2 text-sm font-semibold text-amber-900">Warnings</h3>
                    <ul className="list-disc pl-5 text-sm text-amber-900">
                      {result.warning_flags.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {!!result.clarification_questions?.length && (
                  <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4">
                    <h3 className="mb-2 text-sm font-semibold text-sky-900">Clarifications</h3>
                    <ul className="list-disc pl-5 text-sm text-sky-900">
                      {result.clarification_questions.map((q, i) => (
                        <li key={i}>{q}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <h3 className="mb-3 text-sm font-semibold text-slate-900">Medicines</h3>
                  <div className="space-y-4">
                    {result.medicines.map((med, idx) => (
                      <div key={idx} className="rounded-2xl border border-slate-200 p-4">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">
                            Item {idx + 1}
                          </span>
                          <span
                            className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${confidenceClass(
                              med.confidence
                            )}`}
                          >
                            {med.confidence}%
                          </span>
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2">
                          <EditableField
                            label="Raw text"
                            value={med.raw_observed_text}
                            onChange={(v) => updateMedicine(idx, "raw_observed_text", v)}
                          />
                          <EditableField
                            label="Predicted name"
                            value={med.predicted_name}
                            onChange={(v) => updateMedicine(idx, "predicted_name", v)}
                          />
                          <EditableField
                            label="Dosage"
                            value={med.dosage}
                            onChange={(v) => updateMedicine(idx, "dosage", v)}
                          />
                          <EditableField
                            label="Frequency"
                            value={med.frequency}
                            onChange={(v) => updateMedicine(idx, "frequency", v)}
                          />
                          <EditableField
                            label="Duration"
                            value={med.duration}
                            onChange={(v) => updateMedicine(idx, "duration", v)}
                          />
                          <EditableField
                            label="Route"
                            value={med.route}
                            onChange={(v) => updateMedicine(idx, "route", v)}
                          />
                        </div>

                        {med.uncertainty_reason && (
                          <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                            {med.uncertainty_reason}
                          </div>
                        )}

                        {!!med.alternatives?.length && (
                          <div className="mt-3 text-sm text-slate-600">
                            Alternatives:{" "}
                            {med.alternatives
                              .map((a) => `${a.name} (${a.confidence}%)`)
                              .join(", ")}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="sticky bottom-4 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-lg backdrop-blur">
                  <div className="flex flex-wrap gap-3">
                    <button
                      onClick={analyze}
                      disabled={loading || !file}
                      className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                    >
                      Re-analyze
                    </button>
                    <button
                      onClick={saveVerified}
                      disabled={saving || !result || recordId == null}
                      className="rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-slate-300"
                    >
                      {saving ? "Saving..." : "Verify & Save"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm text-slate-900">{value}</div>
    </div>
  );
}

function EditableField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none ring-0 focus:border-sky-500"
      />
    </label>
  );
}

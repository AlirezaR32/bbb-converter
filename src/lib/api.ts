/** API client for the FastAPI backend (same-origin via Next.js rewrites). */

import type {
  ApiError,
  ConversionJob,
  ExportFormat,
  HealthInfo,
  RecordingAnalysis,
} from "./bbb-types";

export class ApiClientError extends Error {
  code: string;
  details?: Record<string, unknown>;

  constructor(code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

async function unwrap<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let code = "INTERNAL_ERROR";
  let message = res.statusText || "Unexpected server error";
  let details: Record<string, unknown> | undefined;
  try {
    const body = (await res.json()) as ApiError;
    if (body?.error) {
      code = body.error.code;
      message = body.error.message;
      details = body.error.details;
    }
  } catch {
    /* keep defaults */
  }
  throw new ApiClientError(code, message, details);
}

export async function getHealth(): Promise<HealthInfo> {
  const res = await fetch("/api/health", { cache: "no-store" });
  return unwrap<HealthInfo>(res);
}

export async function analyzeRecording(url: string): Promise<RecordingAnalysis> {
  const res = await fetch("/api/recordings/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return unwrap<RecordingAnalysis>(res);
}

export async function createConversion(
  url: string,
  format: ExportFormat,
  includeWebcamPip = true,
): Promise<ConversionJob> {
  const res = await fetch("/api/conversions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, format, include_webcam_pip: includeWebcamPip }),
  });
  return unwrap<ConversionJob>(res);
}

export async function getJob(jobId: string): Promise<ConversionJob> {
  const res = await fetch(`/api/conversions/${jobId}`, { cache: "no-store" });
  return unwrap<ConversionJob>(res);
}

export async function listJobs(): Promise<ConversionJob[]> {
  const res = await fetch("/api/conversions", { cache: "no-store" });
  const data = await unwrap<{ jobs: ConversionJob[] }>(res);
  return data.jobs;
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`/api/conversions/${jobId}`, { method: "DELETE" });
  await unwrap<{ id: string }>(res);
}

export function subscribeToJob(
  jobId: string,
  onUpdate: (payload: {
    status: string;
    stage: string;
    progress: number;
    progress_detail: string;
    error: { code: string; message: string } | null;
  }) => void,
  onEnd: () => void,
): () => void {
  const es = new EventSource(`/api/conversions/${jobId}/events`);
  let closed = false;

  es.addEventListener("progress", (ev) => {
    try {
      onUpdate(JSON.parse((ev as MessageEvent).data));
    } catch {
      /* ignore malformed frames */
    }
  });
  es.addEventListener("end", () => {
    es.close();
    closed = true;
    onEnd();
  });
  es.onerror = () => {
    if (!closed) {
      // Let the caller fall back to polling; EventSource auto-reconnects.
      onEnd();
    }
  };

  return () => {
    closed = true;
    es.close();
  };
}

export function downloadUrl(job: ConversionJob): string {
  if (!job.download) return "#";
  return job.download.url.startsWith("http")
    ? job.download.url
    : job.download.url; // same-origin relative path works directly
}

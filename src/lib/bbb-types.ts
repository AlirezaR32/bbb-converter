/** Shared types mirroring the FastAPI backend schemas. */

export interface AssetInfo {
  available: boolean;
  url?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  note?: string | null;
}

export interface RecordingAnalysis {
  valid: boolean;
  url: string;
  server_host: string;
  meeting_id: string;
  playback_version: string;
  title: string;
  duration_seconds: number;
  participants?: number | null;
  start_time?: string | null;
  assets: {
    direct_video: AssetInfo;
    webcam: AssetInfo;
    screenshare: AssetInfo;
    audio: AssetInfo;
    slides: { available: boolean; count: number; unique?: number; format?: string | null; source?: string | null };
    annotations: { available: boolean };
    panzooms?: string;
  };
  slides: { available: boolean; count: number; format?: string | null; note?: string | null };
  strategy: {
    id: "direct" | "streams" | "reconstruct" | "audio_only" | "unsupported";
    label: string;
    supported: boolean;
    explanation: string;
    limitations: string[];
  };
  estimated_output_mb: Record<string, number>;
  warnings: string[];
}

export interface JobOutput {
  filename: string;
  size_bytes: number;
  duration_seconds: number;
  format: string;
}

export interface JobDownload {
  url: string;
  token: string;
  expires_at: number;
  filename: string;
}

export interface ConversionJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "canceled" | "expired";
  stage: string;
  progress: number;
  progress_detail: string;
  format: string;
  strategy: string;
  title: string;
  source_url: string;
  duration_seconds: number;
  fidelity_notes: string[];
  error: { code: string; message: string } | null;
  output: JobOutput | null;
  download: JobDownload | null;
  created_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
}

export interface HealthInfo {
  status: string;
  version: string;
  ffmpeg_available: boolean;
  ffmpeg_version: string | null;
  queue_mode: string;
  active_jobs: number;
  storage_free_gb: number;
  demo_mode: boolean;
  demo_url: string | null;
  limits: Record<string, number>;
}

export interface ApiError {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export type ExportFormat = "mp4" | "webm" | "mp3";

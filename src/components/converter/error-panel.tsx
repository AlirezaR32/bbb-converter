"use client";

import { motion } from "framer-motion";
import { AlertTriangle, RotateCcw, Trash2, LifeBuoy } from "lucide-react";
import { Button } from "@/components/ui/button";

const HINTS: Record<string, string> = {
  SOURCE_UNREACHABLE:
    "The recording server did not respond. Check that the URL is correct and the server is publicly reachable.",
  SOURCE_TIMEOUT: "The server accepted the connection but responded too slowly. Try again in a moment.",
  SOURCE_FORBIDDEN:
    "The server explicitly refused access (HTTP 401/403). The recording may require login or is not published.",
  SSRF_BLOCKED: "This address points to a private/internal network and is blocked for security reasons.",
  INVALID_URL: "Check that the link is a BigBlueButton playback URL of the form /playback/presentation/2.3/<id>.",
  UNSUPPORTED_PLAYBACK_VERSION: "This playback version is not supported. Supported versions: 2.0, 2.3.",
  ASSETS_MISSING:
    "The playback page exists but its media files are not accessible — the server may restrict downloads or the recording is unpublished.",
  UNSUPPORTED_RECORDING: "This recording does not expose any media this tool can rebuild.",
  RECORDING_TOO_LONG: "The recording exceeds the configured maximum duration.",
  CONCURRENCY_LIMIT: "The server is busy with other conversions. Wait a moment and retry.",
  QUOTA_EXCEEDED: "The server's storage is full. Expired outputs are cleaned automatically.",
  RATE_LIMITED: "Too many requests from your address. Cool down for a minute.",
  FFMPEG_FAILED: "The media encoder failed on this input. The recording may use unsupported codecs.",
  CANCELED: "The job was canceled.",
};

export function ErrorPanel({
  error,
  onRetry,
  onDismiss,
}: {
  error: { code: string; message: string };
  onRetry?: () => void;
  onDismiss: () => void;
}) {
  const hint = HINTS[error.code] ?? "";
  return (
    <motion.section
      aria-label="Error"
      role="alert"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-red-500/25 bg-red-500/[0.06] p-5 sm:p-6"
    >
      <div className="flex items-start gap-3.5">
        <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-500/15 text-red-300">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-red-200">{error.code.replaceAll("_", " ")}</span>
            <code className="rounded bg-black/30 px-1.5 py-0.5 text-[10.5px] text-red-300/80">{error.code}</code>
          </div>
          <p className="mt-1 break-words text-sm text-red-100/90">{error.message}</p>
          {hint && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
              <LifeBuoy className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {hint}
            </p>
          )}
          <div className="mt-3 flex gap-2">
            {onRetry && (
              <Button
                size="sm"
                onClick={onRetry}
                className="h-8 gap-1.5 rounded-lg bg-white/10 text-xs hover:bg-white/15"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                Try again
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={onDismiss}
              className="h-8 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Dismiss
            </Button>
          </div>
        </div>
      </div>
    </motion.section>
  );
}

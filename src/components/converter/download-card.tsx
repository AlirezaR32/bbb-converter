"use client";

import { motion } from "framer-motion";
import { Download, FileCheck2, RotateCcw, Timer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes, formatDuration } from "@/lib/format";
import type { ConversionJob } from "@/lib/bbb-types";

export function DownloadCard({
  job,
  onNewConversion,
}: {
  job: ConversionJob;
  onNewConversion: () => void;
}) {
  const out = job.output;
  if (!out) return null;
  const expires = job.expires_at ? new Date(job.expires_at) : null;
  const expiryText =
    expires && !Number.isNaN(expires.getTime())
      ? `kept for ${Math.max(1, Math.round((expires.getTime() - Date.now()) / 3600000))}h`
      : "stored temporarily";

  return (
    <motion.section
      aria-label="Download"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.35 }}
      className="relative overflow-hidden rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-500/[0.08] via-white/[0.03] to-violet-500/[0.08] p-5 sm:p-6"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3.5">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
            <FileCheck2 className="h-6 w-6" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold" title={job.title}>
              {job.title || "Recording"} — {out.format.toUpperCase()}
            </div>
            <div className="text-xs text-muted-foreground">
              {formatBytes(out.size_bytes)} · {formatDuration(out.duration_seconds)} · {out.format.toUpperCase()}{" "}
              {out.format === "mp4" ? "(H.264/AAC)" : out.format === "webm" ? "(VP9/Opus)" : "(audio)"}
            </div>
            <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground/80">
              <Timer className="h-3 w-3" aria-hidden="true" />
              Secure signed link · {expiryText}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            asChild
            className="btn-glow h-11 flex-1 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-sm font-semibold text-white hover:from-emerald-400 hover:to-teal-400 sm:flex-none sm:px-6"
          >
            <a href={job.download?.url ?? "#"} download={job.download?.filename}>
              <Download className="mr-2 h-4 w-4" aria-hidden="true" />
              Download {out.format.toUpperCase()}
            </a>
          </Button>
          <Button
            variant="outline"
            onClick={onNewConversion}
            className="h-11 rounded-xl border-white/15 px-4 hover:border-violet-400/40 hover:text-violet-200"
          >
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
            New
          </Button>
        </div>
      </div>
    </motion.section>
  );
}

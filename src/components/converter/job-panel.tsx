"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Circle, Loader2, XCircle, X, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { STAGE_LABELS, STAGE_ORDER, formatEta, formatDuration } from "@/lib/format";
import type { ConversionJob } from "@/lib/bbb-types";

function etaSeconds(job: ConversionJob): number {
  if (job.progress <= 0.02 || job.status !== "running") return NaN;
  const elapsedEstimate = (job.progress / (1 - job.progress)) * 30; // rough from observed pace
  return elapsedEstimate;
}

export function JobPanel({ job, onCancel }: { job: ConversionJob; onCancel: () => void }) {
  const pct = Math.round(job.progress * 100);
  const stageIdx = Math.max(0, STAGE_ORDER.indexOf(job.stage));
  const running = job.status === "queued" || job.status === "running";

  return (
    <motion.section
      aria-label="Conversion progress"
      aria-busy={running}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 sm:p-6"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {running ? (
            <Loader2 className="h-5 w-5 animate-spin text-violet-400" aria-hidden="true" />
          ) : job.status === "completed" ? (
            <CheckCircle2 className="h-5 w-5 text-emerald-400" aria-hidden="true" />
          ) : (
            <XCircle className="h-5 w-5 text-red-400" aria-hidden="true" />
          )}
          <div>
            <div className="text-sm font-semibold">
              {running ? "Converting…" : job.status === "completed" ? "Conversion complete" : "Conversion stopped"}
            </div>
            <div className="text-xs text-muted-foreground">
              {job.progress_detail || STAGE_LABELS[job.stage] || job.stage}
              {job.format ? ` · ${job.format.toUpperCase()}` : ""}
            </div>
          </div>
        </div>
        {running && (
          <Button
            variant="outline"
            size="sm"
            onClick={onCancel}
            className="h-8 gap-1.5 rounded-lg border-white/15 hover:border-red-400/40 hover:text-red-300"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            Cancel
          </Button>
        )}
      </div>

      {/* progress bar */}
      <div
        className="progress-shimmer h-2.5 w-full overflow-hidden rounded-full bg-white/[0.06]"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-fuchsia-400 transition-[width] duration-500 ease-out ${
            running ? "progress-shimmer" : ""
          }`}
          style={{ width: `${Math.max(pct, running ? 2 : pct)}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-xs text-muted-foreground">
        <span>{pct}%</span>
        <span>
          {job.status === "running" && job.duration_seconds > 0
            ? `≈ ${formatDuration(job.duration_seconds)} source · ETA ${formatEta(etaSeconds(job))}`
            : job.status === "queued"
              ? "Waiting for a worker slot…"
              : ""}
        </span>
      </div>

      {/* stage stepper */}
      <ol className="mt-5 grid grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Stages">
        {STAGE_ORDER.slice(0, 5).map((s, i) => {
          const done = !running && job.status === "completed";
          const reached = done || i < stageIdx;
          const current = running && i === stageIdx;
          return (
            <li key={s} className="flex flex-col items-center gap-1.5 text-center">
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-[11px] ${
                  current
                    ? "border-violet-400/50 bg-violet-500/20 text-violet-200"
                    : reached
                      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                      : "border-white/10 bg-white/[0.03] text-muted-foreground/50"
                }`}
              >
                {reached && !current ? (
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                ) : current ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Circle className="h-2 w-2" aria-hidden="true" />
                )}
              </span>
              <span className={`text-[10.5px] leading-tight ${current ? "text-foreground" : "text-muted-foreground"}`}>
                {STAGE_LABELS[s]}
              </span>
            </li>
          );
        })}
      </ol>

      {/* fidelity notes */}
      {job.fidelity_notes?.length > 0 && (
        <details className="mt-4 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2">
          <summary className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
            <Terminal className="h-3.5 w-3.5" aria-hidden="true" />
            Processing notes ({job.fidelity_notes.length})
          </summary>
          <ul className="mt-2 list-inside list-disc space-y-1 text-[11.5px] text-muted-foreground/90">
            {job.fidelity_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
    </motion.section>
  );
}

"use client";

import { motion } from "framer-motion";
import { FileVideo, Braces, Music, Check, Info } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { formatDuration } from "@/lib/format";
import type { ExportFormat, RecordingAnalysis } from "@/lib/bbb-types";

const FORMATS: {
  id: ExportFormat;
  name: string;
  detail: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    id: "mp4",
    name: "MP4",
    detail: "H.264 / AAC",
    hint: "Universal playback — recommended",
    icon: FileVideo,
  },
  {
    id: "webm",
    name: "WebM",
    detail: "VP9 / Opus",
    hint: "Smaller files, open codecs",
    icon: Braces,
  },
  {
    id: "mp3",
    name: "MP3",
    detail: "Audio only",
    hint: "Fastest — audio track export",
    icon: Music,
  },
];

export function FormatPicker({
  analysis,
  format,
  onFormatChange,
  includePip,
  onIncludePipChange,
  onConvert,
  converting,
}: {
  analysis: RecordingAnalysis;
  format: ExportFormat;
  onFormatChange: (f: ExportFormat) => void;
  includePip: boolean;
  onIncludePipChange: (v: boolean) => void;
  onConvert: () => void;
  converting: boolean;
}) {
  const strategy = analysis.strategy;
  const estimates = analysis.estimated_output_mb ?? {};
  const isReconstruct = strategy.id === "reconstruct";

  return (
    <motion.section
      aria-label="Export options"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
      className="glass rounded-2xl p-5 sm:p-6"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        {FORMATS.map((f) => {
          const active = format === f.id;
          const est = estimates[f.id];
          const disabled = f.id !== "mp3" && strategy.id === "audio_only";
          return (
            <button
              key={f.id}
              type="button"
              disabled={disabled}
              onClick={() => onFormatChange(f.id)}
              aria-pressed={active}
              className={`relative rounded-xl border p-4 text-left transition-all ${
                active
                  ? "border-violet-500/60 bg-violet-500/10 shadow-[0_0_24px_-8px_rgba(139,92,246,0.5)]"
                  : "border-white/10 bg-white/[0.02] hover:border-white/20"
              } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
            >
              {active && (
                <span className="absolute right-2.5 top-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500">
                  <Check className="h-3 w-3 text-white" aria-hidden="true" />
                </span>
              )}
              <f.icon className={`mb-2 h-5 w-5 ${active ? "text-violet-300" : "text-muted-foreground"}`} aria-hidden="true" />
              <div className="text-sm font-semibold">{f.name}</div>
              <div className="text-xs text-muted-foreground">{f.detail}</div>
              <div className="mt-1.5 text-[11px] text-muted-foreground/80">
                {est ? `≈ ${est < 10 ? est.toFixed(1) : Math.round(est)} MB · ` : ""}
                {formatDuration(analysis.duration_seconds)}
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground/70">{f.hint}</div>
            </button>
          );
        })}
      </div>

      {isReconstruct && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3">
          <div>
            <Label htmlFor="pip" className="text-sm font-medium">
              Include webcam picture-in-picture
            </Label>
            <p className="text-xs text-muted-foreground">
              Overlay the speaker webcam in the corner of the slide video.
            </p>
          </div>
          <Switch id="pip" checked={includePip} onCheckedChange={onIncludePipChange} />
        </div>
      )}

      <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          Processing runs on the server with FFmpeg — progress is reported in real time.
        </p>
        <button
          type="button"
          onClick={onConvert}
          disabled={converting}
          className="btn-glow inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-6 text-sm font-semibold text-white transition-transform hover:scale-[1.015] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
        >
          Convert to {format.toUpperCase()}
        </button>
      </div>
    </motion.section>
  );
}

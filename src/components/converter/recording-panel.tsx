"use client";

import { motion } from "framer-motion";
import {
  MonitorPlay,
  Video,
  FileAudio,
  Presentation,
  PenLine,
  Film,
  CheckCircle2,
  XCircle,
  ShieldAlert,
  Clock,
  Users,
  Server,
  Layers,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatDuration } from "@/lib/format";
import type { AssetInfo, RecordingAnalysis } from "@/lib/bbb-types";

function AssetRow({
  icon: Icon,
  label,
  asset,
  detail,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  asset: AssetInfo | undefined;
  detail?: string;
}) {
  const ok = !!asset?.available;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="flex min-w-0 items-center gap-2.5">
        <Icon className={`h-4 w-4 shrink-0 ${ok ? "text-violet-300" : "text-muted-foreground/50"}`} aria-hidden="true" />
        <span className="truncate text-sm">{label}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {ok && detail && <span className="text-xs text-muted-foreground">{detail}</span>}
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-label="available" />
        ) : (
          <XCircle className="h-4 w-4 text-muted-foreground/40" aria-label="not available" />
        )}
      </div>
    </div>
  );
}

function AnalysisSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3">
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-20 w-full" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export function RecordingPanel({
  analysis,
  loading,
  error,
}: {
  analysis: RecordingAnalysis | null;
  loading: boolean;
  error: { code: string; message: string } | null;
}) {
  if (loading) {
    return (
      <motion.section
        aria-busy="true"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="glass rounded-2xl p-5 sm:p-6"
      >
        <AnalysisSkeleton />
      </motion.section>
    );
  }
  if (!analysis) return null;

  const a = analysis.assets;
  const strategy = analysis.strategy;
  const supported = strategy.supported;

  return (
    <motion.section
      aria-label="Recording details"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="glass rounded-2xl p-5 sm:p-6"
    >
      <div className="grid gap-5 lg:grid-cols-2">
        {/* left: metadata */}
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold tracking-tight" title={analysis.title}>
            {analysis.title || "Untitled recording"}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Server className="h-3 w-3" aria-hidden="true" />
              {analysis.server_host}
            </span>
            <Badge variant="outline" className="h-5 border-white/10 px-1.5 text-[10px]">
              playback {analysis.playback_version}
            </Badge>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" aria-hidden="true" />
              {formatDuration(analysis.duration_seconds)}
            </span>
            {analysis.participants ? (
              <span className="inline-flex items-center gap-1">
                <Users className="h-3 w-3" aria-hidden="true" />
                {analysis.participants}
              </span>
            ) : null}
          </div>

          <div
            className={`mt-4 rounded-xl border p-3 text-sm leading-relaxed ${
              supported
                ? "border-emerald-500/20 bg-emerald-500/[0.06]"
                : "border-amber-500/25 bg-amber-500/[0.06]"
            }`}
          >
            <div className="mb-1 flex items-center gap-2 font-medium">
              {supported ? (
                <Layers className="h-4 w-4 text-emerald-400" aria-hidden="true" />
              ) : (
                <ShieldAlert className="h-4 w-4 text-amber-400" aria-hidden="true" />
              )}
              {strategy.label}
            </div>
            <p className="text-[13px] text-muted-foreground">{strategy.explanation}</p>
            {strategy.limitations.length > 0 && (
              <ul className="mt-2 list-inside list-disc space-y-0.5 text-[12px] text-muted-foreground/90">
                {strategy.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
          </div>

          {analysis.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-amber-300/90">
              {analysis.warnings.map((w) => (
                <li key={w} className="flex gap-1.5">
                  <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* right: asset checklist */}
        <div className="space-y-2" aria-label="Available media assets">
          <AssetRow
            icon={Film}
            label="Ready-made video file"
            asset={a.direct_video}
            detail={formatBytes(a.direct_video?.size_bytes)}
          />
          <AssetRow
            icon={Video}
            label="Webcam stream"
            asset={a.webcam}
            detail={formatBytes(a.webcam?.size_bytes)}
          />
          <AssetRow
            icon={FileAudio}
            label="Separate audio track"
            asset={a.audio}
            detail={formatBytes(a.audio?.size_bytes)}
          />
          <AssetRow
            icon={Presentation}
            label="Presentation slides"
            asset={
              a.slides?.available
                ? { available: true, content_type: a.slides.format }
                : { available: false }
            }
            detail={a.slides?.available ? `${a.slides.count} shown · ${a.slides.format?.toUpperCase() ?? "?"}` : undefined}
          />
          <AssetRow
            icon={PenLine}
            label="Whiteboard annotations"
            asset={a.annotations}
          />
          <AssetRow
            icon={MonitorPlay}
            label="Screenshare"
            asset={a.screenshare}
            detail={formatBytes(a.screenshare?.size_bytes)}
          />
        </div>
      </div>
    </motion.section>
  );
}

"use client";

import { History, Trash2, FileVideo, FileAudio } from "lucide-react";
import type { HistoryEntry } from "@/hooks/use-converter";
import { formatBytes } from "@/lib/format";

const STATUS_DOT: Record<string, string> = {
  completed: "bg-emerald-400",
  failed: "bg-red-400",
  canceled: "bg-amber-400",
  running: "bg-violet-400 animate-pulse",
  queued: "bg-violet-400/50",
};

export function JobsHistory({
  history,
  onClear,
  onReanalyze,
}: {
  history: HistoryEntry[];
  onClear: () => void;
  onReanalyze?: (id: string) => void;
}) {
  if (history.length === 0) return null;
  return (
    <section aria-label="Recent conversions" className="glass rounded-2xl p-4 sm:p-5">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          Recent on this device
        </h2>
        <button
          type="button"
          onClick={onClear}
          className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <Trash2 className="h-3 w-3" aria-hidden="true" />
          Clear
        </button>
      </div>
      <ul className="slim-scroll max-h-56 space-y-1 overflow-y-auto pr-1">
        {history.map((h) => (
          <li
            key={h.id}
            className="group flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2"
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[h.status] ?? "bg-muted-foreground"}`} aria-hidden="true" />
              {h.format === "mp3" ? (
                <FileAudio className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              ) : (
                <FileVideo className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
              <span className="truncate text-xs" title={h.title}>
                {h.title}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
              {h.size_bytes > 0 && <span>{formatBytes(h.size_bytes)}</span>}
              <span className="uppercase">{h.format}</span>
              <span className="hidden sm:inline">{new Date(h.at).toLocaleTimeString()}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

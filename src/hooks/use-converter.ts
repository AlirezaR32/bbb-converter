"use client";

/** Converter state machine: analyze -> ready -> converting -> done/error, with
 * SSE progress (polling fallback) and a lightweight localStorage job history. */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  analyzeRecording,
  createConversion,
  deleteJob,
  getHealth,
  getJob,
  subscribeToJob,
} from "@/lib/api";
import type {
  ConversionJob,
  ExportFormat,
  HealthInfo,
  RecordingAnalysis,
} from "@/lib/bbb-types";

export type Phase =
  | "idle"
  | "analyzing"
  | "ready"
  | "converting"
  | "completed"
  | "failed"
  | "canceled";

export interface HistoryEntry {
  id: string;
  title: string;
  format: string;
  status: string;
  at: string;
  size_bytes: number;
}

const HISTORY_KEY = "bbb-converter-history";

function loadHistory(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]") as HistoryEntry[];
  } catch {
    return [];
  }
}

function saveHistory(entries: HistoryEntry[]) {
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 8)));
  } catch {
    /* storage unavailable */
  }
}

export function useConverter() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [url, setUrl] = useState("");
  const [analysis, setAnalysis] = useState<RecordingAnalysis | null>(null);
  const [format, setFormat] = useState<ExportFormat>("mp4");
  const [includePip, setIncludePip] = useState(true);
  const [job, setJob] = useState<ConversionJob | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setHistory(loadHistory());
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    return () => {
      unsubRef.current?.();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const pushHistory = useCallback((j: ConversionJob) => {
    const entries = loadHistory();
    const next = [
      {
        id: j.id,
        title: j.title || "Untitled recording",
        format: j.format,
        status: j.status,
        at: new Date().toISOString(),
        size_bytes: j.output?.size_bytes ?? 0,
      },
      ...entries.filter((e) => e.id !== j.id),
    ].slice(0, 8);
    saveHistory(next);
    setHistory(next);
  }, []);

  const startTracking = useCallback(
    (initial: ConversionJob) => {
      setJob(initial);
      setPhase("converting");
      pushHistory(initial);

      const finish = async () => {
        try {
          const final = await getJob(initial.id);
          setJob(final);
          pushHistory(final);
          if (final.status === "completed") setPhase("completed");
          else if (final.status === "canceled") setPhase("canceled");
          else if (final.status === "failed") {
            setError(final.error ?? { code: "INTERNAL_ERROR", message: "Conversion failed." });
            setPhase("failed");
          }
        } catch {
          setPhase("failed");
        }
      };

      // SSE with polling fallback if the stream errors out.
      let gotUpdate = false;
      unsubRef.current?.();
      const unsub = subscribeToJob(
        initial.id,
        (p) => {
          gotUpdate = true;
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: p.status as ConversionJob["status"],
                  stage: p.stage,
                  progress: p.progress,
                  progress_detail: p.progress_detail,
                  error: p.error,
                }
              : prev,
          );
        },
        () => {
          unsubRef.current = null;
          void finish();
        },
      );
      unsubRef.current = unsub;

      // Fallback poller: also catches SSE-unsupported proxies.
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        if (unsubRef.current && gotUpdate) return; // SSE is healthy
        try {
          const j = await getJob(initial.id);
          setJob(j);
          if (j.status === "completed" || j.status === "failed" || j.status === "canceled") {
            if (pollRef.current) clearInterval(pollRef.current);
            unsubRef.current?.();
            setJob(j);
            pushHistory(j);
            if (j.status === "completed") setPhase("completed");
            else if (j.status === "canceled") setPhase("canceled");
            else {
              setError(j.error ?? { code: "INTERNAL_ERROR", message: "Conversion failed." });
              setPhase("failed");
            }
          }
        } catch {
          /* transient */
        }
      }, 2000);
    },
    [pushHistory],
  );

  const analyze = useCallback(
    async (rawUrl?: string) => {
      const target = (rawUrl ?? url).trim();
      if (!target) return;
      setUrl(target);
      setAnalyzing(true);
      setError(null);
      setAnalysis(null);
      setPhase("analyzing");
      try {
        const result = await analyzeRecording(target);
        setAnalysis(result);
        setPhase("ready");
      } catch (e) {
        const err = e as { code?: string; message?: string };
        setError({ code: err.code ?? "INTERNAL_ERROR", message: err.message ?? "Analysis failed." });
        setPhase("failed");
      } finally {
        setAnalyzing(false);
      }
    },
    [url],
  );

  const convert = useCallback(
    async (fmt?: ExportFormat) => {
      if (!analysis && !url) return;
      setError(null);
      const chosen = fmt ?? format;
      setFormat(chosen);
      try {
        const j = await createConversion(url, chosen, includePip);
        startTracking(j);
      } catch (e) {
        const err = e as { code?: string; message?: string };
        setError({ code: err.code ?? "INTERNAL_ERROR", message: err.message ?? "Could not start conversion." });
        setPhase("failed");
      }
    },
    [analysis, url, format, includePip, startTracking],
  );

  const cancel = useCallback(async () => {
    if (!job) return;
    try {
      await deleteJob(job.id); // cancels running jobs + removes artifacts
    } catch {
      /* best effort */
    }
    unsubRef.current?.();
    if (pollRef.current) clearInterval(pollRef.current);
    setPhase("canceled");
    setJob(null);
  }, [job]);

  const reset = useCallback(() => {
    unsubRef.current?.();
    if (pollRef.current) clearInterval(pollRef.current);
    setPhase("idle");
    setAnalysis(null);
    setJob(null);
    setError(null);
    setUrl("");
  }, []);

  const retry = useCallback(() => {
    if (job) {
      void deleteJob(job.id).catch(() => undefined);
    }
    setJob(null);
    setError(null);
    if (analysis) setPhase("ready");
    else setPhase("idle");
  }, [job, analysis]);

  const clearHistory = useCallback(() => {
    saveHistory([]);
    setHistory([]);
  }, []);

  return {
    phase,
    url,
    setUrl,
    analysis,
    format,
    setFormat,
    includePip,
    setIncludePip,
    job,
    error,
    health,
    history,
    analyzing,
    analyze,
    convert,
    cancel,
    reset,
    retry,
    clearHistory,
  };
}

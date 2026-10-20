"use client";

import { motion } from "framer-motion";
import { Clapperboard, Cpu, ShieldCheck, Workflow } from "lucide-react";

import { useConverter } from "@/hooks/use-converter";
import { SiteHeader } from "@/components/converter/site-header";
import { SiteFooter } from "@/components/converter/site-footer";
import { UrlForm } from "@/components/converter/url-form";
import { RecordingPanel } from "@/components/converter/recording-panel";
import { FormatPicker } from "@/components/converter/format-picker";
import { JobPanel } from "@/components/converter/job-panel";
import { DownloadCard } from "@/components/converter/download-card";
import { ErrorPanel } from "@/components/converter/error-panel";
import { JobsHistory } from "@/components/converter/jobs-history";
import { toast } from "sonner";

const FEATURES = [
  {
    icon: Workflow,
    title: "True reconstruction",
    text: "Slides, whiteboard annotations, webcam and audio are rebuilt on a synced 1600×900 canvas — never a renamed HTML page.",
  },
  {
    icon: Cpu,
    title: "Real FFmpeg pipeline",
    text: "Stream-copy when possible, H.264/AAC when needed, with live progress streamed from the encoder itself.",
  },
  {
    icon: ShieldCheck,
    title: "Hardened by default",
    text: "SSRF-guarded fetching, signed download links, per-IP limits and automatic cleanup of every artifact.",
  },
];

export default function Home() {
  const cv = useConverter();
  const showAnalyzeState = cv.phase === "analyzing" || (cv.phase === "ready" && cv.analysis);
  const showError = cv.error && (cv.phase === "failed" || (cv.phase === "ready" && !cv.analysis));

  return (
    <div className="relative flex min-h-screen flex-col">
      <div className="app-ambient" aria-hidden="true" />
      <div className="app-grid" aria-hidden="true" />

      <div className="relative z-10">
        <SiteHeader health={cv.health} />

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 pb-16 sm:px-6">
          {/* hero */}
          <section className="pb-8 pt-12 text-center sm:pt-16">
            <motion.h1
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mx-auto max-w-3xl text-balance text-3xl font-bold tracking-tight sm:text-5xl"
            >
              BigBlueButton <span className="text-gradient">Recording Converter</span>
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.08 }}
              className="mx-auto mt-4 max-w-2xl text-balance text-sm text-muted-foreground sm:text-base"
            >
              Paste a public playback link and turn it into a real, downloadable video — slides,
              webcam and audio synchronized into MP4, WebM or MP3.
            </motion.p>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.16 }}
              className="mx-auto mt-5 flex max-w-2xl flex-wrap items-center justify-center gap-x-5 gap-y-1.5 text-[11.5px] text-muted-foreground"
            >
              <span className="inline-flex items-center gap-1.5">
                <Clapperboard className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
                MP4 (H.264/AAC) primary export
              </span>
              <span>WebM · MP3</span>
              <span>Slides + webcam PiP</span>
              <span>SSE live progress</span>
            </motion.div>
          </section>

          <div className="space-y-4">
            <UrlForm
              url={cv.url}
              onUrlChange={cv.setUrl}
              onAnalyze={() => void cv.analyze()}
              analyzing={cv.analyzing}
              disabled={cv.phase === "converting"}
              health={cv.health}
            />

            {showAnalyzeState && (
              <RecordingPanel
                analysis={cv.analysis}
                loading={cv.phase === "analyzing"}
                error={null}
              />
            )}

            {cv.analysis && cv.phase === "ready" && cv.analysis.strategy.supported && (
              <FormatPicker
                analysis={cv.analysis}
                format={cv.format}
                onFormatChange={cv.setFormat}
                includePip={cv.includePip}
                onIncludePipChange={cv.setIncludePip}
                onConvert={() => {
                  void cv.convert();
                  toast.info(`Conversion queued (${cv.format.toUpperCase()})`, {
                    description: "Follow live progress below — powered by real FFmpeg output.",
                  });
                }}
                converting={false}
              />
            )}

            {cv.phase === "converting" && cv.job && <JobPanel job={cv.job} onCancel={() => void cv.cancel()} />}

            {cv.phase === "completed" && cv.job && (
              <DownloadCard job={cv.job} onNewConversion={cv.reset} />
            )}

            {showError && cv.error && (
              <ErrorPanel
                error={cv.error}
                onRetry={() => {
                  cv.retry();
                  if (cv.analysis || cv.url) void cv.analyze(cv.url);
                }}
                onDismiss={cv.reset}
              />
            )}

            {cv.phase === "canceled" && (
              <section className="glass rounded-2xl p-5 text-center text-sm text-muted-foreground">
                Conversion canceled — temporary files were removed.
                <button
                  type="button"
                  onClick={cv.reset}
                  className="ml-2 rounded-md bg-violet-500/15 px-2 py-1 text-xs font-medium text-violet-300 hover:bg-violet-500/25"
                >
                  Start over
                </button>
              </section>
            )}

            <JobsHistory history={cv.history} onClear={cv.clearHistory} />

            {/* features */}
            {cv.phase === "idle" && (
              <section aria-label="How it works" className="grid gap-3 pt-2 sm:grid-cols-3">
                {FEATURES.map((f, i) => (
                  <motion.article
                    key={f.title}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 + i * 0.08 }}
                    className="glass rounded-2xl p-4"
                  >
                    <f.icon className="mb-2.5 h-5 w-5 text-violet-300" aria-hidden="true" />
                    <h2 className="text-sm font-semibold">{f.title}</h2>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{f.text}</p>
                  </motion.article>
                ))}
              </section>
            )}
          </div>
        </main>

        <SiteFooter />
      </div>
    </div>
  );
}

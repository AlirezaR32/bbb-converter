"use client";

import { motion } from "framer-motion";
import { Link2, Loader2, Search, Sparkles, ClipboardPaste } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { HealthInfo } from "@/lib/bbb-types";

interface UrlFormProps {
  url: string;
  onUrlChange: (v: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  disabled?: boolean;
  health: HealthInfo | null;
}

export function UrlForm({ url, onUrlChange, onAnalyze, analyzing, disabled, health }: UrlFormProps) {
  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) onUrlChange(text.trim());
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <motion.section
      aria-label="Recording URL"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="glass rounded-2xl p-4 sm:p-5"
    >
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Link2
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={url}
            onChange={(e) => onUrlChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !analyzing && !disabled) onAnalyze();
            }}
            placeholder="https://your-bbb-server/playback/presentation/2.3/<recording-id>"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            aria-label="BigBlueButton recording playback URL"
            className="h-12 rounded-xl border-white/10 bg-black/30 pl-10 pr-10 text-sm sm:text-base placeholder:text-muted-foreground/70"
          />
          <button
            type="button"
            onClick={pasteFromClipboard}
            aria-label="Paste from clipboard"
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
          >
            <ClipboardPaste className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <Button
          onClick={onAnalyze}
          disabled={analyzing || disabled || !url.trim()}
          className="btn-glow h-12 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-6 text-sm font-semibold text-white transition-transform hover:scale-[1.015] active:scale-[0.99] sm:text-base"
        >
          {analyzing ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              Analyzing…
            </>
          ) : (
            <>
              <Search className="mr-2 h-4 w-4" aria-hidden="true" />
              Analyze Recording
            </>
          )}
        </Button>
      </div>
      {health?.demo_mode && health.demo_url && (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-fuchsia-400" aria-hidden="true" />
          <span>No recording handy?</span>
          <button
            type="button"
            onClick={() => onUrlChange(health.demo_url!)}
            className="rounded-md bg-fuchsia-500/10 px-2 py-1 font-medium text-fuchsia-300 transition-colors hover:bg-fuchsia-500/20"
          >
            Try the bundled demo recording
          </button>
          <span className="hidden sm:inline">— runs fully offline through the real pipeline.</span>
        </div>
      )}
    </motion.section>
  );
}

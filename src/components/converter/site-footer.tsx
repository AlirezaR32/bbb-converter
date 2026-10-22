"use client";

import { ShieldCheck, Github, Lock } from "lucide-react";

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-white/5 py-6">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 text-center text-xs text-muted-foreground sm:flex-row sm:justify-between sm:text-left">
        <p>
          BigBlueButton Recording Converter — self-hosted media pipeline with FFmpeg. Only convert
          recordings you are authorized to access.
        </p>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
            SSRF-hardened
          </span>
          <span className="inline-flex items-center gap-1">
            <Lock className="h-3.5 w-3.5 text-violet-400" aria-hidden="true" />
            Signed downloads
          </span>
          <a
            href="https://github.com/bigbluebutton/bigbluebutton"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
          >
            <Github className="h-3.5 w-3.5" aria-hidden="true" />
            BBB project
          </a>
        </div>
      </div>
    </footer>
  );
}

"use client";

import { Activity, GraduationCap, Github, BookOpen } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { HealthInfo } from "@/lib/bbb-types";

export function SiteHeader({ health }: { health: HealthInfo | null }) {
  const ok = health?.status === "ok" && health.ffmpeg_available;
  return (
    <header className="sticky top-0 z-40 w-full glass border-b">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 shadow-lg shadow-violet-500/25">
            <GraduationCap className="h-4 w-4 text-white" aria-hidden="true" />
          </div>
          <div className="flex flex-col leading-none">
            <span className="text-sm font-semibold tracking-tight">BBB Converter</span>
            <span className="text-[11px] text-muted-foreground">Recording → MP4</span>
          </div>
        </div>
        <nav aria-label="Main" className="flex items-center gap-1.5 sm:gap-3">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="outline"
                  className={
                    ok
                      ? "gap-1.5 border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                      : "gap-1.5 border-amber-500/30 bg-amber-500/10 text-amber-400"
                  }
                >
                  <Activity className="h-3 w-3" aria-hidden="true" />
                  {ok ? "API online" : "API offline"}
                </Badge>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {health
                  ? `v${health.version} · ${health.queue_mode} queue · ${health.storage_free_gb} GB free`
                  : "Backend unreachable"}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <a
            href="https://docs.bigbluebutton.org/admin/recordings/"
            target="_blank"
            rel="noreferrer"
            className="flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
          >
            <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">BBB Docs</span>
          </a>
          <a
            href="https://github.com/bigbluebutton/bigbluebutton"
            target="_blank"
            rel="noreferrer"
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
            aria-label="BigBlueButton on GitHub"
          >
            <Github className="h-4 w-4" aria-hidden="true" />
          </a>
        </nav>
      </div>
    </header>
  );
}

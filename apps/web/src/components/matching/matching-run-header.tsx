"use client";

import React from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertTriangle,
  Clock,
  RefreshCw,
  Layers,
  Users,
  Cpu,
  Loader2,
} from "lucide-react";

type MatchingRun = components["schemas"]["MatchingRunResponse"];
type AudienceEnum = components["schemas"]["AudienceEnum"];

interface MatchingRunHeaderProps {
  runs: MatchingRun[];
  selectedRun: MatchingRun | null;
  onSelectRun: (run: MatchingRun) => void;
  onGenerateRun: (audience: AudienceEnum) => Promise<void>;
  isGenerating: boolean;
  isOperatorOrAdmin: boolean;
  canManage: boolean;
  targetAudience: AudienceEnum;
  setTargetAudience: (aud: AudienceEnum) => void;
  locale?: EnabledLocale;
}

export function MatchingRunHeader({
  runs,
  selectedRun,
  onSelectRun,
  onGenerateRun,
  isGenerating,
  isOperatorOrAdmin,
  canManage,
  targetAudience,
  setTargetAudience,
  locale = "fa",
}: MatchingRunHeaderProps) {
  const messages = getMessages(locale);
  const t = messages.matching;

  const formatDate = (isoString?: string) => {
    if (!isoString) return "-";
    try {
      return new Date(isoString).toLocaleString(locale === "fa" ? "fa-IR" : "en-US", {
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-4">
      {/* Top Bar: Selector + Audience + Run Trigger */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between bg-card p-4 rounded-lg border">
        {/* Left Side: Historical Run Selector or Empty text */}
        <div className="flex flex-wrap items-center gap-3">
          {runs.length > 0 ? (
            <div className="flex items-center gap-2">
              <label htmlFor="matching-run-selector" className="text-xs font-semibold text-muted-foreground whitespace-nowrap">
                {t.runHistory.label}:
              </label>
              <select
                id="matching-run-selector"
                value={selectedRun?.id || ""}
                onChange={(e) => {
                  const run = runs.find((r) => r.id === e.target.value);
                  if (run) onSelectRun(run);
                }}
                className="h-8 rounded-md border border-input bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {runs.map((r, index) => (
                  <option key={r.id} value={r.id}>
                    {formatDate(r.generated_at)} — {t.audiences[r.audience]} ({t.scores.rank} v{r.rfq_version})
                    {index === 0 ? ` [${t.runHistory.latestBadge}]` : ""}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t.states.noRuns}
            </p>
          )}
        </div>

        {/* Right Side: Audience (Operator only) & Action Button */}
        <div className="flex flex-wrap items-center gap-2">
          {isOperatorOrAdmin && (
            <div className="flex items-center gap-1.5 bg-muted/50 px-2 py-1 rounded border text-xs">
              <span className="text-muted-foreground">{t.actions.audienceLabel}</span>
              <select
                aria-label={t.actions.audienceLabel}
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value as AudienceEnum)}
                disabled={isGenerating}
                className="bg-transparent font-semibold text-foreground focus:outline-none"
              >
                <option value="OPERATOR">{t.audiences.OPERATOR}</option>
                <option value="BUYER">{t.audiences.BUYER}</option>
              </select>
            </div>
          )}

          {canManage && runs.length > 0 && (
            <Button
              onClick={() => void onGenerateRun(targetAudience)}
              disabled={isGenerating}
              className="min-h-8 px-3 py-1 text-xs gap-1.5"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t.actions.rerunning}
                </>
              ) : (
                <>
                  <RefreshCw className="h-3.5 w-3.5" />
                  {t.actions.rerun}
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Selected Run Metadata Strip */}
      {selectedRun && (
        <div className="bg-muted/30 px-4 py-2.5 rounded-lg border flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-1 text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>{t.runHistory.runAt}</span>
              <span className="font-semibold text-foreground font-mono">
                {formatDate(selectedRun.generated_at)}
              </span>
            </div>

            <div className="flex items-center gap-1 text-muted-foreground">
              <Users className="h-3.5 w-3.5" />
              <Badge variant="outline" className="text-[11px] font-medium">
                {t.audiences[selectedRun.audience]}
              </Badge>
            </div>

            <div className="flex items-center gap-1 text-muted-foreground">
              <Layers className="h-3.5 w-3.5" />
              <span>{t.runHistory.policyVersion}</span>
              <span className="font-semibold text-foreground font-mono">
                v{selectedRun.policy_version_number}
              </span>
            </div>

            {selectedRun.engine_version && (
              <div className="flex items-center gap-1 text-muted-foreground">
                <Cpu className="h-3.5 w-3.5" />
                <span>{t.runHistory.engineVersion}</span>
                <span className="font-semibold text-foreground font-mono text-[11px]">
                  {selectedRun.engine_version}
                </span>
              </div>
            )}

            <div className="flex items-center gap-1 text-muted-foreground">
              <span>{t.runHistory.candidatesCount}</span>
              <Badge variant="secondary" className="font-mono text-xs">
                {selectedRun.candidate_count}
              </Badge>
            </div>
          </div>

          {selectedRun.is_stale && (
            <Badge variant="destructive" className="text-[11px] gap-1 bg-amber-500 hover:bg-amber-600 text-white">
              <AlertTriangle className="h-3 w-3" />
              {t.stale.badge}
            </Badge>
          )}
        </div>
      )}

      {/* Stale Warning Card if is_stale === true */}
      {selectedRun?.is_stale && (
        <Card className="border-amber-500/50 bg-amber-50 dark:bg-amber-950/20 shadow-sm">
          <CardContent className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 text-xs text-amber-800 dark:text-amber-300">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600" />
              <div className="space-y-0.5">
                <p className="font-bold">{t.stale.title}</p>
                <p className="text-amber-700 dark:text-amber-400 leading-relaxed">
                  {t.stale.warning}
                </p>
              </div>
            </div>
            {canManage && (
              <Button
                variant="outline"
                onClick={() => void onGenerateRun(targetAudience)}
                disabled={isGenerating}
                className="shrink-0 min-h-8 px-3 py-1 text-xs border-amber-400 text-amber-900 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-900/30 gap-1.5"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {t.actions.rerun}
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

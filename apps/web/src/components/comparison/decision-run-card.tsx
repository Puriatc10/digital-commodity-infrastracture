"use client";

import React from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  FileCheck2,
  Loader2,
  Play,
  RefreshCw,
  Scale,
  Sparkles,
  Zap,
} from "lucide-react";

type DecisionRunDetailResponse = components["schemas"]["DecisionRunDetailResponse"];

export interface DecisionRunCardProps {
  run: DecisionRunDetailResponse | null;
  isLoadingRun: boolean;
  isExecutingRun: boolean;
  hasOffers: boolean;
  onExecuteRun: () => Promise<void>;
  locale?: EnabledLocale;
}

export function DecisionRunCard({
  run,
  isLoadingRun,
  isExecutingRun,
  hasOffers,
  onExecuteRun,
  locale = "fa",
}: DecisionRunCardProps) {
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.comparison.decisionSupport;
  const isRtl = locale === "fa";

  if (isLoadingRun) {
    return (
      <Card className="border shadow-xs bg-card/60">
        <CardContent className="p-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>در حال دریافت وضعیت ارزیابی تصمیم…</span>
        </CardContent>
      </Card>
    );
  }

  // Case 1: No DecisionRun has been executed yet
  if (!run) {
    return (
      <Card className="border border-dashed bg-card/40">
        <CardHeader className="pb-2 text-center sm:text-right">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2 justify-center sm:justify-start">
                <Scale className="h-4 w-4 text-primary" />
                <CardTitle className="text-sm font-semibold">{t.noRunTitle}</CardTitle>
              </div>
              <CardDescription className="text-xs leading-relaxed max-w-xl">
                {t.noRunDesc}
              </CardDescription>
            </div>
            <Button
              onClick={() => void onExecuteRun()}
              disabled={isExecutingRun || !hasOffers}
              className="gap-2 shrink-0 font-medium text-xs min-h-9 px-4"
            >
              {isExecutingRun ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t.running}
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-current" />
                  {t.runAction}
                </>
              )}
            </Button>
          </div>
        </CardHeader>
      </Card>
    );
  }

  // Case 2: DecisionRun exists (stale or current)
  const isStale = Boolean(run.is_stale);
  const recommendedCandidate = !isStale
    ? run.candidates.find((c) => c.is_recommended)
    : null;

  return (
    <div className="space-y-3" dir={isRtl ? "rtl" : "ltr"}>
      {/* Stale Warning Banner */}
      {isStale && (
        <div
          role="alert"
          className="p-3.5 bg-amber-500/10 border border-amber-500/30 text-amber-900 dark:text-amber-200 rounded-lg text-xs space-y-1"
        >
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 font-bold text-amber-900 dark:text-amber-200">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
              <span>{t.staleWarningTitle}</span>
            </div>
            <Button
              variant="outline"
              onClick={() => void onExecuteRun()}
              disabled={isExecutingRun}
              className="h-7 min-h-7 text-xs border-amber-500/40 hover:bg-amber-500/20 text-amber-900 dark:text-amber-100 gap-1.5"
            >
              {isExecutingRun ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {t.rerunAction}
            </Button>
          </div>
          <p className="text-[11px] leading-relaxed text-amber-800/90 dark:text-amber-300">
            {t.staleWarningDesc}
          </p>
        </div>
      )}

      {/* Decision Intelligence Summary Card */}
      <Card className={`border shadow-xs ${isStale ? "bg-muted/10 opacity-90" : "bg-card"}`}>
        <CardHeader className="pb-3 border-b border-border/60">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <Sparkles className="h-4 w-4 text-primary" />
                <CardTitle className="text-sm font-semibold">{t.title}</CardTitle>
                <Badge variant="outline" className="text-[11px] text-muted-foreground font-mono">
                  {t.policyVersion} {run.profile_code} (v{run.profile_version_number})
                </Badge>
                {isStale ? (
                  <Badge variant="outline" className="text-amber-600 border-amber-300 text-[11px]">
                    تاریخی / منسوخ
                  </Badge>
                ) : (
                  <Badge className="bg-primary/10 text-primary border-primary/20 text-[11px]">
                    جاری و معتبر
                  </Badge>
                )}
              </div>
              <CardDescription className="text-xs">
                ارزیابی تحلیلی {run.total_candidates} پیشنهاد با استفاده از قوانین بدون سوگیری سامانه
              </CardDescription>
            </div>

            {!isStale && (
              <Button
                variant="outline"
                onClick={() => void onExecuteRun()}
                disabled={isExecutingRun}
                className="h-8 min-h-8 text-xs gap-1.5 shrink-0"
              >
                {isExecutingRun ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                {t.rerunAction}
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="pt-4 pb-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            {/* Metric 1: Top Recommended Candidate */}
            <div className="p-3 rounded-lg border bg-muted/20 space-y-1.5">
              <div className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
                <Award className="h-3.5 w-3.5 text-primary" />
                <span>وضعیت پیشنهاد برتر</span>
              </div>
              {recommendedCandidate ? (
                <div className="space-y-1">
                  <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[11px] gap-1 font-medium">
                    <CheckCircle2 className="h-3 w-3" />
                    {t.recommended}
                  </Badge>
                  <div className="text-[11px] text-muted-foreground">
                    رتبه ۱ با امتیاز مؤثر{" "}
                    <span className="font-mono font-bold text-foreground">
                      {recommendedCandidate.effective_score ?? "—"}%
                    </span>
                  </div>
                </div>
              ) : isStale ? (
                <div className="text-muted-foreground text-[11px] italic">
                  به دلیل تغییر داده‌ها، پیشنهاد جاری انتخاب نشده است.
                </div>
              ) : (
                <div className="text-muted-foreground text-[11px] italic">
                  هیچ پیشنهادی به آستانه پوشش و شرایط واگذاری نرسید.
                </div>
              )}
            </div>

            {/* Metric 2: Evidence Coverage Separation */}
            <div className="p-3 rounded-lg border bg-muted/20 space-y-1.5">
              <div className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
                <FileCheck2 className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />
                <span>پوشش شواهد (تفکیک‌شده از امتیاز)</span>
              </div>
              <div className="text-xs text-muted-foreground leading-relaxed">
                میزان اطلاعات و مدارک اثبات‌شده تجاری به طور مستقل ارزیابی می‌شود تا امتیاز بالا با فقدان شواهد پنهان نماند.
              </div>
            </div>

            {/* Metric 3: Safe Governance */}
            <div className="p-3 rounded-lg border bg-muted/20 space-y-1.5">
              <div className="text-muted-foreground flex items-center gap-1.5 text-[11px]">
                <Zap className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
                <span>اصول تصمیم‌گیری</span>
              </div>
              <div className="text-[11px] text-muted-foreground leading-relaxed">
                رتبه‌بندی قطعی و مستقل از هوش مصنوعی است. تصمیم نهایی واگذاری همیشه با تأیید خریدار انجام می‌شود.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import React from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { getLocalizedReason } from "./matching-reason-codes";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  MinusCircle,
  X,
  Layers,
  ShieldCheck,
  MapPin,
  Calendar,
  Package,
  History,
} from "lucide-react";

type MatchingCandidate = components["schemas"]["MatchingCandidateResponse"];
type MatchingSignal = components["schemas"]["MatchingSignalResponse"];
type DimensionEnum = components["schemas"]["DimensionEnum"];
type OutcomeEnum = components["schemas"]["MatchingSignalResponseOutcomeEnum"];

interface MatchingSignalExplanationDialogProps {
  candidate: MatchingCandidate | null;
  onClose: () => void;
  locale?: EnabledLocale;
}

const DIMENSION_ORDER: DimensionEnum[] = [
  "SPECIFICATION",
  "QUANTITY",
  "AVAILABILITY",
  "GEOGRAPHY",
  "TRUST",
  "HISTORY",
];

export function MatchingSignalExplanationDialog({
  candidate,
  onClose,
  locale = "fa",
}: MatchingSignalExplanationDialogProps) {
  if (!candidate) return null;

  const messages = getMessages(locale);
  const t = messages.matching;
  const isRtl = locale === "fa";

  const getOutcomeBadge = (outcome: OutcomeEnum) => {
    switch (outcome) {
      case "PASS":
        return (
          <Badge className="bg-green-100 text-green-800 border-green-200 dark:bg-green-950/40 dark:text-green-300 gap-1 font-medium">
            <CheckCircle2 className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
            {t.explanation.outcomes.PASS}
          </Badge>
        );
      case "PARTIAL":
        return (
          <Badge className="bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 gap-1 font-medium">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
            {t.explanation.outcomes.PARTIAL}
          </Badge>
        );
      case "FAIL":
        return (
          <Badge className="bg-destructive/10 text-destructive border-destructive/20 gap-1 font-medium">
            <XCircle className="h-3.5 w-3.5 text-destructive" />
            {t.explanation.outcomes.FAIL}
          </Badge>
        );
      case "UNKNOWN":
        return (
          <Badge variant="outline" className="border-blue-300 text-blue-800 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-300 gap-1 font-medium">
            <HelpCircle className="h-3.5 w-3.5 text-blue-500" />
            {t.explanation.outcomes.UNKNOWN}
          </Badge>
        );
      case "NOT_APPLICABLE":
      default:
        return (
          <Badge variant="secondary" className="gap-1 font-normal text-muted-foreground">
            <MinusCircle className="h-3.5 w-3.5" />
            {t.explanation.outcomes.NOT_APPLICABLE}
          </Badge>
        );
    }
  };

  const getDimensionIcon = (dim: DimensionEnum) => {
    switch (dim) {
      case "SPECIFICATION":
        return <Layers className="h-4 w-4 text-primary" />;
      case "QUANTITY":
        return <Package className="h-4 w-4 text-primary" />;
      case "AVAILABILITY":
        return <Calendar className="h-4 w-4 text-primary" />;
      case "GEOGRAPHY":
        return <MapPin className="h-4 w-4 text-primary" />;
      case "TRUST":
        return <ShieldCheck className="h-4 w-4 text-primary" />;
      case "HISTORY":
        return <History className="h-4 w-4 text-primary" />;
      default:
        return null;
    }
  };

  const getDimensionLabel = (dim: DimensionEnum) => {
    return t.explanation.dimensions[dim] || dim;
  };

  // Group signals by dimension preserving canonical order
  const signals = candidate.signals || [];
  const groupedSignals = DIMENSION_ORDER.reduce<Record<DimensionEnum, MatchingSignal[]>>(
    (acc, dim) => {
      const dimSignals = signals.filter((s) => s.dimension === dim);
      if (dimSignals.length > 0) {
        acc[dim] = dimSignals;
      }
      return acc;
    },
    {} as Record<DimensionEnum, MatchingSignal[]>
  );

  const formatValue = (val: unknown): string => {
    if (val === null || val === undefined) return "-";
    if (typeof val === "object") {
      try {
        return JSON.stringify(val);
      } catch {
        return String(val);
      }
    }
    return String(val);
  };

  const candidateOrgName = (candidate.source as Record<string, unknown>)?.organization_name as string ||
    (candidate.source as Record<string, unknown>)?.counterparty_name as string ||
    "";

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 overflow-y-auto"
      dir={isRtl ? "rtl" : "ltr"}
    >
      <Card className="w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden border">
        {/* Header */}
        <CardHeader className="border-b pb-4 shrink-0 flex flex-row items-center justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-lg font-bold">
                {t.explanation.title}
              </CardTitle>
              {candidate.rank !== null && candidate.rank !== undefined && (
                <Badge variant="secondary" className="font-mono text-xs">
                  {t.scores.rank} #{candidate.rank}
                </Badge>
              )}
            </div>
            <CardDescription className="text-xs">
              {candidateOrgName && `${t.explanation.candidateLabel} ${candidateOrgName} · `}
              {t.explanation.subtitle}
            </CardDescription>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-8 w-8 rounded-full border bg-card flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
            aria-label={t.explanation.close}
          >
            <X className="h-4 w-4" />
          </button>
        </CardHeader>

        {/* Candidate Score Summary Banner */}
        <div className="bg-muted/40 px-6 py-3 border-b flex flex-wrap items-center gap-4 text-xs">
          {candidate.lane === "BROKER_PATH" ? (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">{t.scores.brokerRelevance}:</span>
              <span className="font-bold text-sm text-foreground">
                {candidate.ranking_score ? `${Number(candidate.ranking_score).toFixed(2)}${t.scores.percent}` : "-"}
              </span>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">{t.scores.fitScore}:</span>
                <span className="font-bold text-sm text-foreground">
                  {candidate.fit_score ? `${Number(candidate.fit_score).toFixed(2)}${t.scores.percent}` : "-"}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">{t.scores.coverage}:</span>
                <span className="font-bold text-sm text-foreground">
                  <bdi dir="ltr">{candidate.evidence_coverage ? `${Number(candidate.evidence_coverage).toFixed(2)}${t.scores.percent}` : "-"}</bdi>
                </span>
              </div>
              <div className="flex items-center gap-1.5 border-s ps-4">
                <span className="text-muted-foreground">{t.scores.rankingScore}:</span>
                <span className="font-bold text-sm text-primary">
                  <bdi dir="ltr">{candidate.ranking_score ? `${Number(candidate.ranking_score).toFixed(2)}${t.scores.percent}` : "-"}</bdi>
                </span>
              </div>
            </>
          )}

          {candidate.eligible === false && (
            <Badge variant="destructive" className="text-xs">
              {t.candidateCard.ineligibleBadge}
              {candidate.exclusion_code ? ` (${candidate.exclusion_code})` : ""}
            </Badge>
          )}
        </div>

        {/* Signal Groups Body */}
        <CardContent className="flex-1 overflow-y-auto p-6 space-y-6">
          {Object.keys(groupedSignals).length === 0 ? (
            <div className="text-center py-8 text-sm text-muted-foreground">
              {t.states.noCandidates}
            </div>
          ) : (
            (Object.keys(groupedSignals) as DimensionEnum[]).map((dim) => {
              const dimSignals = groupedSignals[dim];
              return (
                <div key={dim} className="space-y-3">
                  <div className="flex items-center gap-2 border-b pb-1.5">
                    {getDimensionIcon(dim)}
                    <h3 className="text-sm font-semibold text-foreground">
                      {getDimensionLabel(dim)}
                    </h3>
                    <Badge variant="secondary" className="text-xs font-mono px-1.5 py-0">
                      {dimSignals.length}
                    </Badge>
                  </div>

                  <div className="rounded-md border overflow-x-auto">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow className="bg-muted/50">
                          <TableHead className="w-[140px] text-start font-medium">
                            {t.explanation.signalTable.code}
                          </TableHead>
                          <TableHead className="w-[110px] text-start font-medium">
                            {t.explanation.signalTable.outcome}
                          </TableHead>
                          <TableHead className="text-start font-medium">
                            {t.explanation.signalTable.reason}
                          </TableHead>
                          <TableHead className="w-[80px] text-center font-medium">
                            {t.explanation.signalTable.weight}
                          </TableHead>
                          <TableHead className="w-[90px] text-center font-medium">
                            {t.explanation.signalTable.contribution}
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {dimSignals.map((sig) => {
                          const hasDetails =
                            sig.expected_value !== undefined &&
                            sig.expected_value !== null ||
                            sig.actual_value !== undefined &&
                            sig.actual_value !== null;

                          return (
                            <React.Fragment key={sig.id}>
                              <TableRow className="hover:bg-muted/30">
                                <TableCell className="font-mono text-xs">
                                  <div className="flex flex-col gap-1">
                                    <span className="font-medium text-foreground">{sig.code}</span>
                                    {sig.is_hard && (
                                      <span className="text-[10px] font-semibold text-destructive">
                                        {t.explanation.signalTable.hardGate}
                                      </span>
                                    )}
                                  </div>
                                </TableCell>
                                <TableCell>
                                  {getOutcomeBadge(sig.outcome)}
                                </TableCell>
                                <TableCell className="text-muted-foreground leading-relaxed">
                                  {getLocalizedReason(sig.reason_code, locale)}
                                </TableCell>
                                <TableCell className="text-center font-mono text-muted-foreground">
                                  {sig.weight ? Number(sig.weight).toFixed(1) : "-"}
                                </TableCell>
                                <TableCell className="text-center font-mono font-medium">
                                  {sig.contribution !== null && sig.contribution !== undefined
                                    ? Number(sig.contribution).toFixed(2)
                                    : "-"}
                                </TableCell>
                              </TableRow>

                              {hasDetails && (
                                <TableRow className="bg-muted/10">
                                  <TableCell colSpan={5} className="py-2 px-4">
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] bg-background/60 p-2.5 rounded border border-dashed">
                                      {sig.expected_value !== undefined && sig.expected_value !== null && (
                                        <div>
                                          <span className="font-semibold text-muted-foreground block mb-0.5">
                                            {t.explanation.signalTable.expected}:
                                          </span>
                                          <bdi dir="ltr" className="font-mono text-foreground break-all block">
                                            {formatValue(sig.expected_value)}
                                          </bdi>
                                        </div>
                                      )}
                                      {sig.actual_value !== undefined && sig.actual_value !== null && (
                                        <div>
                                          <span className="font-semibold text-muted-foreground block mb-0.5">
                                            {t.explanation.signalTable.actual}:
                                          </span>
                                          <bdi dir="ltr" className="font-mono text-foreground break-all block">
                                            {formatValue(sig.actual_value)}
                                          </bdi>
                                        </div>
                                      )}
                                    </div>
                                  </TableCell>
                                </TableRow>
                              )}
                            </React.Fragment>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              );
            })
          )}
        </CardContent>

        {/* Footer */}
        <div className="border-t p-4 flex justify-end shrink-0 bg-muted/20">
          <Button variant="outline" onClick={onClose} className="min-w-24 min-h-8 px-3 py-1 text-xs">
            {t.explanation.close}
          </Button>
        </div>
      </Card>
    </div>
  );
}

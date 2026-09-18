"use client";

import React, { useState } from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  Clock,
  HelpCircle,
  MessageSquare,
  Scale,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { WhyRecommendationModal } from "./why-recommendation-modal";
import { RevisionRequestModal } from "./revision-request-modal";

type ComparisonRow = components["schemas"]["ComparisonRow"];
type DecisionRunDetailResponse = components["schemas"]["DecisionRunDetailResponse"];
type DecisionCandidateResponse = components["schemas"]["DecisionCandidateResponse"];

export interface ComparisonTableProps {
  rows: ComparisonRow[];
  rfqCurrency: string;
  rfqQuantity: string;
  rfqUnit: string;
  decisionRun: DecisionRunDetailResponse | null;
  isOperator: boolean;
  canManage: boolean;
  locale?: EnabledLocale;
  onRefresh: () => void;
}

export function ComparisonTable({
  rows,
  rfqCurrency,
  decisionRun,
  isOperator,
  canManage,
  locale = "fa",
  onRefresh,
}: ComparisonTableProps) {
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.comparison;
  const isRtl = locale === "fa";

  const [selectedCandidate, setSelectedCandidate] = useState<{
    candidate: DecisionCandidateResponse;
    offerorName: string;
  } | null>(null);

  const [revisionRow, setRevisionRow] = useState<ComparisonRow | null>(null);

  const isStale = Boolean(decisionRun?.is_stale);

  // Helper to map candidates by offer_version_id
  const candidatesByVersionId = React.useMemo(() => {
    const map = new Map<string, DecisionCandidateResponse>();
    if (decisionRun?.candidates) {
      for (const cand of decisionRun.candidates) {
        map.set(cand.offer_version_id, cand);
      }
    }
    return map;
  }, [decisionRun]);

  const renderRoleBadge = (role: string, isExternal: boolean) => {
    if (isExternal) {
      return (
        <Badge variant="outline" className="border-indigo-500/30 text-indigo-700 dark:text-indigo-400 bg-indigo-500/10 text-[11px]">
          {t.roles.external}
        </Badge>
      );
    }
    if (role === "BROKER") {
      return (
        <Badge variant="outline" className="border-purple-500/30 text-purple-700 dark:text-purple-400 bg-purple-500/10 text-[11px]">
          {t.roles.broker}
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="border-blue-500/30 text-blue-700 dark:text-blue-400 bg-blue-500/10 text-[11px]">
        {t.roles.supplier}
      </Badge>
    );
  };

  const renderUnknownCostState = (
    landedCost: string | null,
    costComp: ComparisonRow["cost_comparability"]
  ) => {
    if (costComp === "CROSS_CURRENCY_UNKNOWN") {
      return (
        <Badge variant="outline" className="border-amber-500/40 text-amber-700 dark:text-amber-300 bg-amber-500/10 text-[10px]">
          {t.comparability.crossCurrency} ({rfqCurrency})
        </Badge>
      );
    }
    if (landedCost === null || landedCost === undefined) {
      return (
        <span className="text-[11px] text-amber-700 dark:text-amber-400 font-medium italic">
          {t.costStates.unknown}
        </span>
      );
    }
    return null;
  };

  const renderComplianceBadge = (status: ComparisonRow["technical_compliance"]) => {
    switch (status) {
      case "PASS":
        return (
          <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] gap-1">
            <CheckCircle2 className="h-3 w-3" />
            {t.compliance.pass}
          </Badge>
        );
      case "FAIL":
        return (
          <Badge className="bg-rose-600/10 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
            <XCircle className="h-3 w-3" />
            {t.compliance.fail}
          </Badge>
        );
      case "UNKNOWN":
      default:
        return (
          <Badge variant="outline" className="text-muted-foreground text-[10px] gap-1">
            <HelpCircle className="h-3 w-3" />
            {t.compliance.unknown}
          </Badge>
        );
    }
  };

  const renderTrustBadge = (trustStatus: string) => {
    const norm = (trustStatus || "").toUpperCase();
    if (norm.includes("BASIC_VERIFIED")) {
      return (
        <Badge variant="outline" className="border-blue-500/30 text-blue-700 dark:text-blue-400 text-[10px] gap-1">
          <ShieldCheck className="h-3 w-3" />
          {t.trustStatuses.basic_verified}
        </Badge>
      );
    }
    if (norm.includes("VERIFIED")) {
      return (
        <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] gap-1 font-medium">
          <ShieldCheck className="h-3 w-3" />
          {t.trustStatuses.verified}
        </Badge>
      );
    }
    if (norm.includes("SUSPENDED")) {
      return (
        <Badge className="bg-rose-600/10 text-rose-700 dark:text-rose-400 border-rose-500/20 text-[10px] gap-1">
          <ShieldAlert className="h-3 w-3" />
          {t.trustStatuses.suspended}
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="text-muted-foreground text-[10px]">
        {t.trustStatuses.unknown}
      </Badge>
    );
  };

  return (
    <div className="space-y-4" dir={isRtl ? "rtl" : "ltr"}>
      {isOperator && (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="border-primary/40 text-primary text-xs font-semibold">
            {t.operatorProvenance.badge}
          </Badge>
        </div>
      )}

      {/* 1. Desktop & Tablet Table View */}
      <div className="hidden md:block rounded-lg border bg-card overflow-hidden shadow-xs">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40 text-xs">
              <TableHead className="w-[180px] font-semibold">{t.table.offeror}</TableHead>
              <TableHead className="font-semibold">{t.table.version}</TableHead>
              <TableHead className="font-semibold">{t.table.unitPrice}</TableHead>
              <TableHead className="font-semibold">{t.table.quantity}</TableHead>
              <TableHead className="font-semibold">{t.table.landedCost}</TableHead>
              <TableHead className="font-semibold">{t.table.technicalCompliance}</TableHead>
              <TableHead className="font-semibold">{t.table.trust}</TableHead>
              <TableHead className="font-semibold text-center">{t.table.decision}</TableHead>
              <TableHead className="font-semibold text-end">{t.table.actions}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const candidate = candidatesByVersionId.get(row.offer_version_id) || null;
              const isCrossCurrency = row.cost_comparability === "CROSS_CURRENCY_UNKNOWN";
              const isRecommended = Boolean(
                candidate && candidate.is_recommended && !isStale
              );
              const isIneligible = Boolean(candidate && candidate.award_eligible === false);

              return (
                <TableRow
                  key={row.offer_version_id}
                  className={`text-xs transition-colors ${
                    isRecommended
                      ? "bg-emerald-500/5 hover:bg-emerald-500/10 border-s-4 border-s-emerald-500"
                      : isIneligible
                      ? "bg-muted/10 opacity-85"
                      : "hover:bg-muted/30"
                  }`}
                >
                  {/* Column 1: Offeror & Role */}
                  <TableCell className="align-top py-3 font-medium">
                    <div className="space-y-1">
                      <div className="font-semibold text-foreground text-sm flex items-center gap-1.5 flex-wrap">
                        <span>{row.offeror_name}</span>
                      </div>
                      <div className="flex items-center gap-1 flex-wrap">
                        {renderRoleBadge(row.offeror_role, row.is_external)}
                      </div>
                      {row.is_external && (
                        <div className="text-[10px] text-muted-foreground font-mono">
                          {t.roles.external}
                        </div>
                      )}
                    </div>
                  </TableCell>

                  {/* Column 2: Version */}
                  <TableCell className="align-top py-3">
                    <div className="space-y-1">
                      <Badge variant="secondary" className="font-mono text-xs font-semibold">
                        V{row.version_number}
                      </Badge>
                      {row.valid_until && (
                        <div className="text-[10px] text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          <span>{new Date(row.valid_until).toLocaleDateString(locale === "fa" ? "fa-IR" : "en-US")}</span>
                        </div>
                      )}
                    </div>
                  </TableCell>

                  {/* Column 3: Unit Price & Currency */}
                  <TableCell className="align-top py-3">
                    <div className="space-y-0.5">
                      <div className="font-mono font-bold text-foreground text-sm flex items-baseline gap-1">
                        <span>{row.unit_price}</span>
                        <span className={`text-xs ${isCrossCurrency ? "text-amber-600 font-bold" : "text-muted-foreground"}`}>
                          {row.currency}
                        </span>
                      </div>
                      {isCrossCurrency && (
                        <Badge variant="outline" className="border-amber-500/30 text-amber-700 dark:text-amber-400 bg-amber-500/10 text-[10px] px-1 py-0 block w-fit">
                          {t.comparability.crossCurrency}
                        </Badge>
                      )}
                    </div>
                  </TableCell>

                  {/* Column 4: Quantity & Coverage */}
                  <TableCell className="align-top py-3">
                    <div className="space-y-1">
                      <div className="font-mono font-medium text-foreground">
                        {row.offered_quantity} {row.quantity_unit}
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        پوشش تقاضا:{" "}
                        <span className="font-mono font-semibold text-foreground">
                          {(parseFloat(row.quantity_coverage) * 100).toFixed(0)}%
                        </span>
                      </div>
                      {parseFloat(row.surplus_quantity) > 0 && (
                        <div className="text-[10px] text-muted-foreground font-mono">
                          مازاد: {row.surplus_quantity}
                        </div>
                      )}
                    </div>
                  </TableCell>

                  {/* Column 5: Landed Unit Cost & Unknown Semantics */}
                  <TableCell className="align-top py-3">
                    <div className="space-y-1">
                      {renderUnknownCostState(row.landed_unit_cost, row.cost_comparability) || (
                        <div className="font-mono font-bold text-foreground text-sm">
                          {row.landed_unit_cost}{" "}
                          <span className="text-xs font-normal text-muted-foreground">{row.currency}</span>
                        </div>
                      )}
                      <div className="text-[10px] text-muted-foreground font-mono">
                        مجموع شناخته‌شده: {row.known_cost_total}
                      </div>
                      {row.normalization_complete ? (
                        <Badge variant="outline" className="border-emerald-500/30 text-emerald-700 dark:text-emerald-400 text-[9px] px-1">
                          تکمیل هزینه
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-muted-foreground/30 text-muted-foreground text-[9px] px-1">
                          نقص در مؤلفه هزینه
                        </Badge>
                      )}
                    </div>
                  </TableCell>

                  {/* Column 6: Technical Compliance */}
                  <TableCell className="align-top py-3">
                    {renderComplianceBadge(row.technical_compliance)}
                  </TableCell>

                  {/* Column 7: Trust */}
                  <TableCell className="align-top py-3">
                    {renderTrustBadge(row.trust_status)}
                  </TableCell>

                  {/* Column 8: Decision Metrics & Recommendation */}
                  <TableCell className="align-top py-3 text-center">
                    {candidate ? (
                      <div className="space-y-1.5 inline-block text-start w-full max-w-[150px]">
                        {isRecommended && (
                          <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] gap-1 font-medium w-full justify-center">
                            <Award className="h-3 w-3 text-emerald-600" />
                            {t.decisionSupport.recommended}
                          </Badge>
                        )}
                        {isIneligible && (
                          <Badge variant="outline" className="border-rose-500/30 text-rose-700 dark:text-rose-400 bg-rose-500/10 text-[10px] gap-1 w-full justify-center">
                            <AlertTriangle className="h-3 w-3" />
                            {t.decisionSupport.ineligible}
                          </Badge>
                        )}
                        <div className="grid grid-cols-2 gap-1 text-[10px] bg-muted/30 p-1.5 rounded">
                          <div>
                            <span className="text-muted-foreground block text-[9px]">امتیاز:</span>
                            <span className="font-mono font-bold text-foreground">
                              {candidate.decision_score ?? "—"}%
                            </span>
                          </div>
                          <div>
                            <span className="text-muted-foreground block text-[9px]">پوشش:</span>
                            <span className="font-mono font-bold text-blue-600 dark:text-blue-400">
                              {candidate.evidence_coverage ?? "—"}%
                            </span>
                          </div>
                          <div>
                            <span className="text-muted-foreground block text-[9px]">مؤثر:</span>
                            <span className="font-mono font-bold text-foreground">
                              {candidate.effective_score ?? "—"}%
                            </span>
                          </div>
                          {candidate.rank && (
                            <div>
                              <span className="text-muted-foreground block text-[9px]">رتبه:</span>
                              <span className="font-mono font-bold text-primary">#{candidate.rank}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <span className="text-[11px] text-muted-foreground italic">—</span>
                    )}
                  </TableCell>

                  {/* Column 9: CTAs */}
                  <TableCell className="align-top py-3 text-end">
                    <div className="flex flex-col items-end gap-1.5">
                      {candidate && (
                        <Button
                          variant="outline"
                          onClick={() =>
                            setSelectedCandidate({
                              candidate,
                              offerorName: row.offeror_name,
                            })
                          }
                          className="h-7 min-h-7 px-2 text-[11px] gap-1 text-primary hover:text-primary hover:bg-primary/10 border-transparent"
                        >
                          <Scale className="h-3 w-3" />
                          {t.decisionSupport.whyAction}
                        </Button>
                      )}

                      {canManage && (
                        <Button
                          variant="outline"
                          onClick={() => setRevisionRow(row)}
                          className="h-7 min-h-7 px-2 text-[11px] gap-1"
                        >
                          <MessageSquare className="h-3 w-3" />
                          درخواست بازنگری
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* 2. Responsive Mobile Card View */}
      <div className="md:hidden space-y-3">
        {rows.map((row) => {
          const candidate = candidatesByVersionId.get(row.offer_version_id) || null;
          const isCrossCurrency = row.cost_comparability === "CROSS_CURRENCY_UNKNOWN";
          const isRecommended = Boolean(
            candidate && candidate.is_recommended && !isStale
          );
          const isIneligible = Boolean(candidate && candidate.award_eligible === false);

          return (
            <Card
              key={row.offer_version_id}
              className={`border shadow-xs ${
                isRecommended
                  ? "border-emerald-500 bg-emerald-500/5"
                  : isIneligible
                  ? "bg-muted/10 opacity-90"
                  : "bg-card"
              }`}
            >
              <CardContent className="p-4 space-y-3 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1">
                    <div className="font-semibold text-sm text-foreground">{row.offeror_name}</div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {renderRoleBadge(row.offeror_role, row.is_external)}
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        V{row.version_number}
                      </Badge>
                    </div>
                  </div>
                  {isRecommended && (
                    <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] gap-1">
                      <Award className="h-3 w-3" />
                      {t.decisionSupport.recommended}
                    </Badge>
                  )}
                  {isIneligible && (
                    <Badge variant="outline" className="border-rose-500/30 text-rose-700 text-[10px] gap-1">
                      <AlertTriangle className="h-3 w-3" />
                      {t.decisionSupport.ineligible}
                    </Badge>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border/50 text-xs">
                  <div>
                    <span className="text-muted-foreground block text-[10px]">{t.table.unitPrice}:</span>
                    <span className="font-mono font-bold text-foreground">
                      {row.unit_price} {row.currency}
                    </span>
                    {isCrossCurrency && (
                      <span className="text-[10px] text-amber-600 block mt-0.5">
                        {t.comparability.crossCurrency}
                      </span>
                    )}
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[10px]">{t.table.landedCost}:</span>
                    {renderUnknownCostState(row.landed_unit_cost, row.cost_comparability) || (
                      <span className="font-mono font-bold text-foreground">
                        {row.landed_unit_cost} {row.currency}
                      </span>
                    )}
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[10px]">{t.table.quantity}:</span>
                    <span className="font-mono">
                      {row.offered_quantity} {row.quantity_unit}
                    </span>
                    <span className="text-[10px] text-muted-foreground block">
                      پوشش: {(parseFloat(row.quantity_coverage) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground block text-[10px]">انطباق و اعتبار:</span>
                    <div className="flex flex-col gap-1 mt-0.5">
                      {renderComplianceBadge(row.technical_compliance)}
                      {renderTrustBadge(row.trust_status)}
                    </div>
                  </div>
                </div>

                {candidate && (
                  <div className="p-2 bg-muted/30 rounded flex items-center justify-between gap-2 text-[11px]">
                    <div>
                      امتیاز: <span className="font-mono font-bold">{candidate.decision_score ?? "—"}%</span>
                    </div>
                    <div>
                      پوشش: <span className="font-mono font-bold text-blue-600">{candidate.evidence_coverage ?? "—"}%</span>
                    </div>
                    <div>
                      مؤثر: <span className="font-mono font-bold">{candidate.effective_score ?? "—"}%</span>
                    </div>
                    {candidate.rank && (
                      <div>
                        رتبه: <span className="font-mono font-bold text-primary">#{candidate.rank}</span>
                      </div>
                    )}
                  </div>
                )}

                <div className="pt-2 border-t border-border/50 flex justify-end gap-2">
                  {candidate && (
                    <Button
                      variant="outline"
                      onClick={() =>
                        setSelectedCandidate({
                          candidate,
                          offerorName: row.offeror_name,
                        })
                      }
                      className="h-7 min-h-7 text-xs text-primary border-transparent hover:bg-muted"
                    >
                      {t.decisionSupport.whyAction}
                    </Button>
                  )}
                  {canManage && (
                    <Button
                      variant="outline"
                      onClick={() => setRevisionRow(row)}
                      className="h-7 min-h-7 text-xs"
                    >
                      درخواست بازنگری
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* 3. Why Recommendation Breakdown Modal */}
      <WhyRecommendationModal
        isOpen={selectedCandidate !== null}
        onClose={() => setSelectedCandidate(null)}
        candidate={selectedCandidate?.candidate || null}
        offerorName={selectedCandidate?.offerorName || ""}
        locale={locale}
      />

      {/* 4. Revision Request Modal */}
      <RevisionRequestModal
        isOpen={revisionRow !== null}
        onClose={() => setRevisionRow(null)}
        row={revisionRow}
        locale={locale}
        onSuccess={() => {
          onRefresh();
        }}
      />
    </div>
  );
}

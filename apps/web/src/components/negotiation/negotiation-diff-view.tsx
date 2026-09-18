"use client";

import React, { useState } from "react";
import type { EnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Layers,
  Sparkles,
} from "lucide-react";
import type {
  CostComponentDiff,
  FieldDiff,
  OfferVersionDiffResult,
} from "./diff-utility";

export interface NegotiationDiffViewProps {
  diff: OfferVersionDiffResult;
  locale?: EnabledLocale;
  defaultExpanded?: boolean;
}

export function NegotiationDiffView({
  diff,
  locale = "fa",
  defaultExpanded = false,
}: NegotiationDiffViewProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.negotiationHistory.diff;

  const [showAllFields, setShowAllFields] = useState<boolean>(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(defaultExpanded);

  const displayedFields = showAllFields
    ? diff.fields
    : diff.fields.filter((f) => f.diffType !== "unchanged");

  const displayedCostComponents = showAllFields
    ? diff.costComponents
    : diff.costComponents.filter((c) => c.diffType !== "unchanged");

  const commercialFields = displayedFields.filter(
    (f) => f.group === "commercial" || f.group === "delivery" || f.group === "logistics"
  );
  const specFields = displayedFields.filter((f) => f.group === "specification");

  const totalVisibleItems =
    displayedFields.length + displayedCostComponents.length;

  const renderDiffBadge = (diffType: FieldDiff["diffType"]) => {
    switch (diffType) {
      case "added":
        return (
          <Badge
            variant="outline"
            className="border-emerald-500/30 text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 text-[10px]"
          >
            + {t.added}
          </Badge>
        );
      case "removed":
        return (
          <Badge
            variant="outline"
            className="border-rose-500/30 text-rose-700 dark:text-rose-400 bg-rose-500/10 text-[10px]"
          >
            - {t.removed}
          </Badge>
        );
      case "changed":
        return (
          <Badge
            variant="outline"
            className="border-amber-500/30 text-amber-700 dark:text-amber-400 bg-amber-500/10 text-[10px]"
          >
            {t.changed}
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="text-muted-foreground text-[10px]">
            {t.unchanged}
          </Badge>
        );
    }
  };

  const renderFieldRow = (field: FieldDiff) => {
    return (
      <div
        key={field.fieldKey}
        className={`p-2.5 rounded-md border text-xs transition-colors ${
          field.diffType !== "unchanged"
            ? "border-amber-500/25 bg-amber-500/5 dark:bg-amber-500/10"
            : "border-border/40 bg-muted/20"
        }`}
      >
        <div className="flex items-center justify-between gap-2 flex-wrap mb-1.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-semibold text-foreground">{field.label}</span>
            {field.isRequested && (
              <Badge
                variant="secondary"
                className="bg-blue-600/10 text-blue-700 dark:text-blue-400 text-[10px] border-blue-500/20"
              >
                {t.requestedChangeBadge}
              </Badge>
            )}
          </div>
          <div>{renderDiffBadge(field.diffType)}</div>
        </div>

        {/* Previous vs New comparison */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 border-t border-border/30">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted-foreground shrink-0">
              {t.previous}:
            </span>
            <span
              className={`font-mono text-xs ${
                field.diffType !== "unchanged"
                  ? "line-through text-muted-foreground/80"
                  : "text-foreground"
              }`}
              dir="ltr"
            >
              {field.oldDisplay}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {isRtl ? (
              <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 hidden sm:inline" />
            ) : (
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 hidden sm:inline" />
            )}
            <span className="text-[11px] text-muted-foreground shrink-0">
              {t.current}:
            </span>
            <span
              className={`font-mono text-xs font-semibold ${
                field.diffType !== "unchanged"
                  ? "text-primary dark:text-primary-foreground"
                  : "text-foreground"
              }`}
              dir="ltr"
            >
              {field.newDisplay}
            </span>
          </div>
        </div>
      </div>
    );
  };

  const renderCostComponentRow = (c: CostComponentDiff) => {
    return (
      <div
        key={c.key}
        className={`p-2.5 rounded-md border text-xs transition-colors ${
          c.diffType !== "unchanged"
            ? "border-amber-500/25 bg-amber-500/5 dark:bg-amber-500/10"
            : "border-border/40 bg-muted/20"
        }`}
      >
        <div className="flex items-center justify-between gap-2 flex-wrap mb-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-foreground">
              {c.kind} {c.description ? `(${c.description})` : ""}
            </span>
          </div>
          <div>{renderDiffBadge(c.diffType)}</div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 border-t border-border/30">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted-foreground shrink-0">
              {t.previous}:
            </span>
            <span
              className={`font-mono text-xs ${
                c.diffType !== "unchanged"
                  ? "line-through text-muted-foreground/80"
                  : "text-foreground"
              }`}
              dir="ltr"
            >
              {c.oldAmount ? `${c.oldAmount} ${c.currency}` : "—"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {isRtl ? (
              <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 hidden sm:inline" />
            ) : (
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0 hidden sm:inline" />
            )}
            <span className="text-[11px] text-muted-foreground shrink-0">
              {t.current}:
            </span>
            <span
              className={`font-mono text-xs font-semibold ${
                c.diffType !== "unchanged"
                  ? "text-primary dark:text-primary-foreground"
                  : "text-foreground"
              }`}
              dir="ltr"
            >
              {c.newAmount ? `${c.newAmount} ${c.currency}` : "—"}
            </span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <Card className="border border-border/70 bg-card shadow-xs">
      <div className="p-3.5 flex items-center justify-between gap-2 flex-wrap border-b border-border/40 bg-muted/15">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-foreground">
            {t.title.replace("{base}", `V${diff.baseVersionNumber}`)}
          </span>
          <Badge
            variant="secondary"
            className="font-mono text-[10px] bg-primary/10 text-primary"
          >
            {diff.changedCount} {isRtl ? "مورد تغییر" : "changes"}
          </Badge>
        </div>

        <div className="flex items-center gap-2">
          {isExpanded && (
            <Button
              variant="outline"
              onClick={() => setShowAllFields((prev) => !prev)}
              className="h-7 min-h-7 px-2 text-[11px]"
            >
              {showAllFields ? t.showChangesOnly : t.showAllFields}
            </Button>
          )}

          <Button
            variant="outline"
            onClick={() => setIsExpanded((prev) => !prev)}
            className="h-7 min-h-7 px-2 text-xs gap-1 border-transparent hover:bg-muted"
            aria-expanded={isExpanded}
            aria-label={
              isExpanded
                ? isRtl
                  ? "بستن جزئیات تغییرات"
                  : "Collapse changes"
                : isRtl
                ? "مشاهده جزئیات تغییرات"
                : "Expand changes"
            }
          >
            {isExpanded ? (
              <>
                <ChevronUp className="h-3.5 w-3.5" />
                <span>{isRtl ? "بستن" : "Collapse"}</span>
              </>
            ) : (
              <>
                <ChevronDown className="h-3.5 w-3.5" />
                <span>{isRtl ? "مشاهده جزئیات" : "View details"}</span>
              </>
            )}
          </Button>
        </div>
      </div>

      {isExpanded && (
        <CardContent className="p-4 space-y-4">
          {totalVisibleItems === 0 ? (
            <div className="p-4 text-center text-muted-foreground text-xs">
              <CheckCircle2 className="h-5 w-5 text-emerald-600 mx-auto mb-1.5" />
              {t.noChanges}
            </div>
          ) : (
            <>
              {/* 1. Commercial & Delivery Group */}
              {commercialFields.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1.5 pb-1 border-b border-border/30">
                    <Sparkles className="h-3.5 w-3.5 text-primary" />
                    {t.sections.commercial}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {commercialFields.map(renderFieldRow)}
                  </div>
                </div>
              )}

              {/* 2. Dynamic Specifications Group */}
              {specFields.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-muted-foreground flex items-center gap-1.5 pb-1 border-b border-border/30">
                    <Layers className="h-3.5 w-3.5 text-primary" />
                    {t.sections.specifications}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {specFields.map(renderFieldRow)}
                  </div>
                </div>
              )}

              {/* 3. Cost Components Group */}
              {displayedCostComponents.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-muted-foreground pb-1 border-b border-border/30">
                    {t.sections.costComponents}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {displayedCostComponents.map(renderCostComponentRow)}
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
}

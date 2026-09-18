"use client";

import React from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  XCircle,
  X,
  Scale,
} from "lucide-react";

type DecisionCandidateResponse = components["schemas"]["DecisionCandidateResponse"];
type DecisionSignalResponse = components["schemas"]["DecisionSignalResponse"];

export interface WhyRecommendationModalProps {
  isOpen: boolean;
  onClose: () => void;
  candidate: DecisionCandidateResponse | null;
  offerorName: string;
  locale?: EnabledLocale;
}

function formatValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return null;
  }
}

function mapReasonCodeToText(reasonCode: string): string {
  const mapping: Record<string, string> = {
    cost_best_in_market: "بهترین قیمت تمام‌شده در میان پیشنهادهای ارائه‌شده",
    cost_higher_than_best: "قیمت بالاتر از کمترین پیشنهاد موجود",
    cost_unknown_logistics: "هزینه حمل نامشخص است؛ امکان محاسبه قیمت تمام‌شده وجود ندارد",
    cost_cross_currency: "ارز متفاوت بدون نرخ تسعیر رسمی؛ هزینه قابل مقایسه نیست",
    quality_spec_pass: "تمام مشخصات فنی کالا با نیازمندی استعلام منطبق است",
    quality_spec_fail: "حداقل یکی از مشخصات فنی کلیدی با نیازمندی استعلام مغایرت دارد",
    quality_spec_unknown: "بخشی از مشخصات فنی کالا در پیشنهاد مشخص نشده است",
    delivery_within_window: "بازه تحویل پیشنهادی کاملاً در مهلت مقرر استعلام قرار دارد",
    delivery_partial_overlap: "بازه تحویل همپوشانی جزئی با زمان‌بندی مورد نیاز دارد",
    delivery_incompatible: "بازه تحویل خارج از مهلت تعیین‌شده استعلام است",
    delivery_unspecified: "زمان‌بندی و شرایط تحویل مشخص نشده است",
    payment_terms_standard: "شرایط پرداخت با الزامات استعلام همخوانی دارد",
    payment_terms_unknown: "شرایط پرداخت نامشخص یا ساختارنیافته است",
    trust_org_verified: "سازمان دارای گواهی احراز هویت معتبر است",
    trust_org_basic: "سازمان دارای سطح احراز هویت پایه است",
    trust_org_unverified: "سازمان هنوز مراحل احراز هویت را تکمیل نکرده است",
    trust_org_suspended: "سازمان در وضعیت تعلیق قرار دارد (فاقد صلاحیت معامله)",
    trust_external_unknown: "پیشنهاد از منبع خارج از بستر (بدون احراز هویت سیستمی)",
    completeness_full: "تمام مؤلفه‌های کلیدی تجاری و هزینه‌ای تکمیل شده است",
    completeness_missing_data: "برخی مؤلفه‌های ضروری پیشنهاد ثبت نشده‌اند",
  };
  return mapping[reasonCode] || reasonCode;
}

export function WhyRecommendationModal({
  isOpen,
  onClose,
  candidate,
  offerorName,
  locale = "fa",
}: WhyRecommendationModalProps) {
  if (!isOpen || !candidate) return null;

  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.comparison.whyModal;
  const isRtl = locale === "fa";

  const signals = candidate.signals || [];

  // Deterministic signal grouping according to Contract requirements
  const positives = signals.filter((s) => s.status === "PASS");
  const risks = signals.filter((s) => s.status === "FAIL" || s.status === "PARTIAL");
  const unknowns = signals.filter(
    (s) => s.status === "UNKNOWN" || s.status === "NOT_APPLICABLE"
  );

  const renderSignalBadge = (status: DecisionSignalResponse["status"]) => {
    switch (status) {
      case "PASS":
        return (
          <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-xs flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />
            منطبق
          </Badge>
        );
      case "PARTIAL":
        return (
          <Badge className="bg-amber-600/10 text-amber-700 dark:text-amber-400 border-amber-500/20 text-xs flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            انطباق جزئی
          </Badge>
        );
      case "FAIL":
        return (
          <Badge className="bg-rose-600/10 text-rose-700 dark:text-rose-400 border-rose-500/20 text-xs flex items-center gap-1">
            <XCircle className="h-3 w-3" />
            نامنطبق
          </Badge>
        );
      case "NOT_APPLICABLE":
        return (
          <Badge variant="outline" className="text-muted-foreground text-xs">
            عدم شمول
          </Badge>
        );
      case "UNKNOWN":
      default:
        return (
          <Badge variant="outline" className="text-amber-600 border-amber-300 text-xs flex items-center gap-1">
            <HelpCircle className="h-3 w-3" />
            نامشخص
          </Badge>
        );
    }
  };

  const renderSignalList = (list: DecisionSignalResponse[], emptyNotice: string) => {
    if (list.length === 0) {
      return (
        <div className="p-3 text-xs text-muted-foreground italic bg-muted/20 rounded border border-dashed text-center">
          {emptyNotice}
        </div>
      );
    }

    return (
      <div className="space-y-2.5">
        {list.map((signal) => {
          const dimensionName = t.dimensions[signal.dimension] || signal.dimension;
          const reasonText = mapReasonCodeToText(signal.reason_code);
          const expectedStr = formatValue(signal.expected_value);
          const actualStr = formatValue(signal.actual_value);

          return (
            <div
              key={signal.id}
              className="p-3 rounded-md border bg-card/60 text-xs space-y-2 transition-colors hover:bg-card"
            >
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-foreground text-sm">{dimensionName}</span>
                  {renderSignalBadge(signal.status)}
                </div>
                <div className="flex items-center gap-3 text-muted-foreground text-[11px]">
                  {signal.weight && (
                    <span>
                      {t.weight} <span className="font-mono text-foreground font-medium">{signal.weight}%</span>
                    </span>
                  )}
                  {signal.contribution && (
                    <span>
                      {t.contribution} <span className="font-mono text-foreground font-medium">{signal.contribution}%</span>
                    </span>
                  )}
                </div>
              </div>

              <div className="text-muted-foreground leading-relaxed text-xs">
                {reasonText}
              </div>

              {(expectedStr !== null || actualStr !== null) && (
                <div className="pt-1.5 border-t border-muted/50 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                  {expectedStr !== null && (
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-muted-foreground block text-[10px] mb-0.5">{t.expected}:</span>
                      <span className="font-mono text-foreground break-all">{expectedStr}</span>
                    </div>
                  )}
                  {actualStr !== null && (
                    <div className="bg-muted/30 p-1.5 rounded">
                      <span className="text-muted-foreground block text-[10px] mb-0.5">{t.actual}:</span>
                      <span className="font-mono text-foreground break-all">{actualStr}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 overflow-y-auto"
      dir={isRtl ? "rtl" : "ltr"}
      role="dialog"
      aria-modal="true"
      aria-labelledby="why-modal-title"
    >
      <Card className="w-full max-w-2xl shadow-xl max-h-[90vh] flex flex-col my-auto border-border">
        <CardHeader className="border-b pb-3 flex flex-row items-center justify-between shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <Scale className="h-5 w-5 text-primary" />
              <CardTitle id="why-modal-title" className="text-base font-semibold">
                {t.title}
              </CardTitle>
            </div>
            <CardDescription className="text-xs mt-1">
              پیشنهاد {offerorName} (نسخه V{candidate.version_number}) · {t.subtitle}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            onClick={onClose}
            className="h-8 min-h-8 w-8 p-0 rounded-full border-transparent hover:bg-muted"
            aria-label={t.close}
          >
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>

        <CardContent className="p-4 sm:p-6 overflow-y-auto space-y-6">
          {/* Group 1: نقاط مثبت */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4" />
              {t.positiveGroup} ({positives.length})
            </h4>
            {renderSignalList(positives, "سیگنال انطباق کامل ثبت نشده است.")}
          </div>

          {/* Group 2: ریسک‌ها */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-rose-700 dark:text-rose-400 flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4" />
              {t.riskGroup} ({risks.length})
            </h4>
            {renderSignalList(risks, "ریسک یا عدم انطباق بحرانی شناسایی نشد.")}
          </div>

          {/* Group 3: اطلاعات نامشخص */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
              <HelpCircle className="h-4 w-4" />
              {t.unknownGroup} ({unknowns.length})
            </h4>
            {renderSignalList(unknowns, "اطلاعات نامشخصی در این پیشنهاد وجود ندارد.")}
          </div>
        </CardContent>

        <div className="border-t p-3 flex justify-end shrink-0 bg-muted/20">
          <Button variant="outline" onClick={onClose} className="min-w-24 min-h-9 text-xs">
            {t.close}
          </Button>
        </div>
      </Card>
    </div>
  );
}

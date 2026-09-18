"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, History, Loader2, MessageSquare, RefreshCw, ShieldAlert } from "lucide-react";
import { NegotiationHistoryModal } from "./negotiation-history-modal";

type ComparisonRow = components["schemas"]["ComparisonRow"];
type RFQComparisonResponse = components["schemas"]["RFQComparisonResponse"];

export interface RFQNegotiationTabProps {
  rfqId: string;
  canManage: boolean;
  isOperator: boolean;
  locale?: EnabledLocale;
}

export function RFQNegotiationTab({
  rfqId,
  canManage,
  isOperator,
  locale = "fa",
}: RFQNegotiationTabProps) {
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace;
  const isRtl = locale === "fa";
  const { state } = useAuth();

  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const roleKey = state.status === "authenticated" ? state.systemRoles.join(",") : "anon";

  const [comparison, setComparison] = useState<RFQComparisonResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUnauthorized, setIsUnauthorized] = useState<boolean>(false);
  const [selectedOfferId, setSelectedOfferId] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState<number>(0);

  const fetchGenerationRef = useRef<number>(0);

  const triggerRefresh = useCallback(() => {
    setRefreshIndex((prev) => prev + 1);
  }, []);

  useEffect(() => {
    const generation = ++fetchGenerationRef.current;
    let ignore = false;
    const controller = new AbortController();

    async function loadOffers() {
      setIsLoading(true);
      setErrorMessage(null);
      setIsUnauthorized(false);

      try {
        const { data, response, error } = await apiClient.GET(
          "/api/offers/rfqs/{rfq_id}/comparison/",
          {
            params: { path: { rfq_id: rfqId } },
            signal: controller.signal,
          }
        );

        if (ignore || generation !== fetchGenerationRef.current) return;

        if (response.status === 403) {
          setIsUnauthorized(true);
          setComparison(null);
          return;
        }

        if (response.ok && data) {
          setComparison(data);
        } else {
          const errPayload = error as { detail?: string } | undefined;
          const detail =
            errPayload && typeof errPayload === "object" && "detail" in errPayload
              ? String(errPayload.detail)
              : isRtl
              ? "خطا در دریافت پیشنهادهای استعلام."
              : "Failed to load offers for RFQ.";
          setErrorMessage(detail);
        }
      } catch (err: unknown) {
        if (ignore || generation !== fetchGenerationRef.current) return;
        if ((err as Error)?.name !== "AbortError") {
          setErrorMessage(
            isRtl ? "خطای ارتباط با سرور." : "Network connection error."
          );
        }
      } finally {
        if (!ignore && generation === fetchGenerationRef.current) {
          setIsLoading(false);
        }
      }
    }

    void loadOffers();

    return () => {
      ignore = true;
      controller.abort();
    };
  }, [rfqId, currentOrgId, roleKey, refreshIndex, isRtl]);

  const renderRoleBadge = (role: string, isExternal: boolean) => {
    if (isExternal) {
      return (
        <Badge variant="outline" className="border-indigo-500/30 text-indigo-700 dark:text-indigo-400 bg-indigo-500/10 text-[11px]">
          {isRtl ? "طرف برون‌سامانه‌ای" : "External Party"}
        </Badge>
      );
    }
    if (role === "BROKER") {
      return (
        <Badge variant="outline" className="border-purple-500/30 text-purple-700 dark:text-purple-400 bg-purple-500/10 text-[11px]">
          {isRtl ? "کارگزار" : "Broker"}
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="border-blue-500/30 text-blue-700 dark:text-blue-400 bg-blue-500/10 text-[11px]">
        {isRtl ? "تأمین‌کننده" : "Supplier"}
      </Badge>
    );
  };

  const rows: ComparisonRow[] = (comparison?.items || comparison?.offers || []) as ComparisonRow[];

  return (
    <div className="space-y-4" dir={isRtl ? "rtl" : "ltr"}>
      {/* Header card */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div className="space-y-1">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-primary" />
              {isRtl ? "مذاکرات و تاریخچه پیشنهادها" : "Negotiations and Offer Histories"}
            </CardTitle>
            <CardDescription className="text-xs">
              {isRtl
                ? "سیر بازنگری، درخواست‌ها و مقایسه دقیق نسخه‌های مختلف پیشنهادهای این استعلام"
                : "Audit trail of revisions, requests, and structured diffs across offer versions"}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            onClick={triggerRefresh}
            disabled={isLoading}
            className="h-8 min-h-8 text-xs gap-1"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            {isRtl ? "به‌روزرسانی" : "Refresh"}
          </Button>
        </CardHeader>
      </Card>

      {/* Unauthorized State */}
      {isUnauthorized && (
        <Card className="border-rose-500/30 bg-rose-500/5">
          <CardContent className="p-8 text-center space-y-3">
            <ShieldAlert className="h-10 w-10 text-rose-600 mx-auto" />
            <h3 className="font-semibold text-rose-900 dark:text-rose-200">
              {isRtl ? "عدم دسترسی به بخش مذاکرات" : "Unauthorized Access"}
            </h3>
            <p className="text-xs text-rose-700 dark:text-rose-300 max-w-md mx-auto">
              {isRtl
                ? "تنها اعضای سازمان خریدار این استعلام و اپراتورهای سامانه مجاز به مشاهده تاریخچه مذاکرات هستند."
                : "Only members of the buyer organization and operators are authorized to view negotiation histories."}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Loading State */}
      {isLoading && !comparison && (
        <Card>
          <CardContent className="p-12 flex flex-col items-center justify-center space-y-3 text-muted-foreground">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="text-xs">{t.negotiationHistory?.loading || "در حال بارگذاری پیشنهادها…"}</span>
          </CardContent>
        </Card>
      )}

      {/* Error State */}
      {errorMessage && !isLoading && (
        <Card className="border-rose-500/30 bg-rose-500/5">
          <CardContent className="p-6 flex items-start gap-3 text-rose-800 dark:text-rose-200 text-xs">
            <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">{isRtl ? "خطا در بارگذاری" : "Error Loading Data"}</p>
              <p className="mt-1">{errorMessage}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty State */}
      {!isLoading && !isUnauthorized && !errorMessage && rows.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center space-y-3 text-muted-foreground">
            <History className="h-10 w-10 mx-auto text-muted-foreground/50" />
            <h3 className="font-medium text-sm text-foreground">
              {isRtl ? "هیچ پیشنهادی برای مذاکره ثبت نشده است" : "No Offers Submitted Yet"}
            </h3>
            <p className="text-xs max-w-md mx-auto">
              {isRtl
                ? "پس از ثبت پیشنهاد توسط تأمین‌کنندگان یا کارگزاران، تاریخچه رفت‌وبرگشت مذاکرات در این بخش در دسترس خواهد بود."
                : "Once suppliers or brokers submit offers, the complete revision history will appear here."}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Offers List */}
      {!isLoading && !isUnauthorized && rows.length > 0 && (
        <div className="grid grid-cols-1 gap-3">
          {rows.map((row: ComparisonRow) => (
            <Card key={row.offer_id} className="hover:border-primary/40 transition-colors">
              <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-foreground">{row.offeror_name}</span>
                    {renderRoleBadge(row.offeror_role, row.is_external)}
                    <Badge variant="secondary" className="font-mono text-xs">
                      V{row.version_number}
                    </Badge>
                  </div>

                  <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                    <div>
                      <span>{isRtl ? "قیمت واحد: " : "Unit Price: "}</span>
                      <span className="font-mono font-bold text-foreground">
                        {row.unit_price} {row.currency}
                      </span>
                    </div>
                    <div>
                      <span>{isRtl ? "مقدار: " : "Quantity: "}</span>
                      <span className="font-mono text-foreground">
                        {row.offered_quantity} {row.quantity_unit}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setSelectedOfferId(row.offer_id)}
                    className="h-8 min-h-8 text-xs gap-1.5"
                  >
                    <History className="h-3.5 w-3.5 text-primary" />
                    {isRtl ? "مشاهده تاریخچه مذاکرات" : "View History"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Negotiation History Modal */}
      <NegotiationHistoryModal
        isOpen={selectedOfferId !== null}
        onClose={() => setSelectedOfferId(null)}
        offerId={selectedOfferId || ""}
        canManage={canManage}
        isOperator={isOperator}
        locale={locale}
        onActionCompleted={() => {
          triggerRefresh();
        }}
      />
    </div>
  );
}

"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { RefreshCw, Scale } from "lucide-react";
import { DecisionRunCard } from "./decision-run-card";
import { ComparisonTable } from "./comparison-table";
import {
  LoadingState,
  EmptyState,
  ErrorState,
  AccessDeniedState,
} from "@/components/states";

type RFQComparisonResponse = components["schemas"]["RFQComparisonResponse"];
type DecisionRunDetailResponse = components["schemas"]["DecisionRunDetailResponse"];

export interface RFQComparisonTabProps {
  rfqId: string;
  canManage: boolean;
  isOperator: boolean;
  locale?: EnabledLocale;
}

export function RFQComparisonTab({
  rfqId,
  canManage,
  isOperator,
  locale = "fa",
}: RFQComparisonTabProps) {
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.comparison;
  const isRtl = locale === "fa";
  const { state } = useAuth();

  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const roleKey = state.status === "authenticated" ? state.systemRoles.join(",") : "anon";

  // Core Data
  const [comparison, setComparison] = useState<RFQComparisonResponse | null>(null);
  const [decisionRun, setDecisionRun] = useState<DecisionRunDetailResponse | null>(null);

  // Loading & Error States
  const [isLoadingComparison, setIsLoadingComparison] = useState<boolean>(true);
  const [isLoadingRun, setIsLoadingRun] = useState<boolean>(true);
  const [isExecutingRun, setIsExecutingRun] = useState<boolean>(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [isUnauthorized, setIsUnauthorized] = useState<boolean>(false);
  const [refreshIndex, setRefreshIndex] = useState<number>(0);

  // In-flight race isolation generation counters
  const fetchGenerationRef = useRef<number>(0);

  const triggerRefresh = useCallback(() => {
    setRefreshIndex((prev) => prev + 1);
  }, []);

  // 1. Authoritative Comparison Fetch with In-flight Cancellation Guard
  useEffect(() => {
    const generation = ++fetchGenerationRef.current;
    let ignore = false;
    const controller = new AbortController();

    async function loadComparison() {
      setIsLoadingComparison(true);
      setComparisonError(null);
      setIsUnauthorized(false);

      try {
        const { data, response, error } = await apiClient.GET(
          "/api/offers/rfqs/{rfq_id}/comparison/",
          {
            params: { path: { rfq_id: rfqId } },
            signal: controller.signal,
          }
        );

        // If persona switched or unmounted, discard late response
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
              : "خطا در دریافت داده‌های مقایسه.";
          setComparisonError(detail);
        }
      } catch (err: unknown) {
        if (ignore || generation !== fetchGenerationRef.current) return;
        if ((err as Error)?.name !== "AbortError") {
          setComparisonError("خطای ارتباط با سرور در بارگذاری مقایسه.");
        }
      } finally {
        if (!ignore && generation === fetchGenerationRef.current) {
          setIsLoadingComparison(false);
        }
      }
    }

    void loadComparison();

    return () => {
      ignore = true;
      controller.abort();
    };
  }, [rfqId, currentOrgId, roleKey, refreshIndex]);

  // 2. Authoritative DecisionRun Fetch with In-flight Cancellation Guard
  useEffect(() => {
    const generation = fetchGenerationRef.current;
    let ignore = false;
    const controller = new AbortController();

    async function loadDecisionRun() {
      setIsLoadingRun(true);

      try {
        const { data, response } = await apiClient.GET(
          "/api/offers/rfqs/{rfq_id}/decision-runs/",
          {
            params: { path: { rfq_id: rfqId } },
            signal: controller.signal,
          }
        );

        if (ignore || generation !== fetchGenerationRef.current) return;

        if (response.status === 200 && data) {
          setDecisionRun(data);
        } else if (response.status === 404) {
          // Normal state: no run executed yet
          setDecisionRun(null);
        }
      } catch (err: unknown) {
        if (ignore || generation !== fetchGenerationRef.current) return;
        if ((err as Error)?.name !== "AbortError") {
          // If error, clear decision run
          setDecisionRun(null);
        }
      } finally {
        if (!ignore && generation === fetchGenerationRef.current) {
          setIsLoadingRun(false);
        }
      }
    }

    void loadDecisionRun();

    return () => {
      ignore = true;
      controller.abort();
    };
  }, [rfqId, currentOrgId, roleKey, refreshIndex]);

  // 3. Execute DecisionRun Action (Authorized Run or Re-run)
  const handleExecuteDecisionRun = async () => {
    setIsExecutingRun(true);
    try {
      const { data, response, error } = await apiClient.POST(
        "/api/offers/rfqs/{rfq_id}/decision-runs/",
        {
          params: { path: { rfq_id: rfqId } },
          body: {},
        }
      );

      if (response.status === 201 && data) {
        setDecisionRun(data);
        triggerRefresh();
      } else {
        const errPayload = error as { detail?: string } | undefined;
        const detail =
          errPayload && typeof errPayload === "object" && "detail" in errPayload
            ? String(errPayload.detail)
            : "اجرای ارزیابی تصمیم با خطا مواجه شد.";
        setComparisonError(detail);
      }
    } catch {
      setComparisonError("خطای ارتباط با سرور در اجرای ارزیابی تصمیم.");
    } finally {
      setIsExecutingRun(false);
    }
  };

  // State: Loading Initial
  if (isLoadingComparison && !comparison) {
    return <LoadingState variant="section" message={t.loading} locale={locale} />;
  }

  // State: Access Denied / Unauthorized
  if (isUnauthorized) {
    return (
      <AccessDeniedState
        statusCode={403}
        title="عدم دسترسی به مقایسه پیشنهادها"
        description={t.unauthorized}
        locale={locale}
      />
    );
  }

  // State: Error
  if (comparisonError && !comparison) {
    return (
      <ErrorState
        errorMessage={comparisonError}
        onRetry={triggerRefresh}
        locale={locale}
      />
    );
  }

  const items = comparison?.items || [];

  return (
    <div className="space-y-5" dir={isRtl ? "rtl" : "ltr"}>
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-1 border-b border-border/60">
        <div>
          <h3 className="text-base font-bold text-foreground flex items-center gap-2">
            <Scale className="h-5 w-5 text-primary" />
            {t.title}
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">{t.subtitle}</p>
        </div>

        <div className="flex items-center gap-2 self-end sm:self-auto">
          {items.length > 0 && (
            <span className="text-xs text-muted-foreground">
              {t.totalOffers} <span className="font-mono font-bold text-foreground">{items.length}</span>
            </span>
          )}
          <Button
            variant="outline"
            onClick={triggerRefresh}
            className="h-8 min-h-8 w-8 p-0 border-transparent hover:bg-muted"
            aria-label={t.refresh}
          >
            <RefreshCw className={`h-4 w-4 ${isLoadingComparison ? "animate-spin text-primary" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Decision Intelligence Support Card */}
      {items.length > 0 && (
        <DecisionRunCard
          run={decisionRun}
          isLoadingRun={isLoadingRun}
          isExecutingRun={isExecutingRun}
          hasOffers={items.length > 0}
          onExecuteRun={handleExecuteDecisionRun}
          locale={locale}
        />
      )}

      {/* Comparison Universe Content */}
      {items.length === 0 ? (
        <EmptyState
          icon={<Scale className="h-10 w-10 text-muted-foreground/40" />}
          title={t.noOffersTitle}
          description={t.noOffersDesc}
          locale={locale}
        />
      ) : (
        <ComparisonTable
          rows={items}
          rfqCurrency={comparison?.rfq_currency || "USD"}
          rfqQuantity={comparison?.rfq_quantity || "0"}
          rfqUnit={comparison?.rfq_unit || "MT"}
          decisionRun={decisionRun}
          isOperator={isOperator}
          canManage={canManage}
          locale={locale}
          onRefresh={triggerRefresh}
        />
      )}
    </div>
  );
}

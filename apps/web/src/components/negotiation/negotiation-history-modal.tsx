"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileEdit,
  History,
  Info,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldAlert,
  Tag,
  UserCheck,
  X,
  XCircle,
} from "lucide-react";
import { buildNegotiationTimeline, type TimelineItem } from "./timeline-builder";
import { NegotiationDiffView } from "./negotiation-diff-view";

export type OfferNegotiationHistoryResponse =
  components["schemas"]["OfferNegotiationHistoryResponse"];
export type OfferVersionHistory = components["schemas"]["OfferVersionHistory"];

export interface NegotiationHistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  offerId: string;
  rfqId?: string;
  canManage?: boolean; // Buyer can manage RFQ
  isOperator?: boolean;
  locale?: EnabledLocale;
  onActionCompleted?: () => void;
}

export function NegotiationHistoryModal({
  isOpen,
  onClose,
  offerId,
  canManage = false,
  isOperator: propIsOperator = false,
  locale = "fa",
  onActionCompleted,
}: NegotiationHistoryModalProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.negotiationHistory;
  const { state } = useAuth();

  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const isSystemOperator =
    propIsOperator ||
    (state.status === "authenticated" &&
      state.systemRoles.some((r) => r === "operator" || r === "admin"));
  const roleKey = state.status === "authenticated" ? state.systemRoles.join(",") : "anon";

  // Data states
  const [history, setHistory] = useState<OfferNegotiationHistoryResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUnauthorized, setIsUnauthorized] = useState<boolean>(false);
  const [isNotFound, setIsNotFound] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState<number>(0);

  // Action loading states
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // In-flight race isolation generation counters
  const fetchGenerationRef = useRef<number>(0);

  const triggerRefresh = useCallback(() => {
    setRefreshCounter((prev) => prev + 1);
  }, []);

  // Fetch negotiation history with in-flight race cancellation
  useEffect(() => {
    if (!isOpen || !offerId) {
      return () => {
        setHistory(null);
        setIsLoading(false);
      };
    }

    const generation = ++fetchGenerationRef.current;
    let ignore = false;
    const controller = new AbortController();

    async function loadHistory() {
      setIsLoading(true);
      setErrorMessage(null);
      setIsUnauthorized(false);
      setIsNotFound(false);
      setActionError(null);
      setActionSuccess(null);

      try {
        const { data, response, error } = await apiClient.GET(
          "/api/offers/{offer_id}/history/",
          {
            params: { path: { offer_id: offerId } },
            signal: controller.signal,
          }
        );

        // Discard late response if unmounted, offerId changed, or persona switched
        if (ignore || generation !== fetchGenerationRef.current) return;

        if (response.status === 401 || response.status === 403) {
          setIsUnauthorized(true);
          setHistory(null);
          return;
        }

        if (response.status === 404) {
          setIsNotFound(true);
          setHistory(null);
          return;
        }

        if (response.ok && data) {
          setHistory(data);
        } else {
          const errPayload = error as { detail?: string } | undefined;
          setErrorMessage(errPayload?.detail || t.error);
        }
      } catch (err: unknown) {
        if (ignore || generation !== fetchGenerationRef.current) return;
        if ((err as Error)?.name !== "AbortError") {
          setErrorMessage(t.error);
        }
      } finally {
        if (!ignore && generation === fetchGenerationRef.current) {
          setIsLoading(false);
        }
      }
    }

    void loadHistory();

    return () => {
      ignore = true;
      controller.abort();
    };
  }, [isOpen, offerId, currentOrgId, roleKey, refreshCounter, t.error]);

  if (!isOpen) return null;

  // Derive roles
  const isOfferingOrgMember = Boolean(
    history &&
      currentOrgId &&
      !history.is_external &&
      state.status === "authenticated"
  );
  const canOfferPartyAct = isSystemOperator || isOfferingOrgMember;
  const canBuyerAct = isSystemOperator || canManage;

  // Actions on Revision Requests
  const handleDeclineRequest = async (requestId: string) => {
    if (!history) return;
    setActionInProgress(`decline:${requestId}`);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/revision-requests/{request_id}/decline/",
        {
          params: { path: { request_id: requestId } },
          body: { expected_version: history.aggregate_version },
        }
      );

      if (response.status === 200) {
        setActionSuccess(t.toasts.declineSuccess);
        triggerRefresh();
        onActionCompleted?.();
      } else {
        const errPayload = error as { detail?: string } | undefined;
        setActionError(errPayload?.detail || t.toasts.declineError);
      }
    } catch {
      setActionError(t.toasts.serverError);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleCancelRequest = async (requestId: string) => {
    if (!history) return;
    setActionInProgress(`cancel:${requestId}`);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/revision-requests/{request_id}/cancel/",
        {
          params: { path: { request_id: requestId } },
          body: { expected_version: history.aggregate_version },
        }
      );

      if (response.status === 200) {
        setActionSuccess(t.toasts.cancelSuccess);
        triggerRefresh();
        onActionCompleted?.();
      } else {
        const errPayload = error as { detail?: string } | undefined;
        setActionError(errPayload?.detail || t.toasts.cancelError);
      }
    } catch {
      setActionError(t.toasts.serverError);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleCreateDraft = async (requestId: string) => {
    if (!history) return;
    setActionInProgress(`draft:${requestId}`);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/revision-requests/{request_id}/draft/",
        {
          params: { path: { request_id: requestId } },
          body: { expected_version: history.aggregate_version },
        }
      );

      if (response.status === 201) {
        setActionSuccess(t.toasts.draftSuccess);
        triggerRefresh();
        onActionCompleted?.();
      } else {
        const errPayload = error as { detail?: string } | undefined;
        setActionError(errPayload?.detail || t.toasts.draftError);
      }
    } catch {
      setActionError(t.toasts.serverError);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSubmitDraft = async (requestId: string, draftVersionId: string) => {
    if (!history) return;
    setActionInProgress(`submit:${draftVersionId}`);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/revision-requests/{request_id}/submit/",
        {
          params: { path: { request_id: requestId } },
          body: {
            expected_version: history.aggregate_version,
            draft_version_id: draftVersionId,
          },
        }
      );

      if (response.status === 200) {
        setActionSuccess(t.toasts.submitSuccess);
        triggerRefresh();
        onActionCompleted?.();
      } else {
        const errPayload = error as { detail?: string } | undefined;
        setActionError(errPayload?.detail || t.toasts.submitError);
      }
    } catch {
      setActionError(t.toasts.serverError);
    } finally {
      setActionInProgress(null);
    }
  };

  const timelineItems: TimelineItem[] = history
    ? buildNegotiationTimeline(
        history.versions,
        history.revision_requests,
        history.schema,
        locale
      )
    : [];

  const openRevisionRequest = history?.revision_requests.find(
    (r) => r.status === "OPEN"
  );

  const renderRoleBadge = (role: string, isExternal: boolean) => {
    if (isExternal) {
      return (
        <Badge
          variant="outline"
          className="border-indigo-500/30 text-indigo-700 dark:text-indigo-400 bg-indigo-500/10 text-xs"
        >
          {t.roles.externalSupply}
        </Badge>
      );
    }
    if (role === "BROKER") {
      return (
        <Badge
          variant="outline"
          className="border-purple-500/30 text-purple-700 dark:text-purple-400 bg-purple-500/10 text-xs"
        >
          {t.roles.broker}
        </Badge>
      );
    }
    return (
      <Badge
        variant="outline"
        className="border-blue-500/30 text-blue-700 dark:text-blue-400 bg-blue-500/10 text-xs"
      >
        {t.roles.supplier}
      </Badge>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-3 sm:p-6 overflow-y-auto"
      dir={isRtl ? "rtl" : "ltr"}
      role="dialog"
      aria-modal="true"
      aria-labelledby="negotiation-history-modal-title"
    >
      <div className="relative w-full max-w-4xl bg-background rounded-lg border border-border shadow-xl flex flex-col max-h-[92vh] overflow-hidden my-auto animate-in fade-in-50 zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="p-4 sm:p-5 border-b border-border flex items-start justify-between gap-3 bg-muted/20">
          <div className="space-y-1">
            <h2
              id="negotiation-history-modal-title"
              className="text-base sm:text-lg font-bold text-foreground flex items-center gap-2"
            >
              <History className="h-5 w-5 text-primary shrink-0" />
              {t.title}
            </h2>
            <p className="text-xs text-muted-foreground">{t.subtitle}</p>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={triggerRefresh}
              className="h-8 min-h-8 w-8 p-0"
              aria-label={t.refresh}
            >
              <RefreshCw
                className={`h-4 w-4 ${isLoading ? "animate-spin text-primary" : ""}`}
              />
            </Button>
            <Button
              variant="outline"
              onClick={onClose}
              className="h-8 min-h-8 w-8 p-0 border-transparent hover:bg-muted"
              aria-label={t.close}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-4 sm:p-6 overflow-y-auto space-y-5 flex-1">
          {/* Action Alerts */}
          {actionError && (
            <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-destructive text-xs flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          {actionSuccess && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-md text-emerald-700 dark:text-emerald-400 text-xs flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{actionSuccess}</span>
            </div>
          )}

          {/* Loading State */}
          {isLoading && !history && (
            <div className="flex flex-col items-center justify-center p-12 text-center text-muted-foreground space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-sm font-medium">{t.loading}</p>
            </div>
          )}

          {/* Unauthorized State */}
          {isUnauthorized && (
            <Card className="border border-amber-500/30 bg-amber-500/5 p-6 text-center">
              <CardContent className="space-y-3">
                <ShieldAlert className="h-10 w-10 text-amber-600 mx-auto" />
                <div className="text-sm font-semibold text-foreground">
                  {t.unauthorized}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Not Found State */}
          {isNotFound && (
            <Card className="border border-muted p-6 text-center">
              <CardContent className="space-y-3">
                <AlertTriangle className="h-10 w-10 text-muted-foreground mx-auto" />
                <div className="text-sm font-semibold text-foreground">
                  {t.notFound}
                </div>
              </CardContent>
            </Card>
          )}

          {/* General Error State */}
          {errorMessage && !history && (
            <Card className="border border-destructive/30 bg-destructive/5 p-6 text-center">
              <CardContent className="space-y-3">
                <AlertTriangle className="h-8 w-8 text-destructive mx-auto" />
                <div className="text-sm font-semibold text-destructive">
                  {errorMessage}
                </div>
                <Button
                  variant="outline"
                  onClick={triggerRefresh}
                  className="text-xs min-h-8"
                >
                  <RefreshCw className="h-3.5 w-3.5 mr-1" />
                  {t.refresh}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Populated History View */}
          {history && (
            <div className="space-y-6">
              {/* Offer Header / Commercial Identity */}
              <Card className="border border-border/80 bg-muted/10 shadow-xs">
                <CardContent className="p-4 space-y-3 text-xs">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">
                        {t.header.offeror}
                      </div>
                      <div className="text-base font-bold text-foreground">
                        {history.counterparty_name}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      {renderRoleBadge(history.offeror_role, history.is_external)}
                      <Badge variant="secondary" className="font-mono text-xs">
                        v{history.aggregate_version}
                      </Badge>
                    </div>
                  </div>

                  {/* Economic Party vs Entering Actor Clarity */}
                  {history.entered_by_operator && (
                    <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded text-[11px] text-indigo-900 dark:text-indigo-200 flex items-center gap-1.5">
                      <UserCheck className="h-3.5 w-3.5 shrink-0 text-indigo-600" />
                      <span>
                        <strong className="font-semibold">
                          {t.noteLabel}
                        </strong>{" "}
                        {t.header.operatorEntered}
                      </span>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Negotiation Timeline */}
              <div className="space-y-4">
                <h3 className="text-sm font-bold text-foreground flex items-center gap-2 pb-1 border-b border-border/40">
                  <Clock className="h-4 w-4 text-primary" />
                  {t.timeline.title}
                </h3>

                {timelineItems.length === 0 ? (
                  <div className="p-8 text-center text-muted-foreground text-xs">
                    {t.emptyState.noHistory}
                  </div>
                ) : (
                  <div className="space-y-4 relative before:absolute before:inset-0 before:right-3.5 sm:before:right-4 before:w-0.5 before:bg-border/60 before:z-0">
                    {timelineItems.map((item) => {
                      if (item.type === "version") {
                        const v = item.version;
                        return (
                          <div
                            key={item.id}
                            className="relative z-10 mr-7 sm:mr-9 space-y-3"
                          >
                            {/* Marker dot */}
                            <div className="absolute -right-7 sm:-right-9 top-3.5 w-3 h-3 rounded-full bg-primary border-2 border-background ring-2 ring-primary/20" />

                            <Card className="border border-border shadow-xs bg-card">
                              <CardHeader className="p-3.5 pb-2 border-b border-border/40 bg-muted/20 flex flex-row items-center justify-between gap-2 flex-wrap space-y-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <CardTitle className="text-sm font-bold font-mono">
                                    V{v.version_number}
                                  </CardTitle>
                                  {item.isInitial && (
                                    <Badge
                                      variant="outline"
                                      className="text-[10px] border-blue-500/30 text-blue-700 bg-blue-500/10"
                                    >
                                      {t.timeline.initialVersionBadge}
                                    </Badge>
                                  )}
                                  {item.isLatestSubmitted && (
                                    <Badge
                                      variant="outline"
                                      className="text-[10px] border-emerald-500/30 text-emerald-700 bg-emerald-500/10"
                                    >
                                      {t.timeline.latestVersionBadge}
                                    </Badge>
                                  )}
                                </div>

                                <div className="text-[11px] text-muted-foreground flex items-center gap-1.5 font-mono">
                                  <span>
                                    {v.submitted_at
                                      ? new Date(v.submitted_at).toLocaleString(
                                          locale === "fa" ? "fa-IR" : "en-US"
                                        )
                                      : "—"}
                                  </span>
                                </div>
                              </CardHeader>

                              <CardContent className="p-4 space-y-3 text-xs">
                                {/* Commercial Summary Snapshot */}
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 p-2.5 bg-muted/25 rounded-md text-xs">
                                  <div>
                                    <span className="text-muted-foreground block text-[10px]">
                                      {t.diff.fields.unit_price}:
                                    </span>
                                    <span
                                      className="font-mono font-bold text-foreground"
                                      dir="ltr"
                                    >
                                      {v.unit_price} {v.currency}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block text-[10px]">
                                      {t.diff.fields.offered_quantity}:
                                    </span>
                                    <span
                                      className="font-mono font-bold text-foreground"
                                      dir="ltr"
                                    >
                                      {v.offered_quantity} {v.quantity_unit}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block text-[10px]">
                                      {t.diff.fields.incoterm}:
                                    </span>
                                    <span className="font-semibold text-foreground">
                                      {v.incoterm || "—"}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block text-[10px]">
                                      {t.diff.fields.payment_terms}:
                                    </span>
                                    <span className="text-foreground">
                                      {v.payment_terms || "—"}
                                    </span>
                                  </div>
                                </div>

                                {v.notes && (
                                  <div className="text-[11px] text-muted-foreground bg-muted/15 p-2 rounded">
                                    <span className="font-semibold text-foreground">
                                      {t.diff.fields.notes}:
                                    </span>{" "}
                                    {v.notes}
                                  </div>
                                )}

                                {/* Structured Diff View if revised version */}
                                {item.diffAgainstBase && (
                                  <div className="pt-2">
                                    <NegotiationDiffView
                                      diff={item.diffAgainstBase}
                                      locale={locale}
                                      defaultExpanded={true}
                                    />
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          </div>
                        );
                      }

                      if (item.type === "revision_request") {
                        const req = item.request;
                        const isTerminal = item.isTerminal;
                        const isOpen = item.isOpen;

                        const renderStatusBadge = () => {
                          switch (req.status) {
                            case "OPEN":
                              return (
                                <Badge className="bg-amber-600/10 text-amber-700 dark:text-amber-400 border-amber-500/20 text-xs gap-1">
                                  <Clock className="h-3 w-3" />
                                  {t.revisionRequest.statuses.OPEN}
                                </Badge>
                              );
                            case "RESOLVED":
                              return (
                                <Badge className="bg-emerald-600/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-xs gap-1">
                                  <CheckCircle2 className="h-3 w-3" />
                                  {t.revisionRequest.statuses.RESOLVED}
                                </Badge>
                              );
                            case "DECLINED":
                              return (
                                <Badge
                                  variant="outline"
                                  className="border-rose-500/30 text-rose-700 text-xs gap-1"
                                >
                                  <XCircle className="h-3 w-3" />
                                  {t.revisionRequest.statuses.DECLINED}
                                </Badge>
                              );
                            case "CANCELLED":
                              return (
                                <Badge
                                  variant="outline"
                                  className="text-muted-foreground text-xs gap-1"
                                >
                                  <X className="h-3 w-3" />
                                  {t.revisionRequest.statuses.CANCELLED}
                                </Badge>
                              );
                            default:
                              return null;
                          }
                        };

                        return (
                          <div
                            key={item.id}
                            className="relative z-10 mr-7 sm:mr-9 space-y-2"
                          >
                            {/* Marker dot */}
                            <div
                              className={`absolute -right-7 sm:-right-9 top-3.5 w-3 h-3 rounded-full border-2 border-background ring-2 ${
                                isOpen
                                  ? "bg-amber-500 ring-amber-500/20"
                                  : isTerminal
                                  ? "bg-rose-500 ring-rose-500/20"
                                  : "bg-emerald-500 ring-emerald-500/20"
                              }`}
                            />

                            <Card
                              className={`border shadow-xs ${
                                isOpen
                                  ? "border-amber-500/40 bg-amber-500/5 dark:bg-amber-500/10"
                                  : "border-border bg-card"
                              }`}
                            >
                              <CardHeader className="p-3.5 pb-2 border-b border-border/40 flex flex-row items-center justify-between gap-2 flex-wrap space-y-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <MessageSquare className="h-4 w-4 text-primary shrink-0" />
                                  <CardTitle className="text-xs sm:text-sm font-bold text-foreground">
                                    {t.timeline.revisionRequestTitle}
                                  </CardTitle>
                                  {renderStatusBadge()}
                                </div>

                                <span className="text-[11px] text-muted-foreground font-mono">
                                  {new Date(req.requested_at).toLocaleString(
                                    locale === "fa" ? "fa-IR" : "en-US"
                                  )}
                                </span>
                              </CardHeader>

                              <CardContent className="p-3.5 sm:p-4 space-y-3 text-xs">
                                {/* Requester & Base Version */}
                                <div className="flex items-center justify-between gap-2 text-xs flex-wrap">
                                  <div>
                                    <span className="text-muted-foreground">
                                      {t.revisionRequest.requester}{" "}
                                    </span>
                                    <span className="font-semibold text-foreground">
                                      {req.requested_by_name ||
                                        (req.requested_by_role === "OPERATOR"
                                          ? t.revisionRequest.roles.operator
                                          : t.revisionRequest.roles.buyer)}
                                    </span>
                                  </div>

                                  <div>
                                    <span className="text-muted-foreground">
                                      {t.revisionRequest.baseVersion}{" "}
                                    </span>
                                    <span className="font-mono font-bold text-foreground">
                                      V{req.base_version_number}
                                    </span>
                                  </div>
                                </div>

                                {/* Requested Fields */}
                                <div className="space-y-1">
                                  <span className="text-[11px] text-muted-foreground block">
                                    {t.revisionRequest.requestedFields}
                                  </span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {(Array.isArray(req.requested_fields)
                                      ? (req.requested_fields as string[])
                                      : []
                                    ).map((f: string) => (
                                      <Badge
                                        key={f}
                                        variant="secondary"
                                        className="text-[11px] font-medium"
                                      >
                                        <Tag className="h-2.5 w-2.5 mr-1 text-muted-foreground" />
                                        {Object.hasOwn(t.diff.fields, f)
                                          ? (t.diff.fields as Record<string, string>)[f]
                                          : f}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>

                                {/* Message */}
                                {req.message ? (
                                  <div className="p-2.5 rounded bg-muted/30 border border-border/40 text-xs italic text-foreground">
                                    &ldquo;{req.message}&rdquo;
                                  </div>
                                ) : (
                                  <div className="text-[11px] text-muted-foreground">
                                    {t.revisionRequest.noMessage}
                                  </div>
                                )}

                                {/* Resolution link */}
                                {req.status === "RESOLVED" &&
                                  req.resolved_version_number && (
                                    <div className="p-2 bg-emerald-500/10 border border-emerald-500/20 rounded text-[11px] text-emerald-800 dark:text-emerald-300 flex items-center justify-between gap-2 flex-wrap">
                                      <div className="flex items-center gap-1.5">
                                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                                        <span>
                                          {t.revisionRequest.resolvedBy}{" "}
                                          <strong className="font-mono font-bold">
                                            V{req.resolved_version_number}
                                          </strong>
                                        </span>
                                      </div>
                                      {req.resolved_at && (
                                        <span className="font-mono text-[10px]">
                                          {new Date(req.resolved_at).toLocaleString(
                                            locale === "fa" ? "fa-IR" : "en-US"
                                          )}
                                        </span>
                                      )}
                                    </div>
                                  )}

                                {/* Open Request Action Buttons */}
                                {isOpen && (
                                  <div className="pt-2 border-t border-border/40 flex items-center justify-end gap-2 flex-wrap">
                                    {canOfferPartyAct && (
                                      <>
                                        <Button
                                          variant="outline"
                                          onClick={() => handleDeclineRequest(req.id)}
                                          disabled={actionInProgress !== null}
                                          className="h-7 min-h-7 text-xs text-rose-700 hover:text-rose-800 border-rose-500/30 hover:bg-rose-50"
                                        >
                                          {actionInProgress === `decline:${req.id}` ? (
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                          ) : (
                                            t.revisionRequest.actions.decline
                                          )}
                                        </Button>

                                        <Button
                                          variant="default"
                                          onClick={() => handleCreateDraft(req.id)}
                                          disabled={actionInProgress !== null}
                                          className="h-7 min-h-7 text-xs gap-1"
                                        >
                                          {actionInProgress === `draft:${req.id}` ? (
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                          ) : (
                                            <>
                                              <FileEdit className="h-3 w-3" />
                                              {t.revisionRequest.actions.createDraft}
                                            </>
                                          )}
                                        </Button>
                                      </>
                                    )}

                                    {canBuyerAct && (
                                      <Button
                                        variant="outline"
                                        onClick={() => handleCancelRequest(req.id)}
                                        disabled={actionInProgress !== null}
                                        className="h-7 min-h-7 text-xs"
                                      >
                                        {actionInProgress === `cancel:${req.id}` ? (
                                          <Loader2 className="h-3 w-3 animate-spin" />
                                        ) : (
                                          t.revisionRequest.actions.cancel
                                        )}
                                      </Button>
                                    )}
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          </div>
                        );
                      }

                      if (item.type === "draft") {
                        const dv = item.draftVersion;
                        return (
                          <div
                            key={item.id}
                            className="relative z-10 mr-7 sm:mr-9 space-y-3"
                          >
                            <div className="absolute -right-7 sm:-right-9 top-3.5 w-3 h-3 rounded-full bg-blue-500 border-2 border-background ring-2 ring-blue-500/20" />

                            <Card className="border border-blue-500/40 bg-blue-500/5 shadow-xs">
                              <CardHeader className="p-3.5 pb-2 border-b border-blue-500/20 flex flex-row items-center justify-between gap-2 flex-wrap space-y-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <CardTitle className="text-sm font-bold font-mono text-blue-900 dark:text-blue-300">
                                    V{dv.version_number} ({t.timeline.draftBadge})
                                  </CardTitle>
                                  <Badge className="bg-blue-600/10 text-blue-700 dark:text-blue-400 border-blue-500/20 text-[10px]">
                                    {t.timeline.draftTitle.replace(
                                      "{version}",
                                      String(dv.version_number)
                                    )}
                                  </Badge>
                                </div>
                              </CardHeader>

                              <CardContent className="p-4 space-y-3 text-xs">
                                <div className="p-2.5 bg-blue-500/10 rounded-md text-xs text-blue-900 dark:text-blue-200 flex items-center justify-between gap-2 flex-wrap">
                                  <span>
                                    {t.draftNote}
                                  </span>

                                  {canOfferPartyAct && openRevisionRequest && (
                                    <Button
                                      variant="default"
                                      onClick={() =>
                                        handleSubmitDraft(
                                          openRevisionRequest.id,
                                          dv.id
                                        )
                                      }
                                      disabled={actionInProgress !== null}
                                      className="h-7 min-h-7 text-xs gap-1"
                                    >
                                      {actionInProgress === `submit:${dv.id}` ? (
                                        <Loader2 className="h-3 w-3 animate-spin" />
                                      ) : (
                                        <>
                                          <Send className="h-3 w-3" />
                                          {t.revisionRequest.actions.submitRevised}
                                        </>
                                      )}
                                    </Button>
                                  )}
                                </div>

                                {item.diffAgainstBase && (
                                  <NegotiationDiffView
                                    diff={item.diffAgainstBase}
                                    locale={locale}
                                  />
                                )}
                              </CardContent>
                            </Card>
                          </div>
                        );
                      }

                      return null;
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-3.5 sm:p-4 border-t border-border flex items-center justify-between gap-2 bg-muted/20">
          <div className="text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5 inline ml-1 text-muted-foreground" />
            {t.immutableNote}
          </div>
          <Button variant="outline" onClick={onClose} className="text-xs min-h-8">
            {t.close}
          </Button>
        </div>
      </div>
    </div>
  );
}

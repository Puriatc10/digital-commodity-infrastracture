"use client";

import React, { useState } from "react";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  CreditCard,
  History,
  Layers,
  Loader2,
  PlayCircle,
  ShieldCheck,
  SkipForward,
  UserCheck,
} from "lucide-react";
import type {
  ExecutionDetail,
  ExecutionMilestone,
  TimelineEvent,
  ExecutionPaymentStatusEnum,
  ExecutionMilestoneStatusEnum,
} from "./types";

export interface ExecutionTabProps {
  locale?: EnabledLocale;
  dealId: string;
  execution: ExecutionDetail | null;
  timeline: TimelineEvent[];
  isLoadingTimeline: boolean;
  isOperatorOrAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
  isViewer: boolean;
  onRefreshExecution: () => Promise<void>;
  onRefreshTimeline: () => Promise<void>;
  onInitializeExecution: () => Promise<void>;
  isInitializing: boolean;
}

export function ExecutionTab({
  locale = "fa",
  execution,
  timeline,
  isLoadingTimeline,
  isOperatorOrAdmin,
  isBuyer,
  isSeller,
  isViewer,
  onRefreshExecution,
  onRefreshTimeline,
  onInitializeExecution,
  isInitializing,
}: ExecutionTabProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace.executionMonitor;

  // Milestone Action Dialog / Form State
  const [activeMilestoneId, setActiveMilestoneId] = useState<string | null>(null);
  const [milestoneActionType, setMilestoneActionType] = useState<"start" | "complete" | "block" | "skip" | null>(null);
  const [actionNotes, setActionNotes] = useState<string>("");
  const [actionReason, setActionReason] = useState<string>("");
  const [actionActualAt, setActionActualAt] = useState<string>("");
  const [isSubmittingMilestone, setIsSubmittingMilestone] = useState<boolean>(false);
  const [milestoneError, setMilestoneError] = useState<string | null>(null);
  const [blockingIssueError, setBlockingIssueError] = useState<string | null>(null);

  // Payment Action Dialog State
  const [paymentActionType, setPaymentActionType] = useState<"report" | "confirm" | null>(null);
  const [paymentReference, setPaymentReference] = useState<string>("");
  const [paymentNotes, setPaymentNotes] = useState<string>("");
  const [isSubmittingPayment, setIsSubmittingPayment] = useState<boolean>(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);

  // Uninitialized Execution View
  if (!execution) {
    return (
      <Card className="p-12 text-center shadow-none border-dashed" dir={isRtl ? "rtl" : "ltr"}>
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <PlayCircle className="size-6" />
        </div>
        <h2 className="mt-4 text-base font-semibold">{t.uninitialized.title}</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto leading-relaxed">
          {t.uninitialized.description}
        </p>

        <div className="mt-6 flex flex-col items-center gap-2">
          {!isViewer && (isBuyer || isSeller || isOperatorOrAdmin) ? (
            <Button
              type="button"
              onClick={onInitializeExecution}
              disabled={isInitializing}
              className="gap-2 text-xs"
            >
              {isInitializing && <Loader2 className="size-4 animate-spin" />}
              <span>{isInitializing ? t.uninitialized.initializing : t.uninitialized.initButton}</span>
            </Button>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              {t.uninitialized.viewerNotice}
            </Badge>
          )}
        </div>
      </Card>
    );
  }

  const isOpen = execution.status === "OPEN";
  const boundWorkflowName =
    locale === "fa"
      ? execution.workflow_template_name_fa || execution.workflow_template_name_en || execution.workflow_template_code
      : execution.workflow_template_name_en || execution.workflow_template_code;

  // Handle Milestone Actions
  const handleOpenMilestoneAction = (milestone: ExecutionMilestone, type: "start" | "complete" | "block" | "skip") => {
    setActiveMilestoneId(milestone.id);
    setMilestoneActionType(type);
    setActionNotes("");
    setActionReason("");
    setActionActualAt("");
    setMilestoneError(null);
    setBlockingIssueError(null);
  };

  const handleCloseMilestoneAction = () => {
    setActiveMilestoneId(null);
    setMilestoneActionType(null);
    setActionNotes("");
    setActionReason("");
    setActionActualAt("");
    setMilestoneError(null);
    setBlockingIssueError(null);
  };

  const handleSubmitMilestoneAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!execution || !activeMilestoneId || !milestoneActionType) return;

    const currentMilestone = execution.milestones?.find((m) => m.id === activeMilestoneId);
    if (!currentMilestone) return;

    setIsSubmittingMilestone(true);
    setMilestoneError(null);
    setBlockingIssueError(null);

    try {
      if (milestoneActionType === "start") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/milestones/{milestone_id}/start/",
          {
            params: { path: { execution_id: execution.id, milestone_id: currentMilestone.id } },
            body: {
              expected_version: currentMilestone.version ?? 0,
              notes: actionNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseMilestoneAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setMilestoneError(t.conflictError);
          await onRefreshExecution();
        } else {
          setMilestoneError(t.genericError);
        }
      } else if (milestoneActionType === "complete") {
        const { data, response } = await apiClient.POST(
          "/api/execution/{execution_id}/milestones/{milestone_id}/complete/",
          {
            params: { path: { execution_id: execution.id, milestone_id: currentMilestone.id } },
            body: {
              expected_version: currentMilestone.version ?? 0,
              actual_at: actionActualAt || null,
              notes: actionNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseMilestoneAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setMilestoneError(t.conflictError);
          await onRefreshExecution();
        } else if (response.status === 400 && data && typeof data === "object" && "code" in data && data.code === "BLOCKING_ISSUE_OPEN") {
          setBlockingIssueError(t.milestones.blockingIssueOpenError);
        } else {
          setMilestoneError(t.genericError);
        }
      } else if (milestoneActionType === "block") {
        if (!actionReason.trim()) {
          setMilestoneError(t.milestones.dialogs.reasonLabel);
          setIsSubmittingMilestone(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/milestones/{milestone_id}/block/",
          {
            params: { path: { execution_id: execution.id, milestone_id: currentMilestone.id } },
            body: {
              expected_version: currentMilestone.version ?? 0,
              reason: actionReason.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseMilestoneAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setMilestoneError(t.conflictError);
          await onRefreshExecution();
        } else {
          setMilestoneError(t.genericError);
        }
      } else if (milestoneActionType === "skip") {
        if (!actionReason.trim()) {
          setMilestoneError(t.milestones.dialogs.reasonLabel);
          setIsSubmittingMilestone(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/milestones/{milestone_id}/skip/",
          {
            params: { path: { execution_id: execution.id, milestone_id: currentMilestone.id } },
            body: {
              expected_version: currentMilestone.version ?? 0,
              reason: actionReason.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseMilestoneAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setMilestoneError(t.conflictError);
          await onRefreshExecution();
        } else {
          setMilestoneError(t.genericError);
        }
      }
    } catch {
      setMilestoneError(t.genericError);
    } finally {
      setIsSubmittingMilestone(false);
    }
  };

  // Handle Payment Actions
  const handleOpenPaymentAction = (type: "report" | "confirm") => {
    setPaymentActionType(type);
    setPaymentReference("");
    setPaymentNotes("");
    setPaymentError(null);
  };

  const handleClosePaymentAction = () => {
    setPaymentActionType(null);
    setPaymentReference("");
    setPaymentNotes("");
    setPaymentError(null);
  };

  const handleSubmitPaymentAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!execution || !execution.payment || !paymentActionType) return;

    setIsSubmittingPayment(true);
    setPaymentError(null);

    try {
      if (paymentActionType === "report") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/payment/report/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: execution.payment.version ?? 0,
              reference: paymentReference.trim(),
              notes: paymentNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleClosePaymentAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setPaymentError(t.conflictError);
          await onRefreshExecution();
        } else {
          setPaymentError(t.genericError);
        }
      } else if (paymentActionType === "confirm") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/payment/confirm/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: execution.payment.version ?? 0,
              reference: paymentReference.trim(),
              notes: paymentNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleClosePaymentAction();
          await onRefreshExecution();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setPaymentError(t.conflictError);
          await onRefreshExecution();
        } else {
          setPaymentError(t.genericError);
        }
      }
    } catch {
      setPaymentError(t.genericError);
    } finally {
      setIsSubmittingPayment(false);
    }
  };

  // Helper for Milestone Status Badges
  const renderMilestoneStatusBadge = (status?: ExecutionMilestoneStatusEnum) => {
    switch (status) {
      case "COMPLETED":
        return (
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-700 bg-emerald-500/10 text-xs">
            <CheckCircle2 className="size-3 me-1" />
            <span>{t.milestones.statuses.COMPLETED}</span>
          </Badge>
        );
      case "IN_PROGRESS":
        return (
          <Badge variant="outline" className="border-blue-500/40 text-blue-700 bg-blue-500/10 text-xs">
            <PlayCircle className="size-3 me-1" />
            <span>{t.milestones.statuses.IN_PROGRESS}</span>
          </Badge>
        );
      case "BLOCKED":
        return (
          <Badge variant="outline" className="border-destructive/40 text-destructive bg-destructive/10 text-xs">
            <AlertTriangle className="size-3 me-1" />
            <span>{t.milestones.statuses.BLOCKED}</span>
          </Badge>
        );
      case "SKIPPED":
        return (
          <Badge variant="outline" className="border-amber-500/40 text-amber-700 bg-amber-500/10 text-xs">
            <SkipForward className="size-3 me-1" />
            <span>{t.milestones.statuses.SKIPPED}</span>
          </Badge>
        );
      case "PENDING":
      default:
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-xs">
            <Clock className="size-3 me-1" />
            <span>{t.milestones.statuses.PENDING}</span>
          </Badge>
        );
    }
  };

  // Helper for Payment Status Badges
  const renderPaymentStatusBadge = (status?: ExecutionPaymentStatusEnum) => {
    switch (status) {
      case "CONFIRMED":
        return (
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-700 bg-emerald-500/10 text-xs">
            <ShieldCheck className="size-3 me-1" />
            <span>{t.payment.statuses.CONFIRMED}</span>
          </Badge>
        );
      case "REPORTED":
        return (
          <Badge variant="outline" className="border-blue-500/40 text-blue-700 bg-blue-500/10 text-xs">
            <CreditCard className="size-3 me-1" />
            <span>{t.payment.statuses.REPORTED}</span>
          </Badge>
        );
      case "EXPECTED":
      default:
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-xs">
            <Clock className="size-3 me-1" />
            <span>{t.payment.statuses.EXPECTED}</span>
          </Badge>
        );
    }
  };

  const sortedMilestones = [...(execution.milestones || [])].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* 1. Execution Aggregate Overview Card */}
      <Card className="shadow-none">
        <CardHeader className="pb-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <Layers className="size-5 text-primary" />
                <span>{t.workflow.title}</span>
              </CardTitle>
              <CardDescription className="text-xs mt-1">
                {t.workflow.versionImmutableNotice}
              </CardDescription>
            </div>
            <div>
              <Badge
                variant="outline"
                className={`text-xs px-2.5 py-1 ${
                  isOpen
                    ? "border-emerald-500/40 text-emerald-700 bg-emerald-500/10"
                    : "border-slate-500/40 text-slate-700 bg-slate-500/10"
                }`}
              >
                {isOpen ? t.status.OPEN : t.status.CLOSED}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
            <div>
              <dt className="text-muted-foreground font-medium">{t.workflow.templateLabel}</dt>
              <dd className="mt-1 font-semibold">{boundWorkflowName}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{t.workflow.boundVersionTitle}</dt>
              <dd className="mt-1 font-mono" dir="ltr">
                {`v${execution.workflow_version_number}`}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{t.workflow.startedAt}</dt>
              <dd className="mt-1 font-mono" dir="ltr">
                {execution.started_at ? execution.started_at.slice(0, 19).replace("T", " ") : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{t.workflow.closedAt}</dt>
              <dd className="mt-1 font-mono" dir="ltr">
                {execution.closed_at ? execution.closed_at.slice(0, 19).replace("T", " ") : "—"}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* 2. Milestones Graph & Action Panel */}
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle className="text-base">{t.milestones.title}</CardTitle>
          <CardDescription className="text-xs">{t.milestones.subtitle}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {blockingIssueError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-xs text-destructive flex items-start gap-2">
              <AlertCircle className="size-4 shrink-0 mt-0.5" />
              <span>{blockingIssueError}</span>
            </div>
          )}

          {milestoneError && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-800 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{milestoneError}</span>
            </div>
          )}

          <div className="divide-y divide-border border rounded-lg overflow-hidden">
            {sortedMilestones.map((milestone) => {
              const localizedMilestoneName =
                locale === "fa"
                  ? milestone.name_fa || milestone.name_en || milestone.code
                  : milestone.name_en || milestone.code;

              const isCompleted = milestone.status === "COMPLETED";
              const isTerminal = milestone.terminal;
              const canMutate = isOpen && !isViewer;

              // Side-specific eligibility checks for action visibility (UX guidance only; backend remains authoritative)
              const SELLER_EXCLUSIVE = ["LOADING_SCHEDULED", "LOADED", "IN_TRANSIT"];
              const BUYER_EXCLUSIVE = ["ACCEPTED"];

              const isSellerExclusive = SELLER_EXCLUSIVE.includes(milestone.code);
              const isBuyerExclusive = BUYER_EXCLUSIVE.includes(milestone.code);

              let actorPermitted = isOperatorOrAdmin;
              if (isBuyer && !isSellerExclusive) actorPermitted = true;
              if (isSeller && !isBuyerExclusive) actorPermitted = true;

              return (
                <div key={milestone.id} className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-card hover:bg-muted/10 transition-colors">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground w-5 text-center" dir="ltr">
                        {milestone.sort_order}
                      </span>
                      <span className="font-semibold text-sm">{localizedMilestoneName}</span>
                      {renderMilestoneStatusBadge(milestone.status)}
                      {milestone.required ? (
                        <Badge variant="outline" className="text-[10px] py-0 border-border text-muted-foreground">
                          {t.milestones.badges.required}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[10px] py-0 border-border text-muted-foreground">
                          {t.milestones.badges.optional}
                        </Badge>
                      )}
                      {isTerminal && (
                        <Badge variant="outline" className="text-[10px] py-0 border-primary/40 text-primary bg-primary/5">
                          {t.milestones.badges.terminal}
                        </Badge>
                      )}
                    </div>

                    <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 pt-1">
                      {milestone.actual_at && (
                        <span>
                          {t.milestones.timing}:{" "}
                          <span className="font-mono text-foreground" dir="ltr">
                            {milestone.actual_at.slice(0, 19).replace("T", " ")}
                          </span>
                        </span>
                      )}
                      {milestone.completed_by_email && (
                        <span>
                          {t.milestones.actor}: <span className="font-mono text-foreground">{milestone.completed_by_email}</span>
                        </span>
                      )}
                      {milestone.notes && (
                        <span className="line-clamp-1 italic">
                          &ldquo;{milestone.notes}&rdquo;
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions for this milestone */}
                  {canMutate && actorPermitted && !isCompleted && (
                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                      {milestone.status === "PENDING" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => handleOpenMilestoneAction(milestone, "start")}
                          className="text-xs h-7 px-2.5"
                        >
                          {t.milestones.actionsList.start}
                        </Button>
                      )}

                      <Button
                        type="button"
                        variant={isTerminal ? "default" : "outline"}
                        onClick={() => handleOpenMilestoneAction(milestone, "complete")}
                        className="text-xs h-7 px-2.5 gap-1"
                      >
                        <CheckCircle2 className="size-3.5" />
                        <span>{isTerminal ? t.milestones.actionsList.close : t.milestones.actionsList.complete}</span>
                      </Button>

                      {milestone.status !== "BLOCKED" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => handleOpenMilestoneAction(milestone, "block")}
                          className="text-xs h-7 px-2 text-destructive border-destructive/30 hover:bg-destructive/10"
                        >
                          {t.milestones.actionsList.block}
                        </Button>
                      )}

                      {!milestone.required && milestone.status !== "SKIPPED" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => handleOpenMilestoneAction(milestone, "skip")}
                          className="text-xs h-7 px-2 text-amber-700 border-amber-500/30 hover:bg-amber-500/10"
                        >
                          {t.milestones.actionsList.skip}
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Milestone Action Inline Modal / Dialog */}
          {activeMilestoneId && milestoneActionType && (
            <Card className="border-primary/40 bg-muted/20 mt-4 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">
                  {milestoneActionType === "start" && t.milestones.dialogs.startTitle}
                  {milestoneActionType === "complete" && t.milestones.dialogs.completeTitle}
                  {milestoneActionType === "block" && t.milestones.dialogs.blockTitle}
                  {milestoneActionType === "skip" && t.milestones.dialogs.skipTitle}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmitMilestoneAction} className="space-y-4">
                  {(milestoneActionType === "block" || milestoneActionType === "skip") && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.milestones.dialogs.reasonLabel} *</Label>
                      <Textarea
                        value={actionReason}
                        onChange={(e) => setActionReason(e.target.value)}
                        placeholder={t.milestones.dialogs.reasonPlaceholder}
                        required
                        className="text-xs resize-none"
                        rows={2}
                      />
                    </div>
                  )}

                  {milestoneActionType === "complete" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.milestones.dialogs.actualAtLabel}</Label>
                      <Input
                        type="datetime-local"
                        value={actionActualAt}
                        onChange={(e) => setActionActualAt(e.target.value)}
                        className="text-xs"
                      />
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">{t.milestones.dialogs.notesLabel}</Label>
                    <Textarea
                      value={actionNotes}
                      onChange={(e) => setActionNotes(e.target.value)}
                      placeholder={t.milestones.dialogs.notesPlaceholder}
                      className="text-xs resize-none"
                      rows={2}
                    />
                  </div>

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseMilestoneAction}
                      disabled={isSubmittingMilestone}
                      className="text-xs"
                    >
                      {t.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmittingMilestone}
                      className="text-xs gap-1.5"
                    >
                      {isSubmittingMilestone && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmittingMilestone ? t.milestones.dialogs.submitting : t.milestones.dialogs.submit}</span>
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>

      {/* 3. Embedded Payment Monitoring Panel */}
      <Card className="shadow-none">
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <CreditCard className="size-4 text-primary" />
                <span>{t.payment.title}</span>
              </CardTitle>
              <CardDescription className="text-xs mt-1">
                {t.payment.subtitle}
              </CardDescription>
            </div>
            {execution.payment && (
              <div>{renderPaymentStatusBadge(execution.payment.status)}</div>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs text-muted-foreground">
            {t.payment.disclaimer}
          </div>

          {paymentError && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-800 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{paymentError}</span>
            </div>
          )}

          {execution.payment ? (
            <div className="space-y-4">
              <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 text-xs">
                <div>
                  <dt className="text-muted-foreground font-medium">{t.payment.expectedAmount}</dt>
                  <dd className="mt-1 font-semibold text-sm" dir="ltr">
                    {execution.payment.expected_amount
                      ? `${execution.payment.expected_amount} ${execution.payment.currency || ""}`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.payment.expectedDate}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {execution.payment.expected_at ? execution.payment.expected_at.slice(0, 10) : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.payment.reference}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {execution.payment.reference || "—"}
                  </dd>
                </div>

                {execution.payment.reported_at && (
                  <div>
                    <dt className="text-muted-foreground font-medium">{t.payment.reportedAt}</dt>
                    <dd className="mt-1 font-mono" dir="ltr">
                      {execution.payment.reported_at.slice(0, 19).replace("T", " ")}
                    </dd>
                  </div>
                )}
                {execution.payment.reported_by_email && (
                  <div>
                    <dt className="text-muted-foreground font-medium">{t.payment.reportedBy}</dt>
                    <dd className="mt-1 font-mono">{execution.payment.reported_by_email}</dd>
                  </div>
                )}

                {execution.payment.confirmed_at && (
                  <div>
                    <dt className="text-muted-foreground font-medium">{t.payment.confirmedAt}</dt>
                    <dd className="mt-1 font-mono" dir="ltr">
                      {execution.payment.confirmed_at.slice(0, 19).replace("T", " ")}
                    </dd>
                  </div>
                )}
                {execution.payment.confirmed_by_email && (
                  <div>
                    <dt className="text-muted-foreground font-medium">{t.payment.confirmedBy}</dt>
                    <dd className="mt-1 font-mono">{execution.payment.confirmed_by_email}</dd>
                  </div>
                )}
              </dl>

              {execution.payment.notes && (
                <div className="pt-2 border-t text-xs">
                  <span className="text-muted-foreground font-medium">{t.payment.notes} </span>
                  <span className="leading-relaxed">{execution.payment.notes}</span>
                </div>
              )}

              {/* Payment Actions */}
              {isOpen && !isViewer && (
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  {(execution.payment.status === "EXPECTED" || execution.payment.status === "REPORTED") && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => handleOpenPaymentAction("report")}
                      className="text-xs"
                    >
                      {t.payment.actions.report}
                    </Button>
                  )}

                  {isOperatorOrAdmin && execution.payment.status !== "CONFIRMED" && (
                    <Button
                      type="button"
                      onClick={() => handleOpenPaymentAction("confirm")}
                      className="text-xs gap-1.5"
                    >
                      <UserCheck className="size-3.5" />
                      <span>{t.payment.actions.confirm}</span>
                    </Button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">اطلاعات رصد پرداخت در دسترس نیست.</p>
          )}

          {/* Payment Action Modal */}
          {paymentActionType && (
            <Card className="border-primary/40 bg-muted/20 mt-4 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">
                  {paymentActionType === "report" ? t.payment.dialogs.reportTitle : t.payment.dialogs.confirmTitle}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmitPaymentAction} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">{t.payment.dialogs.referenceLabel}</Label>
                    <Input
                      value={paymentReference}
                      onChange={(e) => setPaymentReference(e.target.value)}
                      placeholder={t.payment.dialogs.referencePlaceholder}
                      className="text-xs"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">{t.payment.dialogs.notesLabel}</Label>
                    <Textarea
                      value={paymentNotes}
                      onChange={(e) => setPaymentNotes(e.target.value)}
                      placeholder={t.payment.dialogs.notesPlaceholder}
                      className="text-xs resize-none"
                      rows={2}
                    />
                  </div>

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleClosePaymentAction}
                      disabled={isSubmittingPayment}
                      className="text-xs"
                    >
                      {t.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmittingPayment}
                      className="text-xs gap-1.5"
                    >
                      {isSubmittingPayment && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmittingPayment ? (paymentActionType === "report" ? t.payment.actions.reporting : t.payment.actions.confirming) : t.milestones.dialogs.submit}</span>
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>

      {/* 4. Execution Timeline Panel */}
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <History className="size-4 text-primary" />
            <span>{t.timeline.title}</span>
          </CardTitle>
          <CardDescription className="text-xs">{t.timeline.subtitle}</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoadingTimeline ? (
            <div className="flex items-center justify-center p-8 text-muted-foreground gap-2">
              <Loader2 className="size-4 animate-spin text-primary" />
              <span className="text-xs">{messages.dealWorkspace.loading}</span>
            </div>
          ) : timeline.length === 0 ? (
            <p className="text-xs text-muted-foreground p-4 text-center">{t.timeline.empty}</p>
          ) : (
            <div className="relative border-s border-border ms-4 ps-6 space-y-6 my-2">
              {timeline.map((event) => {
                const localizedTitle =
                  event.milestone_name_fa ||
                  event.milestone_name_en ||
                  event.event_type.replace(/_/g, " ");

                return (
                  <div key={event.event_id} className="relative">
                    <span className="absolute -start-[31px] top-1 flex size-5 items-center justify-center rounded-full bg-background border border-primary text-primary">
                      <Clock className="size-3" />
                    </span>
                    <div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1">
                      <h4 className="text-xs font-semibold text-foreground">{localizedTitle}</h4>
                      <span className="text-[11px] font-mono text-muted-foreground" dir="ltr">
                        {event.event_at ? event.event_at.slice(0, 19).replace("T", " ") : "—"}
                      </span>
                    </div>
                    {event.actor_email && (
                      <p className="mt-0.5 text-[11px] text-muted-foreground font-mono">
                        {t.timeline.actorLabel} {event.actor_email}
                      </p>
                    )}
                    {event.notes && (
                      <p className="mt-1 text-xs text-muted-foreground leading-relaxed italic">
                        &ldquo;{event.notes}&rdquo;
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

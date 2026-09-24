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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertCircle,
  AlertTriangle,
  Calendar,
  CheckCircle2,
  FileCheck2,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import type {
  ExecutionDetail,
  ExecutionInspection,
  ExecutionInspectionStatusEnum,
  ResultEnum,
} from "./types";

export interface QualityTabProps {
  locale?: EnabledLocale;
  dealId: string;
  execution: ExecutionDetail | null;
  inspection: ExecutionInspection | null;
  isOperatorOrAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
  isViewer: boolean;
  onRefreshInspection: () => Promise<void>;
  onRefreshTimeline: () => Promise<void>;
}

export function QualityTab({
  locale = "fa",
  execution,
  inspection,
  isOperatorOrAdmin,
  isBuyer,
  isSeller,
  isViewer,
  onRefreshInspection,
  onRefreshTimeline,
}: QualityTabProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace.executionMonitor.quality;

  const [activeAction, setActiveAction] = useState<"schedule" | "complete" | "cancel" | "markNotRequired" | null>(null);

  // Form states
  const [scheduledAtInput, setScheduledAtInput] = useState<string>("");
  const [inspectionAtInput, setInspectionAtInput] = useState<string>("");
  const [agencyInput, setAgencyInput] = useState<string>("");
  const [resultInput, setResultInput] = useState<ResultEnum | "">("");
  const [notesInput, setNotesInput] = useState<string>("");

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!execution) {
    return (
      <Card className="p-12 text-center shadow-none border-dashed" dir={isRtl ? "rtl" : "ltr"}>
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
          <ShieldCheck className="size-6 text-muted-foreground" />
        </div>
        <h2 className="mt-4 text-base font-semibold">{t.title}</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
          {messages.dealWorkspace.executionMonitor.uninitialized.description}
        </p>
      </Card>
    );
  }

  const isOpen = execution.status === "OPEN";
  const canMutate = isOpen && !isViewer && (isOperatorOrAdmin || isBuyer || isSeller);

  const handleOpenAction = (action: typeof activeAction) => {
    setActiveAction(action);
    setErrorMsg(null);
    if (!inspection) return;

    if (action === "schedule") {
      setScheduledAtInput(inspection.scheduled_at?.slice(0, 16) || "");
      setAgencyInput(inspection.agency || "");
      setNotesInput(inspection.notes || "");
    } else if (action === "complete") {
      setInspectionAtInput(inspection.inspection_at?.slice(0, 16) || "");
      setResultInput((inspection.result as ResultEnum) || "PASS");
      setAgencyInput(inspection.agency || "");
      setNotesInput(inspection.notes || "");
    } else if (action === "cancel") {
      setNotesInput("");
    } else if (action === "markNotRequired") {
      setNotesInput("");
    }
  };

  const handleCloseAction = () => {
    setActiveAction(null);
    setErrorMsg(null);
  };

  const handleSubmitAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!execution || !inspection || !activeAction) return;

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      if (activeAction === "schedule") {
        if (!scheduledAtInput) {
          setErrorMsg("لطفاً زمان نوبت بازرسی را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/inspection/schedule/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: inspection.version ?? 0,
              scheduled_at: scheduledAtInput,
              agency: agencyInput.trim(),
              notes: notesInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshInspection();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshInspection();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "complete") {
        if (!inspectionAtInput || !resultInput) {
          setErrorMsg("لطفاً زمان واقعی بازرسی و نتیجه را مشخص کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/inspection/complete/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: inspection.version ?? 0,
              inspection_at: inspectionAtInput,
              result: resultInput as ResultEnum,
              agency: agencyInput.trim(),
              notes: notesInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshInspection();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshInspection();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "cancel") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/inspection/cancel/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: inspection.version ?? 0,
              notes: notesInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshInspection();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshInspection();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "markNotRequired") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/inspection/mark-not-required/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: inspection.version ?? 0,
              notes: notesInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshInspection();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshInspection();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      }
    } catch {
      setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderInspectionStatusBadge = (status?: ExecutionInspectionStatusEnum) => {
    switch (status) {
      case "COMPLETED":
        return (
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-700 bg-emerald-500/10 text-xs">
            <CheckCircle2 className="size-3 me-1" />
            <span>{t.statuses.COMPLETED}</span>
          </Badge>
        );
      case "SCHEDULED":
        return (
          <Badge variant="outline" className="border-blue-500/40 text-blue-700 bg-blue-500/10 text-xs">
            <Calendar className="size-3 me-1" />
            <span>{t.statuses.SCHEDULED}</span>
          </Badge>
        );
      case "PENDING":
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-xs">
            <Calendar className="size-3 me-1" />
            <span>{t.statuses.PENDING}</span>
          </Badge>
        );
      case "NOT_REQUIRED":
        return (
          <Badge variant="outline" className="border-border text-muted-foreground bg-muted text-xs">
            <span>{t.statuses.NOT_REQUIRED}</span>
          </Badge>
        );
      case "CANCELLED":
      default:
        return (
          <Badge variant="outline" className="border-destructive/40 text-destructive bg-destructive/10 text-xs">
            <XCircle className="size-3 me-1" />
            <span>{t.statuses.CANCELLED}</span>
          </Badge>
        );
    }
  };

  const renderResultBadge = (result?: ResultEnum) => {
    switch (result) {
      case "PASS":
        return (
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-700 bg-emerald-500/10 text-xs">
            <CheckCircle2 className="size-3 me-1" />
            <span>{t.results.PASS}</span>
          </Badge>
        );
      case "FAIL":
        return (
          <Badge variant="outline" className="border-destructive/40 text-destructive bg-destructive/10 text-xs font-semibold">
            <AlertTriangle className="size-3 me-1" />
            <span>{t.results.FAIL}</span>
          </Badge>
        );
      case "CONDITIONAL":
        return (
          <Badge variant="outline" className="border-amber-500/40 text-amber-700 bg-amber-500/10 text-xs">
            <AlertCircle className="size-3 me-1" />
            <span>{t.results.CONDITIONAL}</span>
          </Badge>
        );
      case "UNKNOWN":
      default:
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-xs">
            <span>{t.results.UNKNOWN}</span>
          </Badge>
        );
    }
  };

  const isCompletedAndFail =
    inspection?.status === "COMPLETED" && inspection?.result === "FAIL";

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      <Card className="shadow-none">
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <ShieldCheck className="size-4 text-primary" />
                <span>{t.title}</span>
              </CardTitle>
              <CardDescription className="text-xs mt-1">{t.subtitle}</CardDescription>
            </div>
            {inspection && (
              <div className="flex items-center gap-2">
                {renderInspectionStatusBadge(inspection.status)}
                {renderResultBadge(inspection.result)}
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {errorMsg && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-800 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* COMPLETED + FAIL Special Callout */}
          {isCompletedAndFail && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-xs text-destructive space-y-1">
              <div className="font-semibold flex items-center gap-2">
                <ShieldAlert className="size-4" />
                <span>{t.failedCompletedCalloutTitle}</span>
              </div>
              <p className="leading-relaxed text-muted-foreground">
                {t.failedCompletedCallout}
              </p>
            </div>
          )}

          {inspection ? (
            <div className="space-y-6">
              <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-xs">
                <div>
                  <dt className="text-muted-foreground font-medium">{t.required}</dt>
                  <dd className="mt-1 font-semibold">
                    {inspection.required ? t.requiredYes : t.requiredNo}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.agency}</dt>
                  <dd className="mt-1 font-semibold text-sm">
                    {inspection.agency || t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.status}</dt>
                  <dd className="mt-1">{renderInspectionStatusBadge(inspection.status)}</dd>
                </div>

                <div>
                  <dt className="text-muted-foreground font-medium">{t.result}</dt>
                  <dd className="mt-1">{renderResultBadge(inspection.result)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.scheduledAt}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {inspection.scheduled_at
                      ? inspection.scheduled_at.slice(0, 19).replace("T", " ")
                      : t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.inspectionAt}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {inspection.inspection_at
                      ? inspection.inspection_at.slice(0, 19).replace("T", " ")
                      : t.notRecorded}
                  </dd>
                </div>
              </dl>

              {inspection.notes && (
                <div className="pt-2 border-t text-xs">
                  <span className="text-muted-foreground font-medium">{t.notes} </span>
                  <span className="leading-relaxed">{inspection.notes}</span>
                </div>
              )}

              {/* Quality Actions */}
              {canMutate && (
                <div className="flex flex-wrap items-center gap-2 pt-4 border-t">
                  {inspection.status !== "COMPLETED" && (
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("schedule")}
                        className="text-xs"
                      >
                        {t.actions.schedule}
                      </Button>
                      <Button
                        type="button"
                        variant="default"
                        onClick={() => handleOpenAction("complete")}
                        className="text-xs gap-1"
                      >
                        <FileCheck2 className="size-3.5" />
                        <span>{t.actions.complete}</span>
                      </Button>
                      {inspection.status !== "CANCELLED" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => handleOpenAction("cancel")}
                          className="text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                        >
                          {t.actions.cancel}
                        </Button>
                      )}
                      {inspection.status !== "NOT_REQUIRED" && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => handleOpenAction("markNotRequired")}
                          className="text-xs text-muted-foreground border-border hover:bg-muted"
                        >
                          {t.actions.markNotRequired}
                        </Button>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t.notRecorded}</p>
          )}

          {/* Action Form / Dialog */}
          {activeAction && (
            <Card className="border-primary/40 bg-muted/20 mt-4 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">
                  {activeAction === "schedule" && t.dialogs.scheduleTitle}
                  {activeAction === "complete" && t.dialogs.completeTitle}
                  {activeAction === "cancel" && t.dialogs.cancelTitle}
                  {activeAction === "markNotRequired" && t.dialogs.markNotRequiredTitle}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmitAction} className="space-y-4">
                  {activeAction === "schedule" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.scheduledAt} *</Label>
                        <Input
                          type="datetime-local"
                          value={scheduledAtInput}
                          onChange={(e) => setScheduledAtInput(e.target.value)}
                          required
                          className="text-xs"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.agencyLabel}</Label>
                        <Input
                          value={agencyInput}
                          onChange={(e) => setAgencyInput(e.target.value)}
                          placeholder={t.dialogs.agencyPlaceholder}
                          className="text-xs"
                        />
                      </div>
                    </div>
                  )}

                  {activeAction === "complete" && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.inspectionAt} *</Label>
                        <Input
                          type="datetime-local"
                          value={inspectionAtInput}
                          onChange={(e) => setInspectionAtInput(e.target.value)}
                          required
                          className="text-xs"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.resultLabel} *</Label>
                        <Select
                          value={resultInput}
                          onValueChange={(val) => setResultInput(val as ResultEnum)}
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue placeholder="انتخاب نتیجه…" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="PASS">{t.results.PASS}</SelectItem>
                            <SelectItem value="FAIL">{t.results.FAIL}</SelectItem>
                            <SelectItem value="CONDITIONAL">{t.results.CONDITIONAL}</SelectItem>
                            <SelectItem value="UNKNOWN">{t.results.UNKNOWN}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.agencyLabel}</Label>
                        <Input
                          value={agencyInput}
                          onChange={(e) => setAgencyInput(e.target.value)}
                          placeholder={t.dialogs.agencyPlaceholder}
                          className="text-xs"
                        />
                      </div>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">{t.dialogs.notesLabel}</Label>
                    <Textarea
                      value={notesInput}
                      onChange={(e) => setNotesInput(e.target.value)}
                      placeholder={t.dialogs.notesPlaceholder}
                      className="text-xs resize-none"
                      rows={2}
                    />
                  </div>

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseAction}
                      disabled={isSubmitting}
                      className="text-xs"
                    >
                      {messages.dealWorkspace.executionMonitor.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmitting}
                      className="text-xs gap-1.5"
                    >
                      {isSubmitting && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmitting ? "در حال ثبت…" : "تأیید و ثبت"}</span>
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

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
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  PlayCircle,
  PlusCircle,
  ShieldAlert,
} from "lucide-react";
import { LoadingState, EmptyState } from "@/components/states";
import type {
  ExecutionDetail,
  ExecutionIssue,
  ExecutionIssueTypeEnum,
  ExecutionIssueStatusEnum,
  ExecutionIssueSeverityEnum,
} from "./types";

export interface IssuesTabProps {
  locale?: EnabledLocale;
  dealId: string;
  execution: ExecutionDetail | null;
  issues: ExecutionIssue[];
  isLoadingIssues: boolean;
  isOperatorOrAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
  isViewer: boolean;
  onRefreshIssues: () => Promise<void>;
  onRefreshTimeline: () => Promise<void>;
}

export function IssuesTab({
  locale = "fa",
  execution,
  issues,
  isLoadingIssues,
  isOperatorOrAdmin,
  isBuyer,
  isSeller,
  isViewer,
  onRefreshIssues,
  onRefreshTimeline,
}: IssuesTabProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace.executionMonitor.issues;

  // New Issue Dialog State
  const [isOpenNewDialog, setIsOpenNewDialog] = useState<boolean>(false);
  const [newType, setNewType] = useState<ExecutionIssueTypeEnum>("QUALITY");
  const [newTitle, setNewTitle] = useState<string>("");
  const [newDesc, setNewDesc] = useState<string>("");
  const [newSeverity, setNewSeverity] = useState<ExecutionIssueSeverityEnum | "">("MEDIUM");
  const [newBlocksExecution, setNewBlocksExecution] = useState<boolean>(false);
  const [isSubmittingNew, setIsSubmittingNew] = useState<boolean>(false);

  // Transition Action State (Start, Resolve, Cancel)
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null);
  const [issueActionType, setIssueActionType] = useState<"start" | "resolve" | "cancel" | null>(null);
  const [resolutionNotes, setResolutionNotes] = useState<string>("");
  const [cancelNotes, setCancelNotes] = useState<string>("");
  const [isSubmittingAction, setIsSubmittingAction] = useState<boolean>(false);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!execution) {
    return (
      <Card className="p-12 text-center shadow-none border-dashed" dir={isRtl ? "rtl" : "ltr"}>
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
          <AlertTriangle className="size-6 text-muted-foreground" />
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

  const handleCreateIssue = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    setIsSubmittingNew(true);
    setErrorMessage(null);

    try {
      const { response } = await apiClient.POST(
        "/api/execution/{execution_id}/issues/",
        {
          params: { path: { execution_id: execution.id } },
          body: {
            type: newType,
            title: newTitle.trim(),
            description: newDesc.trim(),
            severity: newSeverity ? (newSeverity as ExecutionIssueSeverityEnum) : null,
            blocks_execution: newBlocksExecution,
          },
        }
      );

      if (response.ok) {
        setIsOpenNewDialog(false);
        setNewTitle("");
        setNewDesc("");
        setNewBlocksExecution(false);
        await onRefreshIssues();
        await onRefreshTimeline();
      } else if (response.status === 409) {
        setErrorMessage(messages.dealWorkspace.executionMonitor.conflictError);
        await onRefreshIssues();
      } else {
        setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
      }
    } catch {
      setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
    } finally {
      setIsSubmittingNew(false);
    }
  };

  const handleOpenAction = (issue: ExecutionIssue, type: "start" | "resolve" | "cancel") => {
    setActiveIssueId(issue.id);
    setIssueActionType(type);
    setResolutionNotes("");
    setCancelNotes("");
    setErrorMessage(null);
  };

  const handleCloseAction = () => {
    setActiveIssueId(null);
    setIssueActionType(null);
    setResolutionNotes("");
    setCancelNotes("");
    setErrorMessage(null);
  };

  const handleSubmitAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeIssueId || !issueActionType) return;

    const currentIssue = issues.find((i) => i.id === activeIssueId);
    if (!currentIssue) return;

    setIsSubmittingAction(true);
    setErrorMessage(null);

    try {
      if (issueActionType === "start") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/issues/{issue_id}/start/",
          {
            params: { path: { execution_id: execution.id, issue_id: currentIssue.id } },
            body: { expected_version: currentIssue.version ?? 0 },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshIssues();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMessage(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshIssues();
        } else {
          setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (issueActionType === "resolve") {
        if (!resolutionNotes.trim()) {
          setErrorMessage("لطفاً شرح نحوه حل مغایرت را وارد نمایید.");
          setIsSubmittingAction(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/issues/{issue_id}/resolve/",
          {
            params: { path: { execution_id: execution.id, issue_id: currentIssue.id } },
            body: {
              expected_version: currentIssue.version ?? 0,
              resolution_notes: resolutionNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshIssues();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMessage(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshIssues();
        } else {
          setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (issueActionType === "cancel") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/issues/{issue_id}/cancel/",
          {
            params: { path: { execution_id: execution.id, issue_id: currentIssue.id } },
            body: {
              expected_version: currentIssue.version ?? 0,
              notes: cancelNotes.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshIssues();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMessage(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshIssues();
        } else {
          setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
        }
      }
    } catch {
      setErrorMessage(messages.dealWorkspace.executionMonitor.genericError);
    } finally {
      setIsSubmittingAction(false);
    }
  };

  const renderStatusBadge = (status: ExecutionIssueStatusEnum) => {
    switch (status) {
      case "RESOLVED":
        return (
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-700 bg-emerald-500/10 text-xs">
            <CheckCircle2 className="size-3 me-1" />
            <span>{t.statuses.RESOLVED}</span>
          </Badge>
        );
      case "IN_PROGRESS":
        return (
          <Badge variant="outline" className="border-blue-500/40 text-blue-700 bg-blue-500/10 text-xs">
            <PlayCircle className="size-3 me-1" />
            <span>{t.statuses.IN_PROGRESS}</span>
          </Badge>
        );
      case "OPEN":
        return (
          <Badge variant="outline" className="border-amber-500/40 text-amber-700 bg-amber-500/10 text-xs">
            <Clock className="size-3 me-1" />
            <span>{t.statuses.OPEN}</span>
          </Badge>
        );
      case "CANCELLED":
      default:
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-xs">
            <Ban className="size-3 me-1" />
            <span>{t.statuses.CANCELLED}</span>
          </Badge>
        );
    }
  };

  const renderSeverityBadge = (severity?: ExecutionIssueSeverityEnum | null) => {
    if (!severity) return null;
    switch (severity) {
      case "CRITICAL":
        return (
          <Badge variant="outline" className="border-destructive/40 text-destructive bg-destructive/10 text-[11px] py-0 font-bold">
            {t.severities.CRITICAL}
          </Badge>
        );
      case "HIGH":
        return (
          <Badge variant="outline" className="border-red-500/40 text-red-700 bg-red-500/10 text-[11px] py-0">
            {t.severities.HIGH}
          </Badge>
        );
      case "MEDIUM":
        return (
          <Badge variant="outline" className="border-amber-500/40 text-amber-700 bg-amber-500/10 text-[11px] py-0">
            {t.severities.MEDIUM}
          </Badge>
        );
      case "LOW":
      default:
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-[11px] py-0">
            {t.severities.LOW}
          </Badge>
        );
    }
  };

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* Issues Header & Actions Card */}
      <Card className="shadow-none">
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <AlertTriangle className="size-4 text-primary" />
                <span>{t.title}</span>
              </CardTitle>
              <CardDescription className="text-xs mt-1">{t.subtitle}</CardDescription>
            </div>
            {canMutate && (
              <Button
                type="button"
                onClick={() => {
                  setIsOpenNewDialog(true);
                  setErrorMessage(null);
                }}
                className="text-xs gap-1.5 self-start sm:self-auto"
              >
                <PlusCircle className="size-3.5" />
                <span>{t.newIssueButton}</span>
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {errorMessage && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-800 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* New Issue Form */}
          {isOpenNewDialog && (
            <Card className="border-primary/40 bg-muted/20 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">{t.dialogs.newTitle}</CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleCreateIssue} className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.dialogs.typeLabel} *</Label>
                      <Select
                        value={newType}
                        onValueChange={(val) => setNewType(val as ExecutionIssueTypeEnum)}
                      >
                        <SelectTrigger className="text-xs">
                          <SelectValue placeholder="نوع مغایرت…" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="QUALITY">{t.types.QUALITY}</SelectItem>
                          <SelectItem value="QUANTITY">{t.types.QUANTITY}</SelectItem>
                          <SelectItem value="LOGISTICS">{t.types.LOGISTICS}</SelectItem>
                          <SelectItem value="PAYMENT">{t.types.PAYMENT}</SelectItem>
                          <SelectItem value="DOCUMENT">{t.types.DOCUMENT}</SelectItem>
                          <SelectItem value="CONTRACT">{t.types.CONTRACT}</SelectItem>
                          <SelectItem value="OTHER">{t.types.OTHER}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.dialogs.severityLabel}</Label>
                      <Select
                        value={newSeverity}
                        onValueChange={(val) => setNewSeverity(val as ExecutionIssueSeverityEnum)}
                      >
                        <SelectTrigger className="text-xs">
                          <SelectValue placeholder="شدت…" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="LOW">{t.severities.LOW}</SelectItem>
                          <SelectItem value="MEDIUM">{t.severities.MEDIUM}</SelectItem>
                          <SelectItem value="HIGH">{t.severities.HIGH}</SelectItem>
                          <SelectItem value="CRITICAL">{t.severities.CRITICAL}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.dialogs.titleLabel} *</Label>
                      <Input
                        value={newTitle}
                        onChange={(e) => setNewTitle(e.target.value)}
                        placeholder={t.dialogs.titlePlaceholder}
                        required
                        className="text-xs"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">{t.dialogs.descLabel}</Label>
                    <Textarea
                      value={newDesc}
                      onChange={(e) => setNewDesc(e.target.value)}
                      placeholder={t.dialogs.descPlaceholder}
                      className="text-xs resize-none"
                      rows={2}
                    />
                  </div>

                  {/* Direct Blocker Checkbox */}
                  <div className="flex items-center gap-2 pt-1">
                    <input
                      id="blockingCheckbox"
                      type="checkbox"
                      checked={newBlocksExecution}
                      onChange={(e) => setNewBlocksExecution(e.target.checked)}
                      className="size-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
                    />
                    <Label htmlFor="blockingCheckbox" className="text-xs font-medium cursor-pointer text-destructive">
                      {t.dialogs.blockingLabel}
                    </Label>
                  </div>

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setIsOpenNewDialog(false)}
                      disabled={isSubmittingNew}
                      className="text-xs"
                    >
                      {messages.dealWorkspace.executionMonitor.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmittingNew || !newTitle.trim()}
                      className="text-xs gap-1.5"
                    >
                      {isSubmittingNew && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmittingNew ? "در حال ثبت…" : "ثبت مغایرت"}</span>
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}

          {/* Issues List / Cards */}
          {isLoadingIssues ? (
            <LoadingState variant="section" message={messages.dealWorkspace.loading} locale={locale} />
          ) : issues.length === 0 ? (
            <EmptyState
              icon={<AlertTriangle className="size-8 text-muted-foreground/60" />}
              title={t.title}
              description={t.empty}
              locale={locale}
            />
          ) : (
            <div className="divide-y divide-border border rounded-lg overflow-hidden">
              {issues.map((issue) => {
                const typeLabel =
                  t.types[issue.type as keyof typeof t.types] || issue.type;

                return (
                  <div key={issue.id} className="p-4 bg-card hover:bg-muted/10 transition-colors space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                      <div className="space-y-1 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="text-[11px] py-0 border-border">
                            {typeLabel}
                          </Badge>
                          {renderSeverityBadge(issue.severity)}
                          {renderStatusBadge(issue.status)}

                          {/* Direct Blocker Badge */}
                          {issue.blocks_execution ? (
                            <Badge variant="outline" className="border-destructive/40 text-destructive bg-destructive/10 text-[10px] py-0 font-semibold">
                              <ShieldAlert className="size-3 me-1" />
                              <span>{t.blocksCloseBadge}</span>
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="border-border text-muted-foreground text-[10px] py-0">
                              <span>{t.nonBlockingBadge}</span>
                            </Badge>
                          )}
                        </div>

                        <h3 className="font-semibold text-sm pt-1">{issue.title}</h3>
                        {issue.description && (
                          <p className="text-xs text-muted-foreground leading-relaxed">
                            {issue.description}
                          </p>
                        )}
                      </div>

                      {/* Issue Action Buttons */}
                      {canMutate && (
                        <div className="flex flex-wrap items-center gap-2 shrink-0">
                          {issue.status === "OPEN" && (
                            <Button
                              type="button"
                              variant="outline"
                              onClick={() => handleOpenAction(issue, "start")}
                              className="text-xs h-7 px-2.5"
                            >
                              {t.actions.start}
                            </Button>
                          )}

                          {(issue.status === "OPEN" || issue.status === "IN_PROGRESS") && (
                            <>
                              <Button
                                type="button"
                                variant="default"
                                onClick={() => handleOpenAction(issue, "resolve")}
                                className="text-xs h-7 px-2.5 gap-1"
                              >
                                <CheckCircle2 className="size-3" />
                                <span>{t.actions.resolve}</span>
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                onClick={() => handleOpenAction(issue, "cancel")}
                                className="text-xs h-7 px-2 text-destructive border-destructive/30 hover:bg-destructive/10"
                              >
                                {t.actions.cancel}
                              </Button>
                            </>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Metadata & Resolution info */}
                    <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 border-t border-dashed">
                      {issue.opened_at && (
                        <span>
                          {t.table.openedAt}:{" "}
                          <span className="font-mono text-foreground" dir="ltr">
                            {issue.opened_at.slice(0, 19).replace("T", " ")}
                          </span>
                        </span>
                      )}
                      {issue.opened_by_email && (
                        <span>
                          {t.table.openedBy}: <span className="font-mono text-foreground">{issue.opened_by_email}</span>
                        </span>
                      )}
                      {issue.resolved_at && (
                        <span>
                          {t.table.resolvedBy}:{" "}
                          <span className="font-mono text-foreground" dir="ltr">
                            {issue.resolved_at.slice(0, 19).replace("T", " ")}
                          </span>
                        </span>
                      )}
                    </div>

                    {issue.resolution_notes && (
                      <div className="rounded bg-muted/40 p-2.5 text-xs text-foreground">
                        <span className="font-semibold text-emerald-700">{t.table.resolutionNotes}: </span>
                        <span>{issue.resolution_notes}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Action Dialog (Resolve / Cancel) */}
          {activeIssueId && issueActionType && (
            <Card className="border-primary/40 bg-muted/20 shadow-sm mt-4">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">
                  {issueActionType === "resolve" ? t.dialogs.resolveTitle : t.dialogs.cancelTitle}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmitAction} className="space-y-4">
                  {issueActionType === "resolve" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.dialogs.resolutionNotesLabel} *</Label>
                      <Textarea
                        value={resolutionNotes}
                        onChange={(e) => setResolutionNotes(e.target.value)}
                        placeholder={t.dialogs.resolutionNotesPlaceholder}
                        required
                        className="text-xs resize-none"
                        rows={2}
                      />
                    </div>
                  )}

                  {issueActionType === "cancel" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.dialogs.cancelNotesLabel}</Label>
                      <Textarea
                        value={cancelNotes}
                        onChange={(e) => setCancelNotes(e.target.value)}
                        placeholder={t.dialogs.cancelNotesPlaceholder}
                        className="text-xs resize-none"
                        rows={2}
                      />
                    </div>
                  )}

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseAction}
                      disabled={isSubmittingAction}
                      className="text-xs"
                    >
                      {messages.dealWorkspace.executionMonitor.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmittingAction}
                      className="text-xs gap-1.5"
                    >
                      {isSubmittingAction && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmittingAction ? "در حال ثبت…" : "تأیید و اعمال"}</span>
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

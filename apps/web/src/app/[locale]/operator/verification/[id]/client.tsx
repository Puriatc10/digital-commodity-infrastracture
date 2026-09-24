"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VerificationBadge } from "@/components/verification-badge";
import { useAuth } from "@/lib/auth-context";
import {
  Loader2,
  Download,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileText,
  ShieldAlert,
  ArrowLeft,
} from "lucide-react";
import Link from "next/link";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";

type InternalVerificationDetail =
  components["schemas"]["InternalOrganizationVerificationDetail"];
type VerificationDoc = components["schemas"]["VerificationDocument"];

export function VerificationCaseDetailClient({
  id: organizationId,
  locale,
}: {
  id: string;
  locale: string;
}) {
  const messages = getMessages((locale || "fa") as EnabledLocale);
  const t = messages.verification.caseDetail;

  const queryClient = useQueryClient();
  const { state: authState } = useAuth();

  const isOperatorOrAdmin =
    authState.status === "authenticated" &&
    authState.systemRoles.some((r) => r === "operator" || r === "admin");

  const [reason, setReason] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [downloadingDocId, setDownloadingDocId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const getDocStatusInfo = (status: string) => {
    switch (status) {
      case "pending":
        return { label: t.documents.statuses.pending, className: "text-amber-600 bg-amber-50" };
      case "accepted":
        return { label: t.documents.statuses.accepted, className: "text-green-600 bg-green-50" };
      case "rejected":
        return { label: t.documents.statuses.rejected, className: "text-destructive bg-destructive/10" };
      case "replaced":
        return { label: t.documents.statuses.replaced, className: "text-muted-foreground bg-muted" };
      default:
        return { label: status, className: "text-muted-foreground" };
    }
  };

  // 1. Fetch case verification detail
  const {
    data: verificationData,
    isLoading: isVerLoading,
    isError: isVerError,
    refetch: refetchVerification,
  } = useQuery<InternalVerificationDetail>({
    queryKey: ["verificationCase", organizationId],
    queryFn: async () => {
      const response = await client.GET("/api/organizations/{org_id}/verification/", {
        params: { path: { org_id: organizationId } },
      });
      if (response.error || (response.response && !response.response.ok) || !response.data) {
        throw new Error("Failed to load verification case");
      }
      return response.data as InternalVerificationDetail;
    },
    enabled: isOperatorOrAdmin,
  });

  // 2. Fetch organization profile for context
  const { data: profileData } = useQuery({
    queryKey: ["organizations", "profiles", organizationId],
    queryFn: async () => {
      const response = await client.GET("/api/organizations/profiles/{id}/", {
        params: { path: { id: organizationId } },
      });
      if (response.error || (response.response && !response.response.ok)) return null;
      return response.data;
    },
    enabled: isOperatorOrAdmin,
  });

  // 3. Fetch evidence documents
  const {
    data: documentsData,
    isLoading: isDocsLoading,
    refetch: refetchDocs,
  } = useQuery<VerificationDoc[]>({
    queryKey: ["verificationDocuments", organizationId],
    queryFn: async () => {
      const response = await client.GET("/api/documents/", {
        params: { query: { organization: organizationId } },
      });
      const raw = response.data;
      if (Array.isArray(raw)) {
        return raw as VerificationDoc[];
      }
      if (raw && typeof raw === "object" && "results" in raw && Array.isArray((raw as { results?: unknown }).results)) {
        return (raw as { results: VerificationDoc[] }).results;
      }
      return [] as VerificationDoc[];
    },
    enabled: isOperatorOrAdmin,
  });

  const handleMutationSuccess = () => {
    setActionError(null);
    setReason("");
    setInternalNote("");
    void queryClient.invalidateQueries({ queryKey: ["verificationCase", organizationId] });
    void queryClient.invalidateQueries({ queryKey: ["verificationDocuments", organizationId] });
    void queryClient.invalidateQueries({ queryKey: ["verificationQueue"] });
  };

  const handleMutationError = (error: unknown, fallbackMessage: string) => {
    void refetchVerification();
    void refetchDocs();
    const err = error as { detail?: string; message?: string; status?: number };
    if (err?.status === 409 || (err?.message && err.message.includes("Stale"))) {
      setActionError(t.conflictError);
    } else {
      setActionError(err?.detail || err?.message || fallbackMessage);
    }
  };

  // Document download handler
  const handleDownloadDocument = async (doc: VerificationDoc) => {
    setDownloadingDocId(doc.id);
    setDownloadError(null);
    try {
      const res = await fetch(`/api/documents/${doc.id}/download/`, {
        credentials: "include",
      });
      if (!res.ok) {
        if (res.status === 403) {
          throw new Error("شما مجوز دانلود این سند را ندارید.");
        }
        if (res.status === 404) {
          throw new Error("فایل سند در فضای ذخیره‌سازی یافت نشد.");
        }
        throw new Error(`خطا در دانلود سند (${res.status})`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.file_name || `document-${doc.id}.bin`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "خطا در بارگیری فایل مدرک";
      setDownloadError(message);
    } finally {
      setDownloadingDocId(null);
    }
  };

  // Actions
  const startReviewMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/start_review/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در شروع بررسی"),
  });

  const approveBasicMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/approve_basic/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در اعطای تاییدیه اولیه"),
  });

  const approveFullMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/approve_full/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در اعطای تاییدیه کامل"),
  });

  const rejectMutation = useMutation({
    mutationFn: async () => {
      if (!reason.trim()) throw new Error("دلیل رد پرونده الزامی است.");
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/reject/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0, reason: reason.trim() },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در رد پرونده"),
  });

  const suspendMutation = useMutation({
    mutationFn: async () => {
      if (!reason.trim()) throw new Error("دلیل تعلیق الزامی است.");
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/suspend/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0, reason: reason.trim() },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در تعلیق پرونده"),
  });

  const reopenMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/reopen/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در بازگشایی پرونده"),
  });

  const addNoteMutation = useMutation({
    mutationFn: async () => {
      if (!internalNote.trim()) throw new Error(t.decision.emptyNoteError);
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/notes/",
        {
          params: { path: { org_id: organizationId } },
          body: { note: internalNote.trim() },
        }
      );
      if (!res.response.ok) throw new Error("خطا در ثبت یادداشت داخلی");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در ثبت یادداشت داخلی"),
  });

  const reviewChecklistMutation = useMutation({
    mutationFn: async ({
      documentId,
      outcome,
    }: {
      documentId: string;
      outcome: "accepted" | "rejected";
    }) => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/checklist/",
        {
          params: { path: { org_id: organizationId } },
          body: {
            document_id: documentId,
            outcome,
            expected_version: verificationData?.version ?? 0,
          },
        }
      );
      if (res.error) throw res.error;
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: (err) => handleMutationError(err, "خطا در بررسی مدرک"),
  });

  if (authState.status === "loading" || isVerLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="sr-only">{t.loadingSr}</span>
      </div>
    );
  }

  if (!isOperatorOrAdmin) {
    return (
      <Card className="p-8 text-center">
        <div className="flex flex-col items-center gap-3">
          <ShieldAlert className="h-10 w-10 text-destructive" />
          <h2 className="text-lg font-semibold text-destructive">{t.unauthorizedTitle}</h2>
          <span className="sr-only">{t.unauthorizedSr}</span>
          <p className="text-sm text-muted-foreground">
            {t.unauthorizedDesc}
          </p>
        </div>
      </Card>
    );
  }

  if (isVerError || !verificationData) {
    return (
      <Card className="p-8 text-center">
        <p className="text-destructive font-medium">
          {t.loadError}
          <span className="sr-only">{t.errorSr}</span>
        </p>
        <Button onClick={() => refetchVerification()} variant="outline" className="mt-4">
          {t.retry}
        </Button>
      </Card>
    );
  }

  const isAnyActionPending =
    startReviewMutation.isPending ||
    approveBasicMutation.isPending ||
    approveFullMutation.isPending ||
    rejectMutation.isPending ||
    suspendMutation.isPending ||
    reopenMutation.isPending ||
    reviewChecklistMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Header with back button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href={`/${locale}/operator/verification`}
            className="flex h-9 w-9 items-center justify-center rounded-md border border-border hover:bg-accent"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h2 className="text-xl font-bold">
              {profileData?.name ? t.title.replace("{name}", profileData.name) : t.defaultTitle}
            </h2>
            <p className="text-xs text-muted-foreground">{t.orgIdLabel} {organizationId}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{t.caseVersionLabel} v{verificationData.version}</span>
          <VerificationBadge status={verificationData.status} />
        </div>
      </div>

      {actionError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span>{actionError}</span>
        </div>
      )}

      {downloadError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span>{downloadError}</span>
        </div>
      )}

      {/* Operator Workflow Action Panel */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">{t.actions.panelTitle}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            {verificationData.status === "documents_submitted" && (
              <Button
                onClick={() => startReviewMutation.mutate()}
                disabled={isAnyActionPending}
                className="bg-primary text-primary-foreground"
              >
                {startReviewMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                {t.actions.startReview}
              </Button>
            )}

            {verificationData.status === "under_review" && (
              <>
                <Button
                  onClick={() => approveBasicMutation.mutate()}
                  disabled={isAnyActionPending}
                  className="bg-teal-600 text-white hover:bg-teal-700"
                >
                  {approveBasicMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                  {t.actions.approveBasic}
                </Button>
                <Button
                  onClick={() => approveFullMutation.mutate()}
                  disabled={isAnyActionPending}
                  className="bg-green-600 text-white hover:bg-green-700"
                >
                  {approveFullMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                  {t.actions.approveFull}
                </Button>
              </>
            )}

            {(verificationData.status === "suspended" || verificationData.status === "basic_verified") && (
              <Button
                onClick={() => reopenMutation.mutate()}
                disabled={isAnyActionPending}
                variant="outline"
              >
                {reopenMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                {t.actions.reopen}
              </Button>
            )}
          </div>

          {/* Rejection / Suspension with reason */}
          {verificationData.status === "under_review" && (
            <div className="flex flex-col gap-2 pt-2 border-t sm:flex-row sm:items-center">
              <Input
                placeholder={t.decision.reasonPlaceholder}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="flex-1"
                disabled={isAnyActionPending}
              />
              <Button
                variant="outline"
                className="border-destructive text-destructive hover:bg-destructive/10"
                onClick={() => rejectMutation.mutate()}
                disabled={isAnyActionPending || !reason.trim()}
              >
                {rejectMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                {t.actions.reject}
              </Button>
            </div>
          )}

          {(verificationData.status === "basic_verified" || verificationData.status === "verified") && (
            <div className="flex flex-col gap-2 pt-2 border-t sm:flex-row sm:items-center">
              <Input
                placeholder={t.decision.suspendPlaceholder}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="flex-1"
                disabled={isAnyActionPending}
              />
              <Button
                variant="outline"
                className="border-destructive text-destructive hover:bg-destructive/10"
                onClick={() => suspendMutation.mutate()}
                disabled={isAnyActionPending || !reason.trim()}
              >
                {suspendMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
                {t.actions.suspend}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Evidence Checklist with Authorized Download */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">{t.documents.title}</CardTitle>
        </CardHeader>
        <CardContent>
          {isDocsLoading ? (
            <div className="flex items-center justify-center p-6">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : !documentsData || documentsData.length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              {t.documents.empty}
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {documentsData.map((doc) => {
                const statusInfo = getDocStatusInfo(doc.verification_status);
                const isDownloading = downloadingDocId === doc.id;
                const isReviewable =
                  verificationData.status === "under_review" &&
                  doc.verification_status !== "replaced";

                return (
                  <li key={doc.id} className="flex flex-wrap items-center justify-between gap-4 py-3">
                    <div className="flex items-center gap-3">
                      <FileText className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">
                          {(t.documents.types as Record<string, string>)[doc.type] || doc.type}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {doc.file_name} · {(doc.size_bytes / 1024).toFixed(0)} {t.documents.sizeUnit} · {t.documents.registeredAt}{" "}
                          {new Date(doc.created_at).toLocaleDateString(locale === "fa" ? "fa-IR" : "en-US")}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className={`rounded-md px-2.5 py-1 text-xs font-medium ${statusInfo.className}`}>
                        {statusInfo.label}
                      </span>

                      {/* Authorized Download Button */}
                      <Button
                        variant="outline"
                        onClick={() => handleDownloadDocument(doc)}
                        disabled={isDownloading}
                        className="flex items-center gap-1.5 min-h-8 px-2.5 py-1 text-xs"
                      >
                        {isDownloading ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Download className="h-3.5 w-3.5" />
                        )}
                        {t.documents.download}
                      </Button>

                      {/* Checklist Accept / Reject Buttons */}
                      {isReviewable && (
                        <div className="flex items-center gap-1.5">
                          <Button
                            variant="outline"
                            className="border-green-600 text-green-600 hover:bg-green-50 min-h-8 px-2.5 py-1 text-xs"
                            onClick={() =>
                              reviewChecklistMutation.mutate({
                                documentId: doc.id,
                                outcome: "accepted",
                              })
                            }
                            disabled={isAnyActionPending}
                          >
                            <CheckCircle2 className="h-3.5 w-3.5 me-1" />
                            {t.actions.accept}
                          </Button>
                          <Button
                            variant="outline"
                            className="border-destructive text-destructive hover:bg-destructive/10 min-h-8 px-2.5 py-1 text-xs"
                            onClick={() =>
                              reviewChecklistMutation.mutate({
                                documentId: doc.id,
                                outcome: "rejected",
                              })
                            }
                            disabled={isAnyActionPending}
                          >
                            <XCircle className="h-3.5 w-3.5 me-1" />
                            {t.actions.checklistReject}
                          </Button>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Internal Notes (Operator only) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">{t.history.notesTitle}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {verificationData.notes && verificationData.notes.length > 0 ? (
            <ul className="space-y-3">
              {verificationData.notes.map((note) => (
                <li key={note.id} className="rounded-md border bg-muted/30 p-3 text-sm">
                  <div className="flex items-center justify-between pb-1 text-xs text-muted-foreground border-b border-border/50 mb-2">
                    <span className="font-medium">{note.actor_email}</span>
                    <span>{new Date(note.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}</span>
                  </div>
                  <p className="whitespace-pre-wrap">{note.note}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t.history.emptyNotes}</p>
          )}

          <div className="flex flex-col gap-2 pt-2 border-t sm:flex-row sm:items-center">
            <Input
              placeholder={t.decision.internalNotePlaceholder}
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
              className="flex-1"
              disabled={addNoteMutation.isPending}
            />
            <Button
              onClick={() => addNoteMutation.mutate()}
              disabled={addNoteMutation.isPending || !internalNote.trim()}
              variant="outline"
            >
              {addNoteMutation.isPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
              {t.actions.addNote}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Decision History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">{t.history.decisionTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          {verificationData.decisions && verificationData.decisions.length > 0 ? (
            <ul className="divide-y divide-border">
              {verificationData.decisions.map((decision) => (
                <li key={decision.id} className="py-3 text-sm">
                  <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                    <span className="font-medium">{decision.actor_email}</span>
                    <span>{new Date(decision.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{decision.action}:</span>
                    <span>{decision.previous_status} ➔ {decision.new_status}</span>
                  </div>
                  {decision.reason && (
                    <p className="mt-1 text-xs text-muted-foreground bg-muted/50 p-2 rounded">
                      {t.decision.reasonPrefix} {decision.reason}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t.history.emptyDecisions}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

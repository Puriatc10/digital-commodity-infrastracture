"use client";

import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { VerificationBadge } from "@/components/verification-badge";
import { useOptionalAuth } from "@/lib/auth-context";
import {
  Loader2,
  Upload,
  FileText,
  CheckCircle2,
  AlertTriangle,
  Send,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { getMessages, type Messages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import {
  LoadingState,
  NotFoundState,
  AccessDeniedState,
  ErrorState,
} from "@/components/states";
import type { components } from "@/lib/api/generated/schema";

type VerificationDoc = components["schemas"]["VerificationDocument"];

const REQUIRED_EVIDENCE_KEYS = [
  "company_registration",
  "tax_id",
  "bank_details",
  "authorized_representative",
] as const;

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB
const ALLOWED_MIME_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/jpg",
];
const ALLOWED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"];

function getCapabilityBadge(cap: string, tDir: Messages["directory"]) {
  switch (cap) {
    case "buyer":
      return (
        <Badge variant="outline" key={cap}>
          {tDir.filters.roles.buyer}
        </Badge>
      );
    case "supplier":
      return (
        <Badge variant="outline" key={cap}>
          {tDir.filters.roles.supplier}
        </Badge>
      );
    case "broker":
      return (
        <Badge variant="outline" key={cap}>
          {tDir.filters.roles.broker}
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" key={cap}>
          {cap}
        </Badge>
      );
  }
}

export function ProfileClient({ id }: { id: string }) {
  const pathname = usePathname();
  const locale = ((pathname?.split("/")[1] as EnabledLocale) || "fa") as EnabledLocale;
  const messages = getMessages(locale);
  const t = messages.directory.profile;
  const tDir = messages.directory;

  const queryClient = useQueryClient();
  const authContext = useOptionalAuth();
  const authState = authContext?.state;
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedType, setSelectedType] = useState<string>("company_registration");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // Check if current user is an Owner or Manager of this organization
  const isOwnerOrManager =
    authState &&
    authState.status === "authenticated" &&
    authState.availableOrganizations.some(
      (ctx) =>
        ctx.organization.id === id &&
        (ctx.role === "owner" || ctx.role === "manager")
    );

  // 1. Fetch organization profile
  const {
    data: profile,
    isLoading: isProfileLoading,
    isError: isProfileError,
    error: profileError,
  } = useQuery({
    queryKey: ["organizations", "profiles", id],
    queryFn: async () => {
      const { data, error, response } = await client.GET(
        "/api/organizations/profiles/{id}/",
        {
          params: { path: { id } },
        }
      );
      if (response.status === 404) {
        const err = new Error("Not found");
        (err as unknown as { status: number }).status = 404;
        throw err;
      }
      if (response.status === 401 || response.status === 403) {
        const err = new Error("Access denied");
        (err as unknown as { status: number }).status = response.status;
        throw err;
      }
      if (error || !response.ok || !data) {
        const err = error || new Error("Profile not found");
        (err as unknown as { status: number }).status = response.status;
        throw err;
      }
      return data;
    },
    retry: false,
  });

  // 2. Fetch customer documents (only enabled if owner or manager)
  const {
    data: documents,
    isLoading: isDocsLoading,
    refetch: refetchDocs,
  } = useQuery<VerificationDoc[]>({
    queryKey: ["organizationDocuments", id],
    queryFn: async () => {
      const res = await client.GET("/api/documents/", {
        params: { query: { organization: id } },
      });
      if (res.error || (res.response && !res.response.ok)) {
        throw new Error("Failed to load documents");
      }
      const raw = res.data;
      if (Array.isArray(raw)) {
        return raw as VerificationDoc[];
      }
      if (raw && typeof raw === "object" && "results" in raw && Array.isArray((raw as { results?: unknown }).results)) {
        return (raw as { results: VerificationDoc[] }).results;
      }
      return [] as VerificationDoc[];
    },
    enabled: isOwnerOrManager,
  });

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async ({ file, type }: { file: File; type: string }) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("type", type);
      formData.append("organization", id);

      const res = await fetch("/api/documents/upload/", {
        method: "POST",
        body: formData,
        credentials: "include",
      });

      if (!res.ok) {
        let errorMsg = "خطا در بارگذاری مدرک.";
        try {
          const json = await res.json();
          errorMsg = json.detail || json.file?.[0] || json.type?.[0] || errorMsg;
        } catch {
          // ignore
        }
        throw new Error(errorMsg);
      }
      return res.json();
    },
    onSuccess: () => {
      setUploadSuccess(t.uploadSuccess);
      setUploadError(null);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      void refetchDocs();
      void queryClient.invalidateQueries({ queryKey: ["organizations", "profiles", id] });
    },
    onError: (err) => {
      setUploadError(err instanceof Error ? err.message : t.fileTypeError);
      setUploadSuccess(null);
    },
  });

  // Submit for verification mutation
  const submitVerificationMutation = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await client.POST(
        "/api/organizations/{org_id}/verification/submit/",
        {
          params: { path: { org_id: id } },
          body: {},
        }
      );
      if (error || !response.ok) {
        const detail =
          typeof error === "object" && error && "detail" in error
            ? String((error as Record<string, unknown>).detail)
            : "خطا در ارسال درخواست بررسی.";
        throw new Error(detail);
      }
      return data;
    },
    onSuccess: () => {
      setSubmitSuccess(t.submitSuccess);
      setSubmitError(null);
      void queryClient.invalidateQueries({ queryKey: ["organizations", "profiles", id] });
      void refetchDocs();
    },
    onError: (err) => {
      setSubmitError(err instanceof Error ? err.message : "خطا در ارسال درخواست احراز هویت");
      setSubmitSuccess(null);
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadError(null);
    setUploadSuccess(null);
    const file = e.target.files?.[0];
    if (!file) {
      setSelectedFile(null);
      return;
    }

    // Client-side format validation
    const fileExt = "." + file.name.split(".").pop()?.toLowerCase();
    const isExtensionValid = ALLOWED_EXTENSIONS.includes(fileExt);
    const isMimeValid = ALLOWED_MIME_TYPES.includes(file.type);

    if (!isExtensionValid && !isMimeValid) {
      setUploadError(t.fileTypeError);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    // Client-side size validation
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setUploadError(t.fileSizeError);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setSelectedFile(file);
  };

  const handleUploadSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadError(t.selectFileError);
      return;
    }
    uploadMutation.mutate({ file: selectedFile, type: selectedType });
  };

  const profileStatus = (profileError as unknown as { status?: number })?.status;

  if (isProfileLoading) {
    return <LoadingState locale={locale} />;
  }

  if (profileStatus === 401 || profileStatus === 403) {
    return (
      <AccessDeniedState
        statusCode={profileStatus as 401 | 403}
        backHref={`/${locale}/directory`}
        backLabel={messages.states.notFound.backToList}
        locale={locale}
      />
    );
  }

  if (profileStatus === 404) {
    return (
      <NotFoundState
        resourceType="organization"
        title={t.notFound}
        backHref={`/${locale}/directory`}
        backLabel={messages.states.notFound.backToList}
        locale={locale}
      />
    );
  }

  if (isProfileError || !profile) {
    return (
      <ErrorState
        errorMessage={t.notFound}
        onRetry={() => void queryClient.invalidateQueries({ queryKey: ["organizations", "profiles", id] })}
        backHref={`/${locale}/directory`}
        backLabel={messages.states.notFound.backToList}
        locale={locale}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Basic Organization Info */}
      <Card>
        <CardHeader>
          <CardTitle>{t.orgInfo}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-muted-foreground">{t.name}</p>
            <p className="text-base font-semibold">{profile.name}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">{t.country}</p>
            <p className="text-base">{profile.country || "-"}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">{t.website}</p>
            <p className="text-base">
              {profile.website ? (
                <a
                  href={profile.website}
                  target="_blank"
                  rel="noreferrer"
                  dir="ltr"
                  className="inline-block text-primary hover:underline"
                >
                  {profile.website}
                </a>
              ) : (
                "-"
              )}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Verification Status */}
      <Card>
        <CardHeader>
          <CardTitle>{t.verificationStatus}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">{t.currentStatus}</span>
            <VerificationBadge status={profile.verification_status} />
          </div>

          {/* Customer Submit for Verification (Owner/Manager and Unverified) */}
          {isOwnerOrManager && profile.verification_status === "unverified" && (
            <div className="pt-3 border-t">
              {submitError && (
                <div className="mb-3 flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{submitError}</span>
                </div>
              )}
              {submitSuccess && (
                <div className="mb-3 flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-3 text-xs text-green-700">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>{submitSuccess}</span>
                </div>
              )}
              <Button
                onClick={() => submitVerificationMutation.mutate()}
                disabled={submitVerificationMutation.isPending}
                className="bg-primary text-primary-foreground flex items-center gap-2"
              >
                {submitVerificationMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {t.submitVerification}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Roles & Commodities */}
      <Card>
        <CardHeader>
          <CardTitle>{t.rolesAndCommodities}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">{t.roles}</p>
            <div className="flex gap-2 flex-wrap">
              {profile.capabilities.length > 0
                ? profile.capabilities.map((cap) => getCapabilityBadge(cap, tDir))
                : "-"}
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">{t.commodities}</p>
            <div className="flex gap-2 flex-wrap">
              {profile.commodities.length > 0
                ? profile.commodities.map((comm) => (
                    <Badge variant="secondary" key={comm}>
                      {comm}
                    </Badge>
                  ))
                : "-"}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Customer Evidence Management (Owner/Manager only) */}
      {isOwnerOrManager && (
        <Card>
          <CardHeader>
            <CardTitle>{t.evidenceTitle}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Status of Required Evidence Types */}
            <div>
              <h4 className="text-sm font-semibold mb-3">{t.requiredEvidenceStatus}</h4>
              {isDocsLoading ? (
                <div className="flex items-center justify-center p-4">
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {REQUIRED_EVIDENCE_KEYS.map((key) => {
                    const label = t.evidenceTypes[key];
                    const currentDoc = documents?.find(
                      (d) => d.type === key && d.is_current
                    );
                    return (
                      <div
                        key={key}
                        className="rounded-lg border border-border p-3.5 flex flex-col justify-between gap-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">{label}</span>
                          {currentDoc ? (
                            <span
                              className={`text-xs px-2 py-0.5 rounded ${
                                currentDoc.verification_status === "accepted"
                                  ? "bg-green-100 text-green-700"
                                  : currentDoc.verification_status === "rejected"
                                  ? "bg-red-100 text-red-700"
                                  : "bg-amber-100 text-amber-700"
                              }`}
                            >
                              {currentDoc.verification_status === "accepted"
                                ? t.docStatuses.accepted
                                : currentDoc.verification_status === "rejected"
                                ? t.docStatuses.rejected
                                : t.docStatuses.pending}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                              {t.notUploaded}
                            </span>
                          )}
                        </div>
                        {currentDoc && (
                          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <FileText className="h-3.5 w-3.5 shrink-0" />
                            <span className="truncate">
                              <bdi className="font-mono">{currentDoc.file_name}</bdi>
                            </span>
                            <span>
                              <bdi dir="ltr">({(currentDoc.size_bytes / 1024).toFixed(0)} {t.fileSizeLabel})</bdi>
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Upload/Replace Form */}
            <div className="pt-4 border-t space-y-4">
              <h4 className="text-sm font-semibold">{t.uploadTitle}</h4>

              {uploadError && (
                <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{uploadError}</span>
                </div>
              )}

              {uploadSuccess && (
                <div className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-3 text-xs text-green-700">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>{uploadSuccess}</span>
                </div>
              )}

              <form
                onSubmit={handleUploadSubmit}
                className="flex flex-col gap-4 sm:flex-row sm:items-end"
              >
                <div className="w-full sm:w-64 space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">{t.docType}</label>
                  <Select
                    value={selectedType}
                    onValueChange={(val) => setSelectedType(val)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t.selectDocType} />
                    </SelectTrigger>
                    <SelectContent>
                      {REQUIRED_EVIDENCE_KEYS.map((key) => (
                        <SelectItem key={key} value={key}>
                          {t.evidenceTypes[key]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex-1 space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    {t.allowedTypesNotice}
                  </label>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={handleFileChange}
                    className="block w-full text-xs text-muted-foreground file:me-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20"
                  />
                </div>

                <Button
                  type="submit"
                  disabled={!selectedFile || uploadMutation.isPending}
                  className="w-full sm:w-auto flex items-center gap-2"
                >
                  {uploadMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  {uploadMutation.isPending ? t.uploading : t.uploadButton}
                </Button>
              </form>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Activity Summary */}
      <Card>
        <CardHeader>
          <CardTitle>{t.activitySummary}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t.activityUnavailable}</p>
        </CardContent>
      </Card>
    </div>
  );
}

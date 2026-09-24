"use client";

import React, { useState, useRef } from "react";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertTriangle,
  Download,
  FileText,
  FileUp,
  Loader2,
  Paperclip,
} from "lucide-react";
import type {
  ExecutionDetail,
  ExecutionDocument,
  CategoryEnum,
} from "./types";

export interface DocumentsTabProps {
  locale?: EnabledLocale;
  execution: ExecutionDetail | null;
  documents: ExecutionDocument[];
  isLoadingDocuments: boolean;
  isOperatorOrAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
  isViewer: boolean;
  onRefreshDocuments: () => Promise<void>;
  onRefreshTimeline: () => Promise<void>;
}

export function DocumentsTab({
  locale = "fa",
  execution,
  documents,
  isLoadingDocuments,
  isOperatorOrAdmin,
  isBuyer,
  isSeller,
  isViewer,
  onRefreshDocuments,
  onRefreshTimeline,
}: DocumentsTabProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace.executionMonitor.documents;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<CategoryEnum | "">("");
  const [selectedAssociationType, setSelectedAssociationType] = useState<"none" | "milestone" | "inspection" | "issue">("none");
  const [selectedMilestoneId, setSelectedMilestoneId] = useState<string>("");

  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  if (!execution) {
    return (
      <Card className="p-12 text-center shadow-none border-dashed" dir={isRtl ? "rtl" : "ltr"}>
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
          <FileText className="size-6 text-muted-foreground" />
        </div>
        <h2 className="mt-4 text-base font-semibold">{t.title}</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
          {messages.dealWorkspace.executionMonitor.uninitialized.description}
        </p>
      </Card>
    );
  }

  const isOpen = execution.status === "OPEN";
  const canUpload = isOpen && !isViewer && (isOperatorOrAdmin || isBuyer || isSeller);

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const handleDownload = async (doc: ExecutionDocument) => {
    setDownloadError(null);
    try {
      const response = await fetch(`/api/execution/${execution.id}/documents/${doc.id}/download/`, {
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error(`Download failed: ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = doc.file_name;
      document.body.appendChild(link);
      link.click();
      window.URL.revokeObjectURL(url);
      link.remove();
    } catch {
      setDownloadError("خطا در دریافت فایل مدرک. لطفاً اتصال اینترنت خود را بررسی و دوباره تلاش کنید.");
    }
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || !selectedCategory) {
      setUploadError("لطفاً فایل و دسته‌بندی مدرک را انتخاب نمایید.");
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    const milestoneId = selectedAssociationType === "milestone" ? selectedMilestoneId || null : null;
    const inspectionId = selectedAssociationType === "inspection" && execution.inspection ? execution.inspection.id : null;

    try {
      const { response } = await apiClient.POST(
        "/api/execution/{execution_id}/documents/upload/",
        {
          params: { path: { execution_id: execution.id } },
          body: {
            file: selectedFile.name,
            category: selectedCategory as CategoryEnum,
            milestone_id: milestoneId,
            inspection_id: inspectionId,
            issue_id: null,
          },
          bodySerializer() {
            const formData = new FormData();
            formData.append("file", selectedFile);
            formData.append("category", selectedCategory);
            if (milestoneId) formData.append("milestone_id", milestoneId);
            if (inspectionId) formData.append("inspection_id", inspectionId);
            return formData;
          },
        }
      );

      if (response.ok) {
        setSelectedFile(null);
        setSelectedCategory("");
        setSelectedAssociationType("none");
        setSelectedMilestoneId("");
        if (fileInputRef.current) fileInputRef.current.value = "";
        await onRefreshDocuments();
        await onRefreshTimeline();
      } else if (response.status === 409) {
        setUploadError(messages.dealWorkspace.executionMonitor.conflictError);
        await onRefreshDocuments();
      } else {
        setUploadError(messages.dealWorkspace.executionMonitor.genericError);
      }
    } catch {
      setUploadError(messages.dealWorkspace.executionMonitor.genericError);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* Upload Form Card */}
      {canUpload && (
        <Card className="shadow-none border-primary/20 bg-muted/20">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <FileUp className="size-4 text-primary" />
              <span>{t.uploadTitle}</span>
            </CardTitle>
            <CardDescription className="text-xs">{t.uploadDesc}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleUploadSubmit} className="space-y-4">
              {uploadError && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-800 flex items-start gap-2">
                  <AlertTriangle className="size-4 shrink-0 mt-0.5" />
                  <span>{uploadError}</span>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium">{t.fileLabel} *</Label>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        setSelectedFile(e.target.files[0]);
                      }
                    }}
                    required
                    className="block w-full text-xs text-muted-foreground file:me-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:bg-primary/90 cursor-pointer"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs font-medium">{t.categoryLabel} *</Label>
                  <Select
                    value={selectedCategory}
                    onValueChange={(val) => setSelectedCategory(val as CategoryEnum)}
                  >
                    <SelectTrigger className="text-xs">
                      <SelectValue placeholder="انتخاب دسته‌بندی…" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="CONTRACT">{t.categories.CONTRACT}</SelectItem>
                      <SelectItem value="PAYMENT_PROOF">{t.categories.PAYMENT_PROOF}</SelectItem>
                      <SelectItem value="LOADING_DOCUMENT">{t.categories.LOADING_DOCUMENT}</SelectItem>
                      <SelectItem value="INSPECTION_REPORT">{t.categories.INSPECTION_REPORT}</SelectItem>
                      <SelectItem value="TRANSPORT_DOCUMENT">{t.categories.TRANSPORT_DOCUMENT}</SelectItem>
                      <SelectItem value="DELIVERY_PROOF">{t.categories.DELIVERY_PROOF}</SelectItem>
                      <SelectItem value="ACCEPTANCE_DOCUMENT">{t.categories.ACCEPTANCE_DOCUMENT}</SelectItem>
                      <SelectItem value="OTHER">{t.categories.OTHER}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs font-medium">{t.associationLabel}</Label>
                  <Select
                    value={selectedAssociationType}
                    onValueChange={(val) => setSelectedAssociationType(val as typeof selectedAssociationType)}
                  >
                    <SelectTrigger className="text-xs">
                      <SelectValue placeholder="نوع انتساب…" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t.noAssociation}</SelectItem>
                      <SelectItem value="milestone">گام اجرایی خاص</SelectItem>
                      {execution.inspection && (
                        <SelectItem value="inspection">{t.inspectionAssociation}</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {selectedAssociationType === "milestone" && (
                <div className="space-y-1.5 max-w-sm">
                  <Label className="text-xs font-medium">انتخاب گام مرتبط *</Label>
                  <Select
                    value={selectedMilestoneId}
                    onValueChange={setSelectedMilestoneId}
                  >
                    <SelectTrigger className="text-xs">
                      <SelectValue placeholder="انتخاب گام…" />
                    </SelectTrigger>
                    <SelectContent>
                      {execution.milestones?.map((m) => (
                        <SelectItem key={m.id} value={m.id}>
                          {m.name_fa || m.name_en || m.code}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <Button
                  type="submit"
                  disabled={isUploading || !selectedFile || !selectedCategory}
                  className="text-xs gap-1.5"
                >
                  {isUploading && <Loader2 className="size-3.5 animate-spin" />}
                  <span>{isUploading ? t.uploading : t.uploadButton}</span>
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Documents Table Card */}
      <Card className="shadow-none">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Paperclip className="size-4 text-primary" />
            <span>{t.title}</span>
          </CardTitle>
          <CardDescription className="text-xs">{t.subtitle}</CardDescription>
        </CardHeader>
        <CardContent>
          {downloadError && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive mb-4">
              {downloadError}
            </div>
          )}

          {isLoadingDocuments ? (
            <div className="flex items-center justify-center p-8 text-muted-foreground gap-2">
              <Loader2 className="size-4 animate-spin text-primary" />
              <span className="text-xs">{messages.dealWorkspace.loading}</span>
            </div>
          ) : documents.length === 0 ? (
            <p className="text-xs text-muted-foreground p-6 text-center">{t.empty}</p>
          ) : (
            <div className="border rounded-lg overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-xs">
                    <TableHead className="text-start">{t.table.fileName}</TableHead>
                    <TableHead className="text-start">{t.table.category}</TableHead>
                    <TableHead className="text-start">{t.table.size}</TableHead>
                    <TableHead className="text-start">{t.table.uploader}</TableHead>
                    <TableHead className="text-start">{t.table.uploadedAt}</TableHead>
                    <TableHead className="text-end">{t.table.actions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {documents.map((doc) => {
                    const categoryLabel =
                      t.categories[doc.category as keyof typeof t.categories] || doc.category;

                    return (
                      <TableRow key={doc.id} className="text-xs">
                        <TableCell className="font-medium flex items-center gap-2 max-w-xs truncate">
                          <FileText className="size-3.5 text-primary shrink-0" />
                          <span title={doc.file_name} className="truncate">
                            {doc.file_name}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[11px] py-0 border-border">
                            {categoryLabel}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-muted-foreground" dir="ltr">
                          {formatFileSize(doc.size_bytes)}
                        </TableCell>
                        <TableCell className="font-mono text-muted-foreground text-[11px]">
                          {doc.uploaded_by_email || "—"}
                        </TableCell>
                        <TableCell className="font-mono text-muted-foreground" dir="ltr">
                          {doc.uploaded_at ? doc.uploaded_at.slice(0, 19).replace("T", " ") : "—"}
                        </TableCell>
                        <TableCell className="text-end">
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => handleDownload(doc)}
                            className="text-xs h-7 px-2 gap-1 text-primary hover:text-primary border-primary/20"
                          >
                            <Download className="size-3" />
                            <span>{t.table.download}</span>
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

export function CustomerVerificationPanel({ orgId }: { orgId: string }) {
  const { state } = useAuth();
  const status = state.status;
  const user = state.status === "authenticated" ? state.user : null;
  const queryClient = useQueryClient();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("company_registration");
  const [uploadError, setUploadError] = useState("");

  const { data: verificationData, isLoading } = useQuery({
    queryKey: ["verification", orgId],
    queryFn: async () => {
      const res = await client.GET("/api/organizations/{org_id}/verification/", {
        params: { path: { org_id: orgId } },
      });
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to load verification status");
      return res.data;
    },
    enabled: !!user,
  });

  const { data: documentsData, isLoading: docsLoading } = useQuery({
    queryKey: ["documents", orgId],
    queryFn: async () => {
      const res = await client.GET("/api/documents/", {
        params: { query: { organization: orgId } as any },
      });
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to load documents");
      return res.data;
    },
    enabled: !!user,
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!selectedFile) return;

      const formData = new FormData();
      formData.append("organization", orgId);
      formData.append("type", docType);
      formData.append("file", selectedFile);

      const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || "";

      const res = await fetch("/api/documents/upload/", {
        method: "POST",
        body: formData,
        headers: {
          "X-CSRFToken": token,
        },
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Upload failed");
      }
      return res.json();
    },
    onSuccess: () => {
      setUploadError("");
      setSelectedFile(null);
      queryClient.invalidateQueries({ queryKey: ["documents", orgId] });
      queryClient.invalidateQueries({ queryKey: ["verification", orgId] });
    },
    onError: (err: any) => {
      setUploadError(err.message);
    }
  });

  const submitMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST("/api/organizations/{org_id}/verification/submit/", {
        params: { path: { org_id: orgId } },
        body: { expected_version: verificationData?.version ?? 0 },
      });
      if (res.error) throw new Error((res.error as any)?.detail || "Submit failed");
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["verification", orgId] });
    },
    onError: (err: any) => {
      setUploadError(err.message);
    }
  });

  if (status === "loading" || isLoading || docsLoading) return <p>در حال بارگذاری مدارک...</p>;
  if (!user) return null;

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>مدیریت مدارک و تاییدیه (Owner/Manager)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <strong>وضعیت تاییدیه: </strong>
          <Badge variant="outline">{verificationData?.status ?? "نامشخص"}</Badge>
        </div>

        <div className="border p-4 rounded-md space-y-4 bg-gray-50">
          <h3 className="font-semibold text-sm">آپلود مدرک جدید</h3>
          {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="border rounded p-2 text-sm"
            >
              <option value="company_registration">ثبت شرکت</option>
              <option value="tax_id">کد اقتصادی</option>
              <option value="trade_license">جواز کسب / پروانه بهره‌برداری</option>
              <option value="bank_details">اطلاعات حساب بانکی</option>
              <option value="authorized_representative">معرفی‌نامه نماینده رسمی</option>
              <option value="certifications">گواهی‌نامه‌های کیفیت</option>
            </select>
            <Input
              type="file"
              accept=".pdf,.jpeg,.jpg,.png"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
            />
            <Button
              onClick={() => uploadMutation.mutate()}
              disabled={uploadMutation.isPending || !selectedFile}
            >
              {uploadMutation.isPending ? "در حال آپلود..." : "آپلود"}
            </Button>
          </div>
          <p className="text-xs text-gray-500">فرمت‌های مجاز: PDF, JPEG, PNG (حداکثر ۱۰ مگابایت)</p>
        </div>

        <div className="mt-4">
          <h3 className="font-semibold text-sm mb-2">مدارک فعلی شما</h3>
          <ul className="space-y-2">
            {documentsData && documentsData.length > 0 ? documentsData.map((doc: any) => (
              <li key={doc.id} className="border p-2 rounded flex justify-between items-center bg-white">
                <div>
                  <span className="text-sm font-medium block">{doc.type}</span>
                  <span className="text-xs text-gray-500">{doc.file_name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary">{doc.verification_status}</Badge>
                  {!doc.is_current && <Badge variant="outline">قدیمی</Badge>}
                </div>
              </li>
            )) : <p className="text-sm text-gray-500">هیچ مدرکی آپلود نشده است.</p>}
          </ul>
        </div>

        <div className="mt-4 pt-4 border-t flex justify-end">
          <Button
            variant="default"
            onClick={() => submitMutation.mutate()}
            disabled={submitMutation.isPending || verificationData?.status === "under_review" || verificationData?.status === "suspended"}
          >
            {submitMutation.isPending ? "در حال ارسال..." : "ارسال برای بررسی"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import React, { useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { AlertTriangle, CheckCircle2, Loader2, MessageSquare, X } from "lucide-react";

type ComparisonRow = components["schemas"]["ComparisonRow"];
type RequestedFieldsEnum = components["schemas"]["RequestedFieldsEnum"];

export interface RevisionRequestModalProps {
  isOpen: boolean;
  onClose: () => void;
  row: ComparisonRow | null;
  locale?: EnabledLocale;
  onSuccess: () => void;
}

const CANONICAL_REVISION_FIELDS: Array<{
  key: RequestedFieldsEnum;
  labelKey: keyof typeof import("@/i18n/messages/fa").default.rfqWorkspace.comparison.revisionModal.fields;
}> = [
  { key: "unit_price", labelKey: "unit_price" },
  { key: "offered_quantity", labelKey: "offered_quantity" },
  { key: "payment_terms", labelKey: "payment_terms" },
  { key: "delivery_terms", labelKey: "delivery_terms" },
  { key: "incoterm", labelKey: "incoterm" },
  { key: "delivery_start", labelKey: "delivery_start" },
  { key: "delivery_end", labelKey: "delivery_end" },
  { key: "valid_until", labelKey: "valid_until" },
  { key: "specifications", labelKey: "specifications" },
  { key: "logistics_cost_amount", labelKey: "logistics_cost_amount" },
  { key: "notes", labelKey: "notes" },
];

export function RevisionRequestModal({
  isOpen,
  onClose,
  row,
  locale = "fa",
  onSuccess,
}: RevisionRequestModalProps) {
  const [selectedFields, setSelectedFields] = useState<RequestedFieldsEnum[]>([]);
  const [message, setMessage] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isConflict, setIsConflict] = useState<boolean>(false);
  const [isSuccess, setIsSuccess] = useState<boolean>(false);

  if (!isOpen || !row) return null;

  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.comparison.revisionModal;
  const isRtl = locale === "fa";

  const handleToggleField = (fieldKey: RequestedFieldsEnum) => {
    setSelectedFields((prev) =>
      prev.includes(fieldKey)
        ? prev.filter((k) => k !== fieldKey)
        : [...prev, fieldKey]
    );
    setErrorMessage(null);
  };

  const handleSubmit = async () => {
    if (selectedFields.length === 0) {
      setErrorMessage("لطفاً حداقل یک فیلد را برای بازنگری انتخاب کنید.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    setIsConflict(false);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/{offer_id}/revision-requests/",
        {
          params: {
            path: { offer_id: row.offer_id },
          },
          body: {
            expected_version: row.aggregate_version,
            base_offer_version: row.offer_version_id,
            requested_fields: selectedFields,
            message: message.trim(),
          },
        }
      );

      if (response.status === 409) {
        setIsConflict(true);
        setErrorMessage(t.conflictError);
        onSuccess(); // Refresh parent comparison to retrieve latest current submitted version
        return;
      }

      if (response.status === 201 || response.ok) {
        setIsSuccess(true);
        setTimeout(() => {
          setIsSuccess(false);
          onSuccess();
          onClose();
        }, 1200);
      } else {
        const errorDetail =
          error && typeof error === "object" && "detail" in error
            ? String(error.detail)
            : t.error;
        setErrorMessage(errorDetail);
      }
    } catch {
      setErrorMessage(t.error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 overflow-y-auto"
      dir={isRtl ? "rtl" : "ltr"}
      role="dialog"
      aria-modal="true"
      aria-labelledby="revision-modal-title"
    >
      <Card className="w-full max-w-lg shadow-xl max-h-[90vh] flex flex-col my-auto border-border">
        <CardHeader className="border-b pb-3 flex flex-row items-center justify-between shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-primary" />
              <CardTitle id="revision-modal-title" className="text-base font-semibold">
                {t.title}
              </CardTitle>
            </div>
            <CardDescription className="text-xs mt-1">
              {t.desc.replace("{version}", String(row.version_number))} ({row.offeror_name})
            </CardDescription>
          </div>
          <Button
            variant="outline"
            onClick={onClose}
            className="h-8 min-h-8 w-8 p-0 rounded-full border-transparent hover:bg-muted"
            disabled={isSubmitting}
            aria-label={t.cancel}
          >
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>

        <CardContent className="p-4 sm:p-6 overflow-y-auto space-y-4">
          {isSuccess && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 rounded-md text-xs flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{t.success}</span>
            </div>
          )}

          {errorMessage && (
            <div
              className={`p-3 rounded-md text-xs flex items-start gap-2 ${
                isConflict
                  ? "bg-amber-500/10 border border-amber-500/30 text-amber-800 dark:text-amber-300"
                  : "bg-destructive/10 border border-destructive/30 text-destructive"
              }`}
            >
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="leading-relaxed">{errorMessage}</div>
            </div>
          )}

          {/* Canonical Fields Selector */}
          <div className="space-y-2">
            <Label className="text-xs font-semibold block text-foreground">
              {t.fieldsLabel} <span className="text-destructive">*</span>
            </Label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto p-1 border rounded-md bg-muted/10">
              {CANONICAL_REVISION_FIELDS.map(({ key, labelKey }) => {
                const isSelected = selectedFields.includes(key);
                const labelText = t.fields[labelKey];

                return (
                  <label
                    key={key}
                    className={`flex items-center gap-2 p-2 rounded text-xs cursor-pointer select-none transition-colors border ${
                      isSelected
                        ? "bg-primary/10 border-primary text-foreground font-medium"
                        : "bg-card border-border text-muted-foreground hover:bg-accent/40"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                      checked={isSelected}
                      onChange={() => handleToggleField(key)}
                      disabled={isSubmitting || isSuccess}
                    />
                    <span>{labelText}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Revision Message */}
          <div className="space-y-1.5">
            <Label htmlFor="revision-message" className="text-xs font-medium text-foreground">
              {t.messageLabel}
            </Label>
            <Textarea
              id="revision-message"
              placeholder={t.messagePlaceholder}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={isSubmitting || isSuccess}
              rows={3}
              className="text-xs resize-none"
            />
          </div>
        </CardContent>

        <div className="border-t p-3 flex justify-end gap-2 shrink-0 bg-muted/20">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
            className="min-w-20 min-h-9 text-xs"
          >
            {t.cancel}
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || selectedFields.length === 0 || isSuccess}
            className="min-w-28 min-h-9 text-xs gap-1.5"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t.submitting}
              </>
            ) : (
              t.submit
            )}
          </Button>
        </div>
      </Card>
    </div>
  );
}

"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { CommoditySpecificationForm } from "@/components/commodity/commodity-specification-form";
import { CommoditySpecificationView } from "@/components/commodity/commodity-specification-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
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

type CommodityDefinition = components["schemas"]["CommodityDefinition"];
type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
type RFQVisibilityEnum = components["schemas"]["RFQVisibilityEnum"];
type DirectoryOrganization = components["schemas"]["DirectoryOrganization"];
type RFQInvitationResponse = components["schemas"]["RFQInvitationResponse"];

export interface RFQBuilderClientProps {
  locale?: EnabledLocale;
  initialRfqId?: string;
}

export function RFQBuilderClient({ locale = "fa", initialRfqId }: RFQBuilderClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.rfqBuilder;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // 1. Authorization & Role Checks
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");
  const isBuyerOrg =
    state.status === "authenticated" &&
    state.currentOrganization?.capabilities.includes("buyer");
  const isOwnerOrManager =
    state.status === "authenticated" &&
    (state.currentOrganization?.role === "owner" ||
      state.currentOrganization?.role === "manager");
  const isAuthorized = isOperatorOrAdmin || (isBuyerOrg && isOwnerOrManager);

  // 2. Organization / Session Invalidation Guard
  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const previousOrgIdRef = useRef<string | null>(null);

  // 3. Wizard Steps: 1..6
  const [step, setStep] = useState<number>(1);

  // 4. Draft Identifiers & Concurrency Version
  const [rfqId, setRfqId] = useState<string | null>(initialRfqId || null);
  const [rfqVersion, setRfqVersion] = useState<number | null>(null);

  // 5. Section 1: Product
  const [commodities, setCommodities] = useState<CommodityDefinition[]>([]);
  const [commodityId, setCommodityId] = useState<string>("");
  const [commodityCode, setCommodityCode] = useState<string>("");
  const [schemaVersionId, setSchemaVersionId] = useState<string>("");
  const [activeSchema, setActiveSchema] = useState<CommoditySchemaVersion | null>(null);
  const [quantity, setQuantity] = useState<string>("");
  const [unit, setUnit] = useState<string>("MT");
  const [specifications, setSpecifications] = useState<Record<string, unknown>>({});
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);
  const [specificationErrors, setSpecificationErrors] = useState<Record<string, string>>({});

  // 6. Section 2: Commercial
  const [currency, setCurrency] = useState<string>("USD");
  const [targetPrice, setTargetPrice] = useState<string>("");
  const [paymentTerms, setPaymentTerms] = useState<string>("");
  const [incoterm, setIncoterm] = useState<string>("");

  // 7. Section 3: Delivery
  const [origin, setOrigin] = useState<string>("");
  const [destination, setDestination] = useState<string>("");
  const [deliveryWindowStart, setDeliveryWindowStart] = useState<string>("");
  const [deliveryWindowEnd, setDeliveryWindowEnd] = useState<string>("");
  const [submissionDeadline, setSubmissionDeadline] = useState<string>("");

  // 8. Section 4: Quality & Inspection
  const [inspectionRequired, setInspectionRequired] = useState<boolean>(false);
  const [qualityNotes, setQualityNotes] = useState<string>("");
  const [notes, setNotes] = useState<string>("");

  // 9. Section 5: Participation & Visibility
  const [visibility, setVisibility] = useState<RFQVisibilityEnum>("private");
  const [directoryOrgs, setDirectoryOrgs] = useState<DirectoryOrganization[]>([]);
  const [invitations, setInvitations] = useState<RFQInvitationResponse[]>([]);
  const [directorySearch, setDirectorySearch] = useState<string>("");
  const [isInvitingId, setIsInvitingId] = useState<string | null>(null);
  const [invitationError, setInvitationError] = useState<string | null>(null);
  const [invitationSuccess, setInvitationSuccess] = useState<string | null>(null);

  // 10. General UI States
  const [isLoadingInitialDraft, setIsLoadingInitialDraft] = useState<boolean>(!!initialRfqId);
  const [isSavingDraft, setIsSavingDraft] = useState<boolean>(false);
  const [isPublishing, setIsPublishing] = useState<boolean>(false);
  const [publishSuccess, setPublishSuccess] = useState<boolean>(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [staleConflict, setStaleConflict] = useState<boolean>(false);

  // Clear state when switching active organization to prevent cross-org edits
  useEffect(() => {
    if (
      previousOrgIdRef.current &&
      previousOrgIdRef.current !== currentOrgId
    ) {
      queryClient.removeQueries({ queryKey: ["rfq"] });
      queryClient.removeQueries({ queryKey: ["rfq-invitations"] });
      setRfqId(null);
      setRfqVersion(null);
      setCommodityId("");
      setCommodityCode("");
      setSchemaVersionId("");
      setActiveSchema(null);
      setQuantity("");
      setUnit("MT");
      setSpecifications({});
      setTargetPrice("");
      setPaymentTerms("");
      setIncoterm("");
      setOrigin("");
      setDestination("");
      setDeliveryWindowStart("");
      setDeliveryWindowEnd("");
      setSubmissionDeadline("");
      setInspectionRequired(false);
      setQualityNotes("");
      setNotes("");
      setVisibility("private");
      setInvitations([]);
      setStep(1);
      setGeneralError(null);
      setStaleConflict(false);
    }
    if (currentOrgId) {
      previousOrgIdRef.current = currentOrgId;
    } else if (state.status === "unauthenticated") {
      previousOrgIdRef.current = null;
    }
  }, [currentOrgId, queryClient, state.status]);

  // Load available commodities on mount
  useEffect(() => {
    async function loadCommodities() {
      try {
        const { data, response } = await apiClient.GET("/api/commodities/");
        if (response.ok && Array.isArray(data)) {
          setCommodities(data);
        }
      } catch {
        // Handled silently
      }
    }
    void loadCommodities();
  }, []);

  // Fetch schema when commodity changes
  const loadCommoditySchema = useCallback(async (code: string) => {
    setIsLoadingSchema(true);
    try {
      const { data, response } = await apiClient.GET("/api/commodities/{code}/schema/", {
        params: { path: { code } },
      });
      if (response.ok && data) {
        setActiveSchema(data);
        setSchemaVersionId(data.id);
      }
    } catch {
      setActiveSchema(null);
    } finally {
      setIsLoadingSchema(false);
    }
  }, []);

  const handleCommoditySelect = (newCommodityId: string) => {
    const selected = commodities.find((c) => c.id === newCommodityId);
    if (!selected) return;
    setCommodityId(selected.id);
    setCommodityCode(selected.code);
    // Invariant: Changing commodity clears incompatible hidden specs
    setSpecifications({});
    setSpecificationErrors({});
    void loadCommoditySchema(selected.code);
  };

  // Load existing draft if initialRfqId provided
  useEffect(() => {
    if (!initialRfqId) return;
    async function loadDraft() {
      setIsLoadingInitialDraft(true);
      try {
        const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/", {
          params: { path: { rfq_id: initialRfqId! } },
        });
        if (response.ok && data) {
          setRfqId(data.id);
          setRfqVersion(data.version);
          setCommodityId(data.commodity_id);
          setCommodityCode(data.commodity_code);
          setSchemaVersionId(data.schema_version_id);
          setQuantity(data.quantity || "");
          setUnit(data.unit || "MT");
          setSpecifications((data.specifications as Record<string, unknown>) || {});
          setCurrency(data.currency || "USD");
          setTargetPrice(data.target_price || "");
          setPaymentTerms(data.payment_terms || "");
          setIncoterm(data.incoterm || "");
          setOrigin(data.origin || "");
          setDestination(data.destination || "");
          setDeliveryWindowStart(data.delivery_window_start || "");
          setDeliveryWindowEnd(data.delivery_window_end || "");
          setSubmissionDeadline(data.submission_deadline || "");
          setInspectionRequired(data.inspection_required ?? false);
          setQualityNotes(data.quality_notes || "");
          setNotes(data.notes || "");
          setVisibility(data.visibility);

          // Fetch schema for this commodity
          void loadCommoditySchema(data.commodity_code);
        }
      } catch {
        setGeneralError(t.loadDraftError);
      } finally {
        setIsLoadingInitialDraft(false);
      }
    }
    void loadDraft();
  }, [initialRfqId, loadCommoditySchema, t.loadDraftError]);


  // Load directory organizations for private invitation picker
  useEffect(() => {
    if (visibility !== "private" || (step !== 5 && step !== 6)) return;
    let isCancelled = false;
    async function fetchDirectoryAndInvitations() {
      try {
        const { data: dirData, response: dirRes } = await apiClient.GET("/api/organizations/directory/", {
          params: { query: { capability: ["supplier", "broker"] } },
        });
        if (!isCancelled && dirRes.ok && Array.isArray(dirData)) {
          setDirectoryOrgs(dirData);
        }
        if (rfqId) {
          const { data: invData, response: invRes } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/invitations/", {
            params: { path: { rfq_id: rfqId } },
          });
          if (!isCancelled && invRes.ok && Array.isArray(invData)) {
            setInvitations(invData);
          }
        }
      } catch {
        // Ignored
      }
    }
    void fetchDirectoryAndInvitations();
    return () => {
      isCancelled = true;
    };
  }, [visibility, step, rfqId]);

  // Helper to refetch authoritative draft upon 409 conflict
  const refetchAuthoritativeDraft = async (id: string) => {
    try {
      const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/", {
        params: { path: { rfq_id: id } },
      });
      if (response.ok && data) {
        setRfqVersion(data.version);
        setQuantity(data.quantity || "");
        setUnit(data.unit || "MT");
        setSpecifications((data.specifications as Record<string, unknown>) || {});
        setCurrency(data.currency || "USD");
        setTargetPrice(data.target_price || "");
        setPaymentTerms(data.payment_terms || "");
        setIncoterm(data.incoterm || "");
        setOrigin(data.origin || "");
        setDestination(data.destination || "");
        setDeliveryWindowStart(data.delivery_window_start || "");
        setDeliveryWindowEnd(data.delivery_window_end || "");
        setSubmissionDeadline(data.submission_deadline || "");
        setInspectionRequired(data.inspection_required ?? false);
        setQualityNotes(data.quality_notes || "");
        setNotes(data.notes || "");
        setVisibility(data.visibility);
      }
    } catch {
      // Ignored
    }
  };

  // Structured error mapper
  const handleBackendError = (errPayload: unknown) => {
    if (!errPayload || typeof errPayload !== "object") return;
    const p = errPayload as Record<string, unknown>;

    if (p.detail && typeof p.detail === "string") {
      setGeneralError(p.detail);
    }

    // Dynamic field-level specification errors
    if (Array.isArray(p.errors)) {
      const specMap: Record<string, string> = {};
      for (const item of p.errors) {
        if (item && typeof item === "object" && "field" in item && "message" in item) {
          specMap[String(item.field)] = String(item.message);
        }
      }
      setSpecificationErrors(specMap);
    }

    // Static form field errors
    const fMap: Record<string, string> = {};
    for (const [key, val] of Object.entries(p)) {
      if (key !== "detail" && key !== "errors") {
        fMap[key] = Array.isArray(val) ? val.join(" ") : String(val);
      }
    }
    if (Object.keys(fMap).length > 0) {
      setFieldErrors(fMap);
    }
  };

  // Save Draft action
  const handleSaveDraft = async (): Promise<boolean> => {
    setIsSavingDraft(true);
    setGeneralError(null);
    setStaleConflict(false);
    setSpecificationErrors({});
    setFieldErrors({});

    try {
      if (!rfqId) {
        // Creation validation
        if (!commodityId || !schemaVersionId) {
          setGeneralError(t.product.selectCommodityPrompt);
          return false;
        }
        if (!quantity || Number(quantity) <= 0) {
          setFieldErrors({ quantity: t.errors.positiveQuantity });
          return false;
        }

        const { data, response, error } = await apiClient.POST("/api/trade-hub/rfqs/", {
          body: {
            commodity_id: commodityId,
            schema_version_id: schemaVersionId,
            quantity,
            unit: unit || "MT",
            specifications,
            target_price: targetPrice ? targetPrice : null,
            currency: currency || "USD",
            payment_terms: paymentTerms || "",
            incoterm: incoterm || "",
            origin: origin || "",
            destination: destination || "",
            delivery_window_start: deliveryWindowStart || null,
            delivery_window_end: deliveryWindowEnd || null,
            submission_deadline: submissionDeadline ? new Date(submissionDeadline).toISOString() : null,
            inspection_required: inspectionRequired,
            quality_notes: qualityNotes || "",
            notes: notes || "",
            visibility,
          },
        });

        if (response.status === 201 && data) {
          setRfqId(data.id);
          setRfqVersion(data.version);
          return true;
        }

        handleBackendError(error || data);
        return false;
      } else {
        // Subsequent update using expected_version
        const { data, response, error } = await apiClient.PATCH(
          "/api/trade-hub/rfqs/{rfq_id}/",
          {
            params: { path: { rfq_id: rfqId } },
            body: {
              expected_version: rfqVersion ?? 1,
              commodity_id: commodityId || undefined,
              schema_version_id: schemaVersionId || undefined,
              quantity: quantity || undefined,
              unit: unit || undefined,
              specifications,
              target_price: targetPrice ? targetPrice : null,
              currency: currency || "USD",
              payment_terms: paymentTerms || "",
              incoterm: incoterm || "",
              origin: origin || "",
              destination: destination || "",
              delivery_window_start: deliveryWindowStart || null,
              delivery_window_end: deliveryWindowEnd || null,
              submission_deadline: submissionDeadline ? new Date(submissionDeadline).toISOString() : null,
              inspection_required: inspectionRequired,
              quality_notes: qualityNotes || "",
              notes: notes || "",
              visibility,
            },
          }
        );

        if (response.ok && data) {
          setRfqVersion(data.version);
          return true;
        }

        if (response.status === 409) {
          setStaleConflict(true);
          setGeneralError(messages.rfqBuilder.conflicts.staleDescription);
          await refetchAuthoritativeDraft(rfqId);
          return false;
        }

        handleBackendError(error || data);
        return false;
      }
    } finally {
      setIsSavingDraft(false);
    }
  };

  // Step advancement
  const handleNextStep = async () => {
    // If on Step 1, create or validate draft first
    if (step === 1) {
      const saved = await handleSaveDraft();
      if (!saved) return;
    } else {
      // Save state before advancing
      if (rfqId) {
        const saved = await handleSaveDraft();
        if (!saved) return;
      }
    }
    setStep((s) => Math.min(s + 1, 6));
  };

  const handlePrevStep = () => {
    setStep((s) => Math.max(s - 1, 1));
  };

  // Participant Invitation
  const handleInviteOrganization = async (targetOrgId: string) => {
    if (!rfqId) {
      const saved = await handleSaveDraft();
      if (!saved) {
        setInvitationError(t.visibility.saveDraftFirstPrompt);
        return;
      }
    }
    if (!rfqId) return;

    setIsInvitingId(targetOrgId);
    setInvitationError(null);
    setInvitationSuccess(null);

    try {
      const { data, response, error } = await apiClient.POST(
        "/api/trade-hub/rfqs/{rfq_id}/invitations/",
        {
          params: { path: { rfq_id: rfqId } },
          body: { organization_id: targetOrgId },
        }
      );

      if (response.status === 201 && data) {
        setInvitations((prev) => [...prev, data]);
        setInvitationSuccess(t.visibility.inviteSuccess);
        return;
      }

      if (response.status === 409) {
        setInvitationError(t.visibility.duplicateInviteError);
        return;
      }

      const err = error as Record<string, unknown> | undefined;
      setInvitationError(err?.detail ? String(err.detail) : t.visibility.inviteError);
    } finally {
      setIsInvitingId(null);
    }
  };

  // Publish RFQ Action
  const handlePublish = async () => {
    if (!rfqId) {
      const saved = await handleSaveDraft();
      if (!saved) return;
    }
    if (!rfqId || rfqVersion === null) return;

    setIsPublishing(true);
    setGeneralError(null);
    setStaleConflict(false);

    try {
      const { data, response, error } = await apiClient.POST(
        "/api/trade-hub/rfqs/{rfq_id}/publish/",
        {
          params: { path: { rfq_id: rfqId } },
          body: { expected_version: rfqVersion },
        }
      );

      if (response.ok && data) {
        setPublishSuccess(true);
        setRfqVersion(data.version);
        // Navigate to the best existing post-publish route
        setTimeout(() => {
          router.push(`/${locale}`);
        }, 1500);
        return;
      }

      if (response.status === 409) {
        setStaleConflict(true);
        setGeneralError(messages.rfqBuilder.conflicts.staleDescription);
        await refetchAuthoritativeDraft(rfqId);
        return;
      }

      handleBackendError(error || data);
    } finally {
      setIsPublishing(false);
    }
  };

  // 11. Render Guard States
  if (state.status === "loading" || isLoadingInitialDraft) {
    return (
      <div className="flex h-64 items-center justify-center" dir={isRtl ? "rtl" : "ltr"}>
        <p className="text-muted-foreground">{isLoadingInitialDraft ? t.loadingDraft : t.loadingSession}</p>
      </div>
    );
  }

  if (!isAuthorized) {
    return (
      <Card className="border-destructive/40 shadow-none" dir={isRtl ? "rtl" : "ltr"}>
        <CardHeader>
          <CardTitle className="text-destructive">{t.unauthorizedTitle}</CardTitle>
          <CardDescription>{t.unauthorizedDescription}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // Filtered organizations for invitation
  const invitedOrgIds = new Set(invitations.map((i) => i.organization.id));
  const filteredDirectoryOrgs = directoryOrgs.filter((org) => {
    if (currentOrgId && org.id === currentOrgId) return false;
    if (!directorySearch.trim()) return true;
    return org.name.toLowerCase().includes(directorySearch.toLowerCase());
  });

  return (
    <div className="space-y-8" dir={isRtl ? "rtl" : "ltr"}>
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t.subtitle}</p>
      </div>

      {/* Version and Draft Status Bar */}
      {rfqId && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-md border bg-muted/40 px-4 py-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-muted-foreground">{t.preview.rfqIdLabel}</span>
            <span className="font-mono">{rfqId}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-muted-foreground">{t.preview.versionLabel}</span>
            <Badge variant="outline">{rfqVersion ?? 1}</Badge>
          </div>
        </div>
      )}

      {/* Global Alerts: Stale Version / General Errors / Success */}
      {staleConflict && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-md border border-amber-500/50 bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-300"
        >
          <h4 className="font-semibold">{t.conflicts.staleTitle}</h4>
          <p className="mt-1 leading-relaxed">{t.conflicts.staleDescription}</p>
        </div>
      )}

      {generalError && !staleConflict && (
        <div
          role="alert"
          aria-live="assertive"
          className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
        >
          <p>{generalError}</p>
        </div>
      )}

      {publishSuccess && (
        <div
          role="alert"
          className="rounded-md border border-emerald-500/50 bg-emerald-500/10 p-4 text-sm text-emerald-800 dark:text-emerald-300"
        >
          <p className="font-semibold">{t.preview.publishSuccess}</p>
        </div>
      )}

      {/* Stepper Navigation Indicator */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" aria-label="مراحل ایجاد استعلام">
        {[
          { num: 1, title: t.steps.product },
          { num: 2, title: t.steps.commercial },
          { num: 3, title: t.steps.delivery },
          { num: 4, title: t.steps.quality },
          { num: 5, title: t.steps.visibility },
          { num: 6, title: t.steps.preview },
        ].map((item) => {
          const isActive = step === item.num;
          return (
            <button
              key={item.num}
              type="button"
              onClick={() => setStep(item.num)}
              className={`flex flex-col items-center justify-center rounded-md border p-3 text-center transition-colors ${
                isActive
                  ? "border-primary bg-primary/10 text-primary font-semibold"
                  : "border-border bg-background hover:bg-accent/40 cursor-pointer text-foreground"
              }`}
            >
              <span className="text-xs font-bold mb-1">{item.num}</span>
              <span className="text-xs">{item.title}</span>
            </button>
          );
        })}
      </div>

      {/* Section 1: Product */}
      {step === 1 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>{t.steps.product}</CardTitle>
            <CardDescription>{t.product.specificationsTitle}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="rfq-commodity-select" className="flex items-center gap-1">
                  <span>{t.product.commodityLabel}</span>
                  <span className="text-destructive">*</span>
                </Label>
                <Select
                  dir={isRtl ? "rtl" : "ltr"}
                  value={commodityId}
                  onValueChange={handleCommoditySelect}
                >
                  <SelectTrigger id="rfq-commodity-select">
                    <SelectValue placeholder={t.product.commodityPlaceholder} />
                  </SelectTrigger>
                  <SelectContent>
                    {commodities.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {locale === "fa" ? c.name_fa : c.name_en} ({c.code})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="rfq-quantity" className="flex items-center gap-1">
                    <span>{t.product.quantityLabel}</span>
                    <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="rfq-quantity"
                    type="number"
                    step="any"
                    min="0.001"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    placeholder={t.product.quantityPlaceholder}
                    aria-invalid={!!fieldErrors.quantity}
                    aria-describedby={fieldErrors.quantity ? "rfq-quantity-error" : undefined}
                  />
                  {fieldErrors.quantity && (
                    <p id="rfq-quantity-error" role="alert" className="text-xs text-destructive">
                      {fieldErrors.quantity}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="rfq-unit">{t.product.unitLabel}</Label>
                  <Input
                    id="rfq-unit"
                    type="text"
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder={t.product.unitPlaceholder}
                  />
                </div>
              </div>
            </div>

            {/* Dynamic Commodity Specifications */}
            <div className="border-t pt-6">
              <h3 className="text-base font-semibold mb-4">{t.product.specificationsTitle}</h3>
              {isLoadingSchema && (
                <p className="text-sm text-muted-foreground">{t.product.loadingSchema}</p>
              )}
              {!isLoadingSchema && !activeSchema && (
                <p className="text-sm text-muted-foreground">{t.product.selectCommodityPrompt}</p>
              )}
              {!isLoadingSchema && activeSchema && (
                <CommoditySpecificationForm
                  schema={activeSchema}
                  value={specifications}
                  onChange={setSpecifications}
                  locale={locale}
                  errors={specificationErrors}
                />
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Section 2: Commercial */}
      {step === 2 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>{t.steps.commercial}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="rfq-currency">{t.commercial.currencyLabel}</Label>
                <Input
                  id="rfq-currency"
                  type="text"
                  maxLength={3}
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  placeholder={t.commercial.currencyPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-target-price">{t.commercial.targetPriceLabel}</Label>
                <Input
                  id="rfq-target-price"
                  type="number"
                  step="0.01"
                  min="0"
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(e.target.value)}
                  placeholder={t.commercial.targetPricePlaceholder}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-payment-terms">{t.commercial.paymentTermsLabel}</Label>
                <Input
                  id="rfq-payment-terms"
                  type="text"
                  value={paymentTerms}
                  onChange={(e) => setPaymentTerms(e.target.value)}
                  placeholder={t.commercial.paymentTermsPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-incoterm">{t.commercial.incotermLabel}</Label>
                <Input
                  id="rfq-incoterm"
                  type="text"
                  maxLength={10}
                  value={incoterm}
                  onChange={(e) => setIncoterm(e.target.value.toUpperCase())}
                  placeholder={t.commercial.incotermPlaceholder}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Section 3: Delivery */}
      {step === 3 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>{t.steps.delivery}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="rfq-origin">{t.delivery.originLabel}</Label>
                <Input
                  id="rfq-origin"
                  type="text"
                  value={origin}
                  onChange={(e) => setOrigin(e.target.value)}
                  placeholder={t.delivery.originPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-destination">{t.delivery.destinationLabel}</Label>
                <Input
                  id="rfq-destination"
                  type="text"
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                  placeholder={t.delivery.destinationPlaceholder}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-delivery-start">{t.delivery.deliveryWindowStartLabel}</Label>
                <Input
                  id="rfq-delivery-start"
                  type="date"
                  value={deliveryWindowStart}
                  onChange={(e) => setDeliveryWindowStart(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="rfq-delivery-end">{t.delivery.deliveryWindowEndLabel}</Label>
                <Input
                  id="rfq-delivery-end"
                  type="date"
                  value={deliveryWindowEnd}
                  onChange={(e) => setDeliveryWindowEnd(e.target.value)}
                />
              </div>

              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="rfq-submission-deadline">{t.delivery.submissionDeadlineLabel}</Label>
                <Input
                  id="rfq-submission-deadline"
                  type="datetime-local"
                  value={submissionDeadline}
                  onChange={(e) => setSubmissionDeadline(e.target.value)}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Section 4: Quality & Inspection */}
      {step === 4 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>{t.steps.quality}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div className="space-y-0.5">
                <Label htmlFor="rfq-inspection" className="text-base">
                  {t.quality.inspectionRequiredLabel}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t.quality.inspectionRequiredDescription}
                </p>
              </div>
              <Switch
                id="rfq-inspection"
                checked={inspectionRequired}
                onCheckedChange={setInspectionRequired}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rfq-quality-notes">{t.quality.qualityNotesLabel}</Label>
              <Textarea
                id="rfq-quality-notes"
                value={qualityNotes}
                onChange={(e) => setQualityNotes(e.target.value)}
                placeholder={t.quality.qualityNotesPlaceholder}
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rfq-general-notes">{t.quality.notesLabel}</Label>
              <Textarea
                id="rfq-general-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t.quality.notesPlaceholder}
                rows={3}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Section 5: Participation & Visibility */}
      {step === 5 && (
        <Card className="shadow-none">
          <CardHeader>
            <CardTitle>{t.steps.visibility}</CardTitle>
            <CardDescription>{t.visibility.tierLabel}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Visibility Tiers */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {[
                { key: "public" as RFQVisibilityEnum, label: t.visibility.public, desc: t.visibility.publicDesc },
                { key: "network" as RFQVisibilityEnum, label: t.visibility.network, desc: t.visibility.networkDesc },
                { key: "private" as RFQVisibilityEnum, label: t.visibility.private, desc: t.visibility.privateDesc },
              ].map((tier) => (
                <div
                  key={tier.key}
                  onClick={() => setVisibility(tier.key)}
                  className={`cursor-pointer rounded-lg border p-4 transition-all ${
                    visibility === tier.key
                      ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-sm">{tier.label}</span>
                    <input
                      type="radio"
                      name="rfq-visibility"
                      checked={visibility === tier.key}
                      onChange={() => setVisibility(tier.key)}
                      className="size-4 text-primary"
                    />
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{tier.desc}</p>
                </div>
              ))}
            </div>

            {/* Private Visibility Counterparty Invitations */}
            {visibility === "private" && (
              <div className="space-y-6 border-t pt-6">
                <div>
                  <h3 className="text-base font-semibold">{t.visibility.invitationsTitle}</h3>
                  <p className="text-xs text-muted-foreground">{t.visibility.invitationsDesc}</p>
                </div>

                {invitationError && (
                  <div role="alert" className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
                    {invitationError}
                  </div>
                )}
                {invitationSuccess && (
                  <div role="alert" className="rounded-md border border-emerald-500/50 bg-emerald-500/10 p-3 text-xs text-emerald-800 dark:text-emerald-300">
                    {invitationSuccess}
                  </div>
                )}

                {/* Directory Search */}
                <div className="flex gap-2">
                  <Input
                    type="search"
                    placeholder={t.visibility.searchPlaceholder}
                    value={directorySearch}
                    onChange={(e) => setDirectorySearch(e.target.value)}
                    className="max-w-md"
                  />
                </div>

                {/* Available Counterparties List */}
                <div className="rounded-md border overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>نام سازمان</TableHead>
                        <TableHead>قابلیت‌ها</TableHead>
                        <TableHead>کشور</TableHead>
                        <TableHead className="text-end">عملیات</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredDirectoryOrgs.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} className="text-center text-muted-foreground py-6">
                            {t.visibility.noOrganizationsFound}
                          </TableCell>
                        </TableRow>
                      ) : (
                        filteredDirectoryOrgs.slice(0, 10).map((org) => {
                          const isInvited = invitedOrgIds.has(org.id);
                          return (
                            <TableRow key={org.id}>
                              <TableCell className="font-medium">{org.name}</TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1">
                                  {org.capabilities.map((cap) => (
                                    <Badge key={cap} variant="secondary" className="text-xs">
                                      {cap === "supplier" ? "تأمین‌کننده" : cap === "broker" ? "کارگزار" : cap}
                                    </Badge>
                                  ))}
                                </div>
                              </TableCell>
                              <TableCell>{org.country}</TableCell>
                              <TableCell className="text-end">
                                {isInvited ? (
                                  <Badge variant="outline" className="text-muted-foreground">
                                    {t.visibility.alreadyInvited}
                                  </Badge>
                                ) : (
                                  <Button
                                    variant="outline"
                                    className="min-h-8 px-3 text-xs"
                                    disabled={isInvitingId === org.id}
                                    onClick={() => handleInviteOrganization(org.id)}
                                  >
                                    {isInvitingId === org.id ? t.actions.inviting : t.actions.invite}
                                  </Button>
                                )}
                              </TableCell>
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>
                </div>

                {/* Invited Participants List */}
                {invitations.length > 0 && (
                  <div className="space-y-3 pt-4">
                    <h4 className="text-sm font-semibold">{t.visibility.invitedListTitle}</h4>
                    <div className="rounded-md border overflow-hidden">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>نام سازمان</TableHead>
                            <TableHead>وضعیت دعوت</TableHead>
                            <TableHead>تاریخ دعوت</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {invitations.map((inv) => (
                            <TableRow key={inv.id}>
                              <TableCell className="font-medium">{inv.organization.name}</TableCell>
                              <TableCell>
                                <Badge variant="secondary" className="text-xs">
                                  {inv.status}
                                </Badge>
                              </TableCell>
                              <TableCell className="text-xs text-muted-foreground">
                                {new Date(inv.created_at).toLocaleDateString("fa-IR")}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Section 6: Preview & Publish */}
      {step === 6 && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle>{t.preview.title}</CardTitle>
              <CardDescription>{t.preview.description}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-8">
              {/* Product Specifications Summary */}
              <div className="space-y-4">
                <h3 className="text-base font-semibold border-b pb-2">{t.preview.productSummary}</h3>
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.product.commodityLabel}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {commodities.find((c) => c.id === commodityId)?.name_fa || commodityCode}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.product.quantityLabel}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {quantity} {unit}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.product.schemaVersion}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {activeSchema ? `نسخه ${activeSchema.version}` : t.preview.notSpecified}
                    </dd>
                  </div>
                </dl>

                {activeSchema && (
                  <div className="mt-4 rounded-md border p-4 bg-muted/10">
                    <CommoditySpecificationView
                      schema={activeSchema}
                      value={specifications}
                      locale={locale}
                    />
                  </div>
                )}
              </div>

              {/* Commercial Terms Summary */}
              <div className="space-y-4">
                <h3 className="text-base font-semibold border-b pb-2">{t.preview.commercialSummary}</h3>
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-4">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.commercial.currencyLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{currency}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.commercial.targetPriceLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{targetPrice || t.preview.notSpecified}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.commercial.paymentTermsLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{paymentTerms || t.preview.notSpecified}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.commercial.incotermLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{incoterm || t.preview.notSpecified}</dd>
                  </div>
                </dl>
              </div>

              {/* Delivery Terms Summary */}
              <div className="space-y-4">
                <h3 className="text-base font-semibold border-b pb-2">{t.preview.deliverySummary}</h3>
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.delivery.originLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{origin || t.preview.notSpecified}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.delivery.destinationLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{destination || t.preview.notSpecified}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">بازه تحویل</dt>
                    <dd className="text-sm font-medium mt-1">
                      {deliveryWindowStart || deliveryWindowEnd
                        ? `${deliveryWindowStart || "—"} تا ${deliveryWindowEnd || "—"}`
                        : t.preview.notSpecified}
                    </dd>
                  </div>
                </dl>
              </div>

              {/* Quality & Visibility Summary */}
              <div className="space-y-4">
                <h3 className="text-base font-semibold border-b pb-2">{t.preview.qualitySummary}</h3>
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.quality.inspectionRequiredLabel}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {inspectionRequired ? t.preview.yes : t.preview.no}
                    </dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-muted-foreground">{t.quality.qualityNotesLabel}</dt>
                    <dd className="text-sm font-medium mt-1">{qualityNotes || t.preview.notSpecified}</dd>
                  </div>
                </dl>
              </div>

              <div className="space-y-4">
                <h3 className="text-base font-semibold border-b pb-2">{t.preview.visibilitySummary}</h3>
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.visibility.tierLabel}</dt>
                    <dd className="text-sm font-medium mt-1">
                      <Badge variant="outline">
                        {visibility === "public"
                          ? t.visibility.public
                          : visibility === "network"
                          ? t.visibility.network
                          : t.visibility.private}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">تعداد مخاطبان دعوت‌شده</dt>
                    <dd className="text-sm font-medium mt-1">{invitations.length}</dd>
                  </div>
                </dl>
              </div>
            </CardContent>
          </Card>

          {/* Warning Banner */}
          <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-4 text-xs text-amber-800 dark:text-amber-300">
            {t.preview.publishWarning}
          </div>
        </div>
      )}

      {/* Footer Actions / Navigation Bar */}
      <div className="flex items-center justify-between border-t pt-6">
        <div>
          {step > 1 && (
            <Button type="button" variant="outline" onClick={handlePrevStep}>
              {t.actions.prev}
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={isSavingDraft}
            onClick={handleSaveDraft}
          >
            {isSavingDraft ? t.actions.saving : t.actions.saveDraft}
          </Button>

          {step < 6 ? (
            <Button type="button" onClick={handleNextStep}>
              {t.actions.next}
            </Button>
          ) : (
            <Button
              type="button"
              disabled={isPublishing || publishSuccess}
              onClick={handlePublish}
              className="bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {isPublishing ? t.actions.publishing : t.actions.publish}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

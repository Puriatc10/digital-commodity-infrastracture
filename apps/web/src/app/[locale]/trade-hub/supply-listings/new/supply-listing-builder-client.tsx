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
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Layers,
  Loader2,
  Package,
  Save,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

type CommodityDefinition = components["schemas"]["CommodityDefinition"];
type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
type RFQVisibilityEnum = components["schemas"]["RFQVisibilityEnum"];

export interface SupplyListingBuilderClientProps {
  locale?: EnabledLocale;
  initialListingId?: string;
}

export function SupplyListingBuilderClient({
  locale = "fa",
  initialListingId,
}: SupplyListingBuilderClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.supplyListingBuilder;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // 1. Authorization & Role Checks
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");
  const isSupplierOrg =
    state.status === "authenticated" &&
    Boolean(state.currentOrganization?.capabilities.includes("supplier"));
  const isOwnerOrManager =
    state.status === "authenticated" &&
    (state.currentOrganization?.role === "owner" ||
      state.currentOrganization?.role === "manager");
  const isAuthorized = isOperatorOrAdmin || (isSupplierOrg && isOwnerOrManager);

  // 2. Organization / Session Invalidation Guard
  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const previousOrgIdRef = useRef<string | null>(null);

  // 3. Wizard Steps: 1..4 (Product, Commercial & Delivery, Visibility, Preview & Activate)
  const [step, setStep] = useState<number>(1);

  // 4. Draft Identifiers & Concurrency Version
  const [listingId, setListingId] = useState<string | null>(initialListingId || null);
  const [listingVersion, setListingVersion] = useState<number | null>(null);

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

  // 6. Section 2: Commercial & Availability
  const [indicativePrice, setIndicativePrice] = useState<string>("");
  const [currency, setCurrency] = useState<string>("USD");
  const [paymentTerms, setPaymentTerms] = useState<string>("");
  const [incoterm, setIncoterm] = useState<string>("");
  const [origin, setOrigin] = useState<string>("");
  const [destination, setDestination] = useState<string>("");
  const [availabilityWindowStart, setAvailabilityWindowStart] = useState<string>("");
  const [availabilityWindowEnd, setAvailabilityWindowEnd] = useState<string>("");
  const [qualityNotes, setQualityNotes] = useState<string>("");
  const [notes, setNotes] = useState<string>("");

  // 7. Section 3: Visibility
  const [visibility, setVisibility] = useState<RFQVisibilityEnum>("public");

  // 8. General UI States
  const [isLoadingInitialDraft, setIsLoadingInitialDraft] = useState<boolean>(!!initialListingId);
  const [isSavingDraft, setIsSavingDraft] = useState<boolean>(false);
  const [isActivating, setIsActivating] = useState<boolean>(false);
  const [savedNotice, setSavedNotice] = useState<boolean>(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [staleConflict, setStaleConflict] = useState<boolean>(false);

  // Clear state when switching active organization to prevent cross-org leaks
  useEffect(() => {
    if (previousOrgIdRef.current && previousOrgIdRef.current !== currentOrgId) {
      queryClient.removeQueries({ queryKey: ["supply-listing"] });
      queryClient.removeQueries({ queryKey: ["supply-listings"] });
      setListingId(null);
      setListingVersion(null);
      setCommodityId("");
      setCommodityCode("");
      setSchemaVersionId("");
      setActiveSchema(null);
      setQuantity("");
      setUnit("MT");
      setSpecifications({});
      setIndicativePrice("");
      setPaymentTerms("");
      setIncoterm("");
      setOrigin("");
      setDestination("");
      setAvailabilityWindowStart("");
      setAvailabilityWindowEnd("");
      setQualityNotes("");
      setNotes("");
      setVisibility("public");
      setStep(1);
      setGeneralError(null);
      setStaleConflict(false);
      setFieldErrors({});
      setSpecificationErrors({});
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

  // Exact historical schema fetch
  const loadExactSchemaById = useCallback(async (schemaId: string) => {
    setIsLoadingSchema(true);
    try {
      const { data, response } = await apiClient.GET("/api/commodity-schemas/{id}/", {
        params: { path: { id: schemaId } },
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

  // Load existing draft if initialListingId provided
  useEffect(() => {
    if (!initialListingId) return;
    async function loadDraft() {
      setIsLoadingInitialDraft(true);
      try {
        const { data, response } = await apiClient.GET(
          "/api/trade-hub/supply-listings/{listing_id}/",
          {
            params: { path: { listing_id: initialListingId! } },
          }
        );
        if (response.ok && data) {
          setListingId(data.id);
          setListingVersion(data.version);
          setCommodityId(data.commodity_id);
          setCommodityCode(data.commodity_code);
          setSchemaVersionId(data.schema_version_id);
          setQuantity(data.quantity || "");
          setUnit(data.unit || "MT");
          setSpecifications((data.specifications as Record<string, unknown>) || {});
          setIndicativePrice(data.indicative_price || "");
          setCurrency(data.currency || "USD");
          setPaymentTerms(data.payment_terms || "");
          setIncoterm(data.incoterm || "");
          setOrigin(data.origin || "");
          setDestination(data.destination || "");
          setAvailabilityWindowStart(data.availability_window_start || "");
          setAvailabilityWindowEnd(data.availability_window_end || "");
          setQualityNotes(data.quality_notes || "");
          if ("notes" in data && typeof data.notes === "string") {
            setNotes(data.notes);
          }
          setVisibility(data.visibility);

          // Invariant: Exact Schema Binding: Historical listing uses stored schema version
          void loadExactSchemaById(data.schema_version_id);
        }
      } catch {
        setGeneralError(t.loadDraftError);
      } finally {
        setIsLoadingInitialDraft(false);
      }
    }
    void loadDraft();
  }, [initialListingId, loadExactSchemaById, t.loadDraftError]);

  // Helper to refetch authoritative draft upon 409 conflict
  const refetchAuthoritativeDraft = async (id: string) => {
    try {
      const { data, response } = await apiClient.GET(
        "/api/trade-hub/supply-listings/{listing_id}/",
        {
          params: { path: { listing_id: id } },
        }
      );
      if (response.ok && data) {
        setListingVersion(data.version);
        setQuantity(data.quantity || "");
        setUnit(data.unit || "MT");
        setSpecifications((data.specifications as Record<string, unknown>) || {});
        setIndicativePrice(data.indicative_price || "");
        setCurrency(data.currency || "USD");
        setPaymentTerms(data.payment_terms || "");
        setIncoterm(data.incoterm || "");
        setOrigin(data.origin || "");
        setDestination(data.destination || "");
        setAvailabilityWindowStart(data.availability_window_start || "");
        setAvailabilityWindowEnd(data.availability_window_end || "");
        setQualityNotes(data.quality_notes || "");
        if ("notes" in data && typeof data.notes === "string") {
          setNotes(data.notes);
        }
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
      if (!listingId) {
        // Creation validation
        if (!commodityId || !schemaVersionId) {
          setGeneralError(t.product.selectCommodityPrompt);
          return false;
        }
        if (!quantity || Number(quantity) <= 0) {
          setFieldErrors({ quantity: t.errors.positiveQuantity });
          return false;
        }

        const { data, response, error } = await apiClient.POST(
          "/api/trade-hub/supply-listings/",
          {
            body: {
              commodity_id: commodityId,
              schema_version_id: schemaVersionId,
              quantity,
              unit: unit || "MT",
              specifications,
              indicative_price: indicativePrice ? indicativePrice : null,
              currency: currency || "USD",
              payment_terms: paymentTerms || "",
              incoterm: incoterm || "",
              origin: origin || "",
              destination: destination || "",
              availability_window_start: availabilityWindowStart || null,
              availability_window_end: availabilityWindowEnd || null,
              quality_notes: qualityNotes || "",
              notes: notes || "",
              visibility,
            },
          }
        );

        if (response.status === 201 && data) {
          setListingId(data.id);
          setListingVersion(data.version);
          setSavedNotice(true);
          setTimeout(() => setSavedNotice(false), 3000);
          return true;
        }

        handleBackendError(error || data);
        return false;
      } else {
        // Subsequent update using expected_version
        const { data, response, error } = await apiClient.PATCH(
          "/api/trade-hub/supply-listings/{listing_id}/",
          {
            params: { path: { listing_id: listingId } },
            body: {
              expected_version: listingVersion ?? 1,
              commodity_id: commodityId || undefined,
              schema_version_id: schemaVersionId || undefined,
              quantity: quantity || undefined,
              unit: unit || undefined,
              specifications,
              indicative_price: indicativePrice ? indicativePrice : null,
              currency: currency || "USD",
              payment_terms: paymentTerms || "",
              incoterm: incoterm || "",
              origin: origin || "",
              destination: destination || "",
              availability_window_start: availabilityWindowStart || null,
              availability_window_end: availabilityWindowEnd || null,
              quality_notes: qualityNotes || "",
              notes: notes || "",
              visibility,
            },
          }
        );

        if (response.ok && data) {
          setListingVersion(data.version);
          setSavedNotice(true);
          setTimeout(() => setSavedNotice(false), 3000);
          return true;
        }

        if (response.status === 409) {
          setStaleConflict(true);
          setGeneralError(t.conflicts.staleDescription);
          await refetchAuthoritativeDraft(listingId);
          return false;
        }

        handleBackendError(error || data);
        return false;
      }
    } finally {
      setIsSavingDraft(false);
    }
  };

  // Explicit Activation Action
  const handleActivate = async () => {
    if (!listingId) {
      const saved = await handleSaveDraft();
      if (!saved) return;
    }

    setIsActivating(true);
    setGeneralError(null);
    setStaleConflict(false);
    setSpecificationErrors({});
    setFieldErrors({});

    try {
      const { data, response, error } = await apiClient.POST(
        "/api/trade-hub/supply-listings/{listing_id}/activate/",
        {
          params: { path: { listing_id: listingId! } },
          body: {
            expected_version: listingVersion ?? 1,
          },
        }
      );

      if (response.ok && data) {
        setListingVersion(data.version);
        router.push(`/${locale}/trade-hub/supply-listings/${data.id}`);
        return;
      }

      if (response.status === 409) {
        setStaleConflict(true);
        setGeneralError(t.conflicts.staleDescription);
        await refetchAuthoritativeDraft(listingId!);
        return;
      }

      handleBackendError(error || data);
    } finally {
      setIsActivating(false);
    }
  };

  // Step Validation Guard
  const validateCurrentStep = (): boolean => {
    setFieldErrors({});
    setGeneralError(null);

    if (step === 1) {
      if (!commodityId) {
        setGeneralError(t.product.selectCommodityPrompt);
        return false;
      }
      if (!quantity || Number(quantity) <= 0) {
        setFieldErrors({ quantity: t.errors.positiveQuantity });
        return false;
      }
    }

    if (step === 2) {
      if (
        availabilityWindowStart &&
        availabilityWindowEnd &&
        new Date(availabilityWindowStart) > new Date(availabilityWindowEnd)
      ) {
        setFieldErrors({ availabilityWindowEnd: t.errors.availabilityWindowInvalid });
        return false;
      }
    }

    return true;
  };

  const handleNextStep = async () => {
    if (!validateCurrentStep()) return;

    // Auto-save draft on step progression
    if (step === 1 || step === 2 || step === 3) {
      const saved = await handleSaveDraft();
      if (!saved) return;
    }

    setStep((s) => Math.min(s + 1, 4));
  };

  const handlePrevStep = () => {
    setStep((s) => Math.max(s - 1, 1));
  };

  // Auth & Session Loading Screen
  if (state.status === "loading" || isLoadingInitialDraft) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-4 text-muted-foreground" dir={isRtl ? "rtl" : "ltr"}>
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm font-medium">{t.loadingSession}</p>
      </div>
    );
  }

  // Authorization Check Screen
  if (!isAuthorized) {
    return (
      <div className="mx-auto my-12 max-w-xl" dir={isRtl ? "rtl" : "ltr"}>
        <Card className="border-destructive/30 bg-destructive/5 shadow-md">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <ShieldAlert className="h-6 w-6" />
            </div>
            <CardTitle className="text-xl text-destructive">{t.unauthorizedTitle}</CardTitle>
            <CardDescription className="mt-2 text-foreground/80">
              {t.unauthorizedDescription}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-6">
            <Button variant="outline" onClick={() => router.push(`/${locale}/trade-hub`)}>
              {messages.rfqWorkspace.backToHub}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const selectedCommodity = commodities.find((c) => c.id === commodityId);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* Header */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{t.title}</h1>
          <p className="text-sm text-muted-foreground">{t.subtitle}</p>
        </div>
        <div className="flex items-center gap-3">
          {listingVersion && (
            <Badge variant="outline" className="h-8 px-3 text-xs">
              {t.preview.versionLabel} {listingVersion}
            </Badge>
          )}
          {savedNotice && (
            <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
              <CheckCircle2 className="h-4 w-4" />
              {t.actions.savedNotice}
            </span>
          )}
          <Button
            variant="outline"
            onClick={() => void handleSaveDraft()}
            disabled={isSavingDraft || isActivating}
            className="flex items-center gap-2 h-9 px-3 text-xs"
          >
            {isSavingDraft ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            <span>{isSavingDraft ? t.actions.saving : t.actions.saveDraft}</span>
          </Button>
        </div>
      </div>

      {/* Stale Conflict Banner */}
      {staleConflict && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-amber-800 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{t.conflicts.staleTitle}</span>
            <span className="text-sm">{t.conflicts.staleDescription}</span>
          </div>
        </div>
      )}

      {/* General Error Banner */}
      {generalError && !staleConflict && (
        <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <span className="text-sm font-medium">{generalError}</span>
        </div>
      )}

      {/* Stepper Navigation */}
      <div className="grid grid-cols-4 gap-2 rounded-xl border bg-card p-2 text-center shadow-xs">
        {[
          { id: 1, label: t.steps.product, icon: Package },
          { id: 2, label: t.steps.commercial, icon: Clock },
          { id: 3, label: t.steps.visibility, icon: Layers },
          { id: 4, label: t.steps.preview, icon: Sparkles },
        ].map((item) => {
          const Icon = item.icon;
          const isActive = step === item.id;
          const isPassed = step > item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                if (item.id < step || validateCurrentStep()) {
                  setStep(item.id);
                }
              }}
              className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-semibold transition-all ${
                isActive
                  ? "bg-primary text-primary-foreground shadow-xs"
                  : isPassed
                    ? "bg-muted/60 text-foreground hover:bg-muted"
                    : "text-muted-foreground hover:bg-muted/40"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="hidden sm:inline">{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Step 1: Product & Specifications */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>{t.product.title}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Commodity Selector */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="commodity-select" className="text-sm font-medium">
                  {t.product.commodityLabel}
                </Label>
                <Select value={commodityId} onValueChange={handleCommoditySelect}>
                  <SelectTrigger id="commodity-select" aria-label={t.product.commodityLabel}>
                    <SelectValue placeholder={t.product.commodityPlaceholder} />
                  </SelectTrigger>
                  <SelectContent>
                    {commodities.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {isRtl ? c.name_fa : c.name_en} ({c.code})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedCommodity && (
                  <p className="text-xs text-muted-foreground">
                    {t.product.schemaVersion}: {activeSchema ? `v${activeSchema.version}` : "—"}
                  </p>
                )}
              </div>

              {/* Quantity and Unit */}
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 flex flex-col gap-2">
                  <Label htmlFor="quantity" className="text-sm font-medium">
                    {t.product.quantityLabel}
                  </Label>
                  <Input
                    id="quantity"
                    type="number"
                    step="any"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    placeholder={t.product.quantityPlaceholder}
                    className={fieldErrors.quantity ? "border-destructive" : ""}
                  />
                  {fieldErrors.quantity && (
                    <span className="text-xs text-destructive">{fieldErrors.quantity}</span>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="unit" className="text-sm font-medium">
                    {t.product.unitLabel}
                  </Label>
                  <Input
                    id="unit"
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder={t.product.unitPlaceholder}
                  />
                </div>
              </div>
            </div>

            {/* Dynamic Commodity Specification Form */}
            <div className="mt-4 flex flex-col gap-3 border-t pt-4">
              <h3 className="text-base font-semibold text-foreground">
                {t.product.specificationsTitle}
              </h3>

              {!commodityId ? (
                <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                  {t.product.selectCommodityPrompt}
                </div>
              ) : isLoadingSchema ? (
                <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                  <span>{t.product.loadingSchema}</span>
                </div>
              ) : activeSchema ? (
                <CommoditySpecificationForm
                  schema={activeSchema}
                  value={specifications}
                  onChange={setSpecifications}
                  errors={specificationErrors}
                  locale={locale}
                />
              ) : (
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
                  {t.product.selectCommodityPrompt}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Commercial & Availability Terms */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>{t.commercial.title}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {/* Indicative Price & Currency */}
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 flex flex-col gap-2">
                  <Label htmlFor="indicative-price" className="text-sm font-medium">
                    {t.commercial.indicativePriceLabel}
                  </Label>
                  <Input
                    id="indicative-price"
                    type="number"
                    step="0.01"
                    value={indicativePrice}
                    onChange={(e) => setIndicativePrice(e.target.value)}
                    placeholder={t.commercial.indicativePricePlaceholder}
                    className={fieldErrors.indicative_price ? "border-destructive" : ""}
                  />
                  {fieldErrors.indicative_price && (
                    <span className="text-xs text-destructive">{fieldErrors.indicative_price}</span>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="currency" className="text-sm font-medium">
                    {t.commercial.currencyLabel}
                  </Label>
                  <Input
                    id="currency"
                    maxLength={3}
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                    placeholder={t.commercial.currencyPlaceholder}
                  />
                </div>
              </div>

              {/* Payment Terms & Incoterm */}
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="payment-terms" className="text-sm font-medium">
                    {t.commercial.paymentTermsLabel}
                  </Label>
                  <Input
                    id="payment-terms"
                    value={paymentTerms}
                    onChange={(e) => setPaymentTerms(e.target.value)}
                    placeholder={t.commercial.paymentTermsPlaceholder}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="incoterm" className="text-sm font-medium">
                    {t.commercial.incotermLabel}
                  </Label>
                  <Input
                    id="incoterm"
                    maxLength={10}
                    value={incoterm}
                    onChange={(e) => setIncoterm(e.target.value.toUpperCase())}
                    placeholder={t.commercial.incotermPlaceholder}
                  />
                </div>
              </div>

              {/* Origin & Destination */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="origin" className="text-sm font-medium">
                  {t.commercial.originLabel}
                </Label>
                <Input
                  id="origin"
                  value={origin}
                  onChange={(e) => setOrigin(e.target.value)}
                  placeholder={t.commercial.originPlaceholder}
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor="destination" className="text-sm font-medium">
                  {t.commercial.destinationLabel}
                </Label>
                <Input
                  id="destination"
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                  placeholder={t.commercial.destinationPlaceholder}
                />
              </div>

              {/* Availability Window */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="window-start" className="text-sm font-medium">
                  {t.commercial.availabilityWindowStartLabel}
                </Label>
                <Input
                  id="window-start"
                  type="date"
                  value={availabilityWindowStart}
                  onChange={(e) => setAvailabilityWindowStart(e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor="window-end" className="text-sm font-medium">
                  {t.commercial.availabilityWindowEndLabel}
                </Label>
                <Input
                  id="window-end"
                  type="date"
                  value={availabilityWindowEnd}
                  onChange={(e) => setAvailabilityWindowEnd(e.target.value)}
                  className={fieldErrors.availabilityWindowEnd ? "border-destructive" : ""}
                />
                {fieldErrors.availabilityWindowEnd && (
                  <span className="text-xs text-destructive">
                    {fieldErrors.availabilityWindowEnd}
                  </span>
                )}
              </div>
            </div>

            {/* Quality Notes */}
            <div className="flex flex-col gap-2">
              <Label htmlFor="quality-notes" className="text-sm font-medium">
                {t.commercial.qualityNotesLabel}
              </Label>
              <Textarea
                id="quality-notes"
                rows={3}
                value={qualityNotes}
                onChange={(e) => setQualityNotes(e.target.value)}
                placeholder={t.commercial.qualityNotesPlaceholder}
              />
            </div>

            {/* Internal Notes */}
            <div className="flex flex-col gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
              <Label htmlFor="notes" className="text-sm font-medium text-foreground">
                {t.commercial.notesLabel}
              </Label>
              <Textarea
                id="notes"
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t.commercial.notesPlaceholder}
              />
              <p className="text-xs text-muted-foreground">
                {messages.supplyListingDetail.internalNotesNotice}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Visibility Selection */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>{t.visibility.title}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Label className="text-sm font-medium">{t.visibility.tierLabel}</Label>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              {[
                {
                  id: "public" as RFQVisibilityEnum,
                  title: t.visibility.public,
                  desc: t.visibility.publicDesc,
                },
                {
                  id: "network" as RFQVisibilityEnum,
                  title: t.visibility.network,
                  desc: t.visibility.networkDesc,
                },
                {
                  id: "private" as RFQVisibilityEnum,
                  title: t.visibility.private,
                  desc: t.visibility.privateDesc,
                },
              ].map((tier) => (
                <button
                  key={tier.id}
                  type="button"
                  onClick={() => setVisibility(tier.id)}
                  className={`flex flex-col gap-2 rounded-xl border p-4 text-start transition-all ${
                    visibility === tier.id
                      ? "border-primary bg-primary/5 ring-2 ring-primary shadow-xs"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-foreground">{tier.title}</span>
                    {visibility === tier.id && (
                      <CheckCircle2 className="h-5 w-5 text-primary" />
                    )}
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground">{tier.desc}</p>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Preview & Explicit Activation */}
      {step === 4 && (
        <Card>
          <CardHeader>
            <CardTitle>{t.preview.title}</CardTitle>
            <CardDescription>{t.preview.description}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {/* Warning Alert */}
            <div className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-4 text-foreground">
              <Sparkles className="h-5 w-5 text-primary shrink-0" />
              <p className="text-xs leading-relaxed">{t.preview.activateWarning}</p>
            </div>

            {/* Product Summary & Dynamic Specification View */}
            <div className="flex flex-col gap-3 rounded-lg border p-4">
              <h3 className="font-semibold text-foreground">{t.preview.productSummary}</h3>
              <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
                <div>
                  <span className="text-muted-foreground">{t.product.commodityLabel}:</span>
                  <p className="font-medium">
                    {selectedCommodity
                      ? `${isRtl ? selectedCommodity.name_fa : selectedCommodity.name_en} (${commodityCode || selectedCommodity.code})`
                      : (commodityCode || "—")}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.product.schemaVersion}:</span>
                  <p className="font-medium">
                    {activeSchema ? `v${activeSchema.version}` : "—"}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.product.quantityLabel}:</span>
                  <p className="font-medium">
                    {quantity ? `${quantity} ${unit}` : "—"}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.visibility.tierLabel}:</span>
                  <p className="font-medium capitalize">{visibility}</p>
                </div>
              </div>

              {activeSchema && (
                <div className="mt-4 border-t pt-4">
                  <CommoditySpecificationView
                    schema={activeSchema}
                    value={specifications}
                    locale={locale}
                  />
                </div>
              )}
            </div>

            {/* Commercial Terms Summary */}
            <div className="flex flex-col gap-3 rounded-lg border p-4">
              <h3 className="font-semibold text-foreground">{t.preview.commercialSummary}</h3>
              <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
                <div>
                  <span className="text-muted-foreground">{t.commercial.indicativePriceLabel}:</span>
                  <p className="font-medium">
                    {indicativePrice ? `${indicativePrice} ${currency}` : t.preview.notSpecified}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.commercial.paymentTermsLabel}:</span>
                  <p className="font-medium">{paymentTerms || t.preview.notSpecified}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.commercial.incotermLabel}:</span>
                  <p className="font-medium">{incoterm || t.preview.notSpecified}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.commercial.originLabel}:</span>
                  <p className="font-medium">{origin || t.preview.notSpecified}</p>
                </div>
              </div>
            </div>

            {/* Availability Window */}
            <div className="flex flex-col gap-3 rounded-lg border p-4">
              <h3 className="font-semibold text-foreground">{t.preview.deliverySummary}</h3>
              <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
                <div>
                  <span className="text-muted-foreground">{t.commercial.availabilityWindowStartLabel}:</span>
                  <p className="font-medium">{availabilityWindowStart || t.preview.notSpecified}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.commercial.availabilityWindowEndLabel}:</span>
                  <p className="font-medium">{availabilityWindowEnd || t.preview.notSpecified}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">{t.commercial.destinationLabel}:</span>
                  <p className="font-medium">{destination || t.preview.notSpecified}</p>
                </div>
              </div>
            </div>

            {/* Quality & Internal Notes */}
            {(qualityNotes || notes) && (
              <div className="flex flex-col gap-3 rounded-lg border p-4">
                <h3 className="font-semibold text-foreground">{t.preview.qualitySummary}</h3>
                {qualityNotes && (
                  <div>
                    <span className="text-xs text-muted-foreground">{t.commercial.qualityNotesLabel}:</span>
                    <p className="text-sm font-medium">{qualityNotes}</p>
                  </div>
                )}
                {notes && (
                  <div className="mt-2 rounded-md bg-amber-500/10 p-3">
                    <span className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                      {t.preview.internalNotesSummary}:
                    </span>
                    <p className="text-sm text-amber-800 dark:text-amber-300">{notes}</p>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Navigation Footer */}
      <div className="flex items-center justify-between border-t pt-4">
        <Button
          variant="outline"
          onClick={handlePrevStep}
          disabled={step === 1 || isActivating || isSavingDraft}
          className="flex items-center gap-2"
        >
          {isRtl ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          <span>{t.actions.prev}</span>
        </Button>

        <div className="flex items-center gap-3">
          {step < 4 ? (
            <Button
              onClick={() => void handleNextStep()}
              disabled={isSavingDraft || isActivating}
              className="flex items-center gap-2"
            >
              <span>{t.actions.next}</span>
              {isRtl ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </Button>
          ) : (
            <Button
              onClick={() => void handleActivate()}
              disabled={isActivating || isSavingDraft}
              className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
            >
              {isActivating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              <span>{isActivating ? t.actions.activating : t.actions.activate}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

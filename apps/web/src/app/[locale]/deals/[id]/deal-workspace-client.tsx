"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { CommoditySpecificationView } from "@/components/commodity/commodity-specification-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Award,
  CheckCircle2,
  ExternalLink,
  FileText,
  Layers,
  Loader2,
  Lock,
  PlayCircle,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Truck,
  Users,
} from "lucide-react";

type DealResponse = components["schemas"]["DealResponse"];
type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
type PrimaryChannelEnum = components["schemas"]["PrimaryChannelEnum"];

export type DealWorkspaceTab =
  | "overview"
  | "terms"
  | "parties"
  | "attribution"
  | "execution"
  | "logistics"
  | "quality"
  | "documents"
  | "issues"
  | "activity";

export interface DealWorkspaceClientProps {
  locale?: EnabledLocale;
  dealId: string;
}

export function DealWorkspaceClient({ locale = "fa", dealId }: DealWorkspaceClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace;
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // Active navigation tab
  const [activeTab, setActiveTab] = useState<DealWorkspaceTab>("overview");

  // Core Data States
  const [deal, setDeal] = useState<DealResponse | null>(null);
  const [schema, setSchema] = useState<CommoditySchemaVersion | null>(null);

  // Loading & Error States
  const [isLoadingDeal, setIsLoadingDeal] = useState<boolean>(true);
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);
  const [isNotFound, setIsNotFound] = useState<boolean>(false);
  const [isUnauthorized, setIsUnauthorized] = useState<boolean>(false);

  // Manual Attribution Resolution Form State (Operator/Admin only)
  const [selectedChannel, setSelectedChannel] = useState<PrimaryChannelEnum | "">("");
  const [resolutionReason, setResolutionReason] = useState<string>("");
  const [isResolving, setIsResolving] = useState<boolean>(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolveSuccess, setResolveSuccess] = useState<boolean>(false);

  // Actor / Session Scope
  const isAuthLoading = state.status === "loading";
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");
  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const currentUserId = state.status === "authenticated" ? state.user.id : null;

  // Active request key to discard out-of-order or stale in-flight responses
  const activeRequestKeyRef = useRef<string>("");
  const previousSessionKeyRef = useRef<string | null>(null);
  const currentSessionKey = `${dealId}:${currentOrgId ?? "none"}:${currentUserId ?? "none"}:${isOperatorOrAdmin ? "op" : "cust"}`;

  // 1. Authoritative Deal Fetch & Session Isolation
  useEffect(() => {
    if (isAuthLoading) return;

    // Invalidate state when session scope changes
    if (
      previousSessionKeyRef.current !== null &&
      previousSessionKeyRef.current !== currentSessionKey
    ) {
      queryClient.removeQueries({ queryKey: ["deal"] });
      setDeal(null);
      setSchema(null);
      setActiveTab("overview");
      setResolveError(null);
      setResolveSuccess(false);
    }
    previousSessionKeyRef.current = currentSessionKey;

    let ignore = false;
    const requestKey = currentSessionKey;
    activeRequestKeyRef.current = requestKey;

    async function fetchDeal() {
      setIsNotFound(false);
      setIsUnauthorized(false);
      setResolveError(null);
      setResolveSuccess(false);
      setIsLoadingDeal(true);

      try {
        const { data, response } = await apiClient.GET("/api/deals/{deal_id}/", {
          params: { path: { deal_id: dealId } },
        });

        if (ignore || activeRequestKeyRef.current !== requestKey) return;

        if (response.status === 404) {
          setIsNotFound(true);
          setDeal(null);
          return;
        }

        if (response.status === 403) {
          setIsUnauthorized(true);
          setDeal(null);
          return;
        }

        if (response.ok && data) {
          setDeal(data);
          setIsNotFound(false);
          setIsUnauthorized(false);
        }
      } catch {
        if (!ignore && activeRequestKeyRef.current === requestKey) {
          setIsNotFound(true);
          setDeal(null);
        }
      } finally {
        if (!ignore && activeRequestKeyRef.current === requestKey) {
          setIsLoadingDeal(false);
        }
      }
    }

    void fetchDeal();
    return () => {
      ignore = true;
    };
  }, [currentSessionKey, dealId, isAuthLoading, queryClient]);

  // 2. Exact Historical Schema Fetch
  const schemaVersionId = deal?.terms?.schema_version_id;
  useEffect(() => {
    if (!schemaVersionId) return;
    const currentSchemaId = schemaVersionId;
    let ignore = false;

    async function loadExactSchema() {
      setIsLoadingSchema(true);
      try {
        const { data, response } = await apiClient.GET("/api/commodity-schemas/{id}/", {
          params: { path: { id: currentSchemaId } },
        });

        if (ignore) return;
        if (response.ok && data) {
          setSchema(data);
        }
      } catch {
        if (!ignore) {
          setSchema(null);
        }
      } finally {
        if (!ignore) {
          setIsLoadingSchema(false);
        }
      }
    }

    void loadExactSchema();
    return () => {
      ignore = true;
    };
  }, [schemaVersionId]);

  // Handle Manual Attribution Resolution Submit
  const handleResolveAttribution = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!deal || !selectedChannel || !resolutionReason.trim()) return;

    setIsResolving(true);
    setResolveError(null);

    try {
      const { data, response } = await apiClient.POST(
        "/api/deals/{deal_id}/attribution/resolve/",
        {
          params: { path: { deal_id: deal.id } },
          body: {
            primary_channel: selectedChannel as PrimaryChannelEnum,
            reason: resolutionReason.trim(),
            expected_version: deal.attribution.version,
          },
        }
      );

      if (response.ok && data) {
        setDeal((prev) => (prev ? { ...prev, attribution: data } : null));
        setResolveSuccess(true);
        setSelectedChannel("");
        setResolutionReason("");
      } else if (response.status === 409) {
        setResolveError(t.attribution.resolveConflictError);
      } else {
        setResolveError(t.attribution.resolveGenericError);
      }
    } catch {
      setResolveError(t.attribution.resolveGenericError);
    } finally {
      setIsResolving(false);
    }
  };

  const ArrowIcon = isRtl ? ArrowLeft : ArrowRight;

  // Loading State View
  if (isAuthLoading || isLoadingDeal) {
    return (
      <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Link href={`/${locale}/deals`} className="hover:text-foreground">
            {t.backToList}
          </Link>
        </div>
        <Card className="flex items-center justify-center p-16 shadow-none">
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <Loader2 className="size-8 animate-spin text-primary" />
            <p className="text-sm">{t.loading}</p>
          </div>
        </Card>
      </div>
    );
  }

  // Not Found State View
  if (isNotFound) {
    return (
      <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Link href={`/${locale}/deals`} className="flex items-center gap-1 hover:text-foreground">
            <ArrowIcon className="size-4" />
            <span>{t.backToList}</span>
          </Link>
        </div>
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <AlertCircle className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.notFoundTitle}</h2>
          <p className="mt-2 text-sm text-muted-foreground">{t.notFoundDescription}</p>
          <div className="mt-6">
            <Button asChild variant="outline">
              <Link href={`/${locale}/deals`}>{t.backToList}</Link>
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // Unauthorized State View
  if (isUnauthorized) {
    return (
      <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Link href={`/${locale}/deals`} className="flex items-center gap-1 hover:text-foreground">
            <ArrowIcon className="size-4" />
            <span>{t.backToList}</span>
          </Link>
        </div>
        <Card className="p-12 text-center shadow-none border-destructive/20 bg-destructive/5">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-destructive/10">
            <ShieldAlert className="size-6 text-destructive" />
          </div>
          <h2 className="mt-4 text-base font-semibold text-destructive">{t.unauthorizedTitle}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.unauthorizedDescription}
          </p>
          <div className="mt-6">
            <Button asChild variant="outline">
              <Link href={`/${locale}/deals`}>{t.backToList}</Link>
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (!deal) return null;

  // Extract Parties
  const buyerParty = deal.parties?.find((p) => p.role === "BUYER");
  const sellerParty = deal.parties?.find((p) => p.role === "SELLER");

  const commodityName =
    locale === "fa"
      ? deal.terms?.commodity_name_fa || deal.terms?.commodity_code
      : deal.terms?.commodity_name_en || deal.terms?.commodity_code;

  const isAttributionPending = deal.attribution?.status === "PENDING";
  const primaryChannelKey = deal.attribution?.primary_channel;
  const primaryChannelLabel = primaryChannelKey
    ? t.attribution.channels[primaryChannelKey as keyof typeof t.attribution.channels] ?? primaryChannelKey
    : "—";

  // Tab definitions
  const tabs: { key: DealWorkspaceTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { key: "overview", label: t.tabs.overview, icon: Layers },
    { key: "terms", label: t.tabs.terms, icon: Scale },
    { key: "parties", label: t.tabs.parties, icon: Users },
    { key: "attribution", label: t.tabs.attribution, icon: Award },
    { key: "execution", label: t.tabs.execution, icon: PlayCircle },
    { key: "logistics", label: t.tabs.logistics, icon: Truck },
    { key: "quality", label: t.tabs.quality, icon: ShieldCheck },
    { key: "documents", label: t.tabs.documents, icon: FileText },
    { key: "issues", label: t.tabs.issues, icon: AlertTriangle },
    { key: "activity", label: t.tabs.activity, icon: Activity },
  ];

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* Navigation Breadcrumb & Back */}
      <div className="flex items-center justify-between">
        <Link
          href={`/${locale}/deals`}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowIcon className="size-3.5" />
          <span>{t.backToList}</span>
        </Link>
        <Badge variant="outline" className="text-xs text-emerald-700 bg-emerald-500/10 border-emerald-500/30">
          <CheckCircle2 className="size-3 me-1" />
          <span>{t.badges.materialized}</span>
        </Badge>
      </div>

      {/* Deal Workspace Header Card */}
      <Card className="shadow-none border-primary/20 bg-card">
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-primary">
                  {t.dealIdPrefix}:
                </span>
                <span className="font-mono text-xs text-muted-foreground" dir="ltr">
                  {deal.id}
                </span>
                {deal.seller_external_counterparty_id && (
                  <Badge variant="outline" className="text-xs border-amber-500/40 text-amber-700 bg-amber-500/10">
                    {t.badges.externalCounterparty}
                  </Badge>
                )}
              </div>
              <h1 className="mt-1 text-2xl font-bold tracking-tight">
                {commodityName || deal.terms?.commodity_code || "کالا"}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground flex flex-wrap items-center gap-2">
                <span>{buyerParty?.name_snapshot || "خریدار"}</span>
                <span>←</span>
                <span>{sellerParty?.name_snapshot || "فروشنده"}</span>
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-4 bg-muted/40 p-4 rounded-lg border text-sm">
              <div className="text-start">
                <p className="text-xs text-muted-foreground">{t.overview.awardedQuantity}</p>
                <p className="font-semibold text-base mt-0.5" dir="ltr">{`${deal.terms?.quantity} ${deal.terms?.quantity_unit}`}</p>
              </div>
              <div className="h-8 w-px bg-border hidden sm:block" />
              <div className="text-start">
                <p className="text-xs text-muted-foreground">{t.overview.unitPrice}</p>
                <p className="font-semibold text-base mt-0.5" dir="ltr">{`${deal.terms?.unit_price} ${deal.terms?.currency}`}</p>
              </div>
              <div className="h-8 w-px bg-border hidden sm:block" />
              <div className="text-start">
                <p className="text-xs text-muted-foreground">{t.overview.productCost}</p>
                <p className="font-bold text-base text-primary mt-0.5" dir="ltr">{`${deal.terms?.product_cost_snapshot} ${deal.terms?.currency}`}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabs Navigation Bar */}
      <div className="border-b border-border overflow-x-auto">
        <nav className="flex space-x-1 rtl:space-x-reverse min-w-max pb-px" aria-label="Tabs">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
                }`}
              >
                <Icon className="size-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab 1: Overview */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">{t.overview.commercialSummary}</CardTitle>
              <CardDescription className="text-xs">
                {t.badges.immutableNotice}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.dealId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">{deal.id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.awardAllocationId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">{deal.award_allocation_id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.awardId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">{deal.award_id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.rfqId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">
                    <Link
                      href={`/${locale}/trade-hub/rfqs/${deal.rfq_id}`}
                      className="text-primary hover:underline inline-flex items-center gap-1"
                    >
                      <span>{deal.rfq_id.slice(0, 13)}…</span>
                      <ExternalLink className="size-3" />
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.offerId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">{deal.offer_id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.offerVersionId}</dt>
                  <dd className="mt-1 font-mono text-xs break-all" dir="ltr">{deal.offer_version_id}</dd>
                </div>

                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.buyer}</dt>
                  <dd className="mt-1 font-medium text-foreground">{buyerParty?.name_snapshot || "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.seller}</dt>
                  <dd className="mt-1 font-medium text-foreground flex items-center gap-1.5">
                    <span>{sellerParty?.name_snapshot || "—"}</span>
                    {deal.seller_external_counterparty_id && (
                      <Badge variant="outline" className="text-[10px] border-amber-500/40 text-amber-700 bg-amber-500/10">
                        {t.badges.externalCounterparty}
                      </Badge>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.commodity}</dt>
                  <dd className="mt-1 font-medium text-foreground">{commodityName || "—"}</dd>
                </div>

                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.awardedQuantity}</dt>
                  <dd className="mt-1 font-semibold" dir="ltr">{deal.terms?.quantity} {deal.terms?.quantity_unit}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.unitPrice}</dt>
                  <dd className="mt-1 font-semibold" dir="ltr">{deal.terms?.unit_price} {deal.terms?.currency}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.productCost}</dt>
                  <dd className="mt-1 font-bold text-primary" dir="ltr">{deal.terms?.product_cost_snapshot} {deal.terms?.currency}</dd>
                </div>

                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.incoterm}</dt>
                  <dd className="mt-1 font-semibold" dir="ltr">{deal.terms?.incoterm || "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.deliveryWindow}</dt>
                  <dd className="mt-1 text-xs" dir="ltr">
                    {deal.terms?.delivery_start ?? "—"} ~ {deal.terms?.delivery_end ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.origin} / {t.overview.destination}</dt>
                  <dd className="mt-1 text-xs">{deal.terms?.origin || "—"} / {deal.terms?.destination || "—"}</dd>
                </div>

                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.attributionChannel}</dt>
                  <dd className="mt-1 font-medium text-xs">{primaryChannelLabel}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.attributionStatus}</dt>
                  <dd className="mt-1">
                    {isAttributionPending ? (
                      <Badge variant="outline" className="text-amber-600 border-amber-500/30 bg-amber-500/10">
                        {t.attribution.statuses.PENDING}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-emerald-600 border-emerald-500/30 bg-emerald-500/10">
                        {t.attribution.statuses.RESOLVED}
                      </Badge>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground font-medium">{t.overview.createdAt}</dt>
                  <dd className="mt-1 font-mono text-xs" dir="ltr">{deal.created_at}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 2: Terms */}
      {activeTab === "terms" && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">{t.terms.title}</CardTitle>
              <CardDescription className="text-xs">{t.terms.subtitle}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Commercial Values */}
              <div className="border-b pb-6">
                <h3 className="text-sm font-semibold mb-4 text-foreground">{t.terms.quantityAndPrice}</h3>
                <dl className="grid grid-cols-1 sm:grid-cols-3 gap-6 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.quantity}</dt>
                    <dd className="mt-1 text-base font-bold" dir="ltr">
                      {deal.terms?.quantity} {deal.terms?.quantity_unit}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.unitPrice}</dt>
                    <dd className="mt-1 text-base font-bold" dir="ltr">
                      {deal.terms?.unit_price} {deal.terms?.currency}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.productCost}</dt>
                    <dd className="mt-1 text-base font-bold text-primary" dir="ltr">
                      {deal.terms?.product_cost_snapshot} {deal.terms?.currency}
                    </dd>
                  </div>
                </dl>
              </div>

              {/* Dynamic Commodity Specifications with Historical Schema */}
              <div className="border-b pb-6">
                <h3 className="text-sm font-semibold mb-4 text-foreground">{t.terms.specificationsTitle}</h3>
                {isLoadingSchema ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-4">
                    <Loader2 className="size-4 animate-spin text-primary" />
                    <span>{t.loadingSchema}</span>
                  </div>
                ) : schema ? (
                  <CommoditySpecificationView
                    schema={schema}
                    value={(deal.terms?.specifications as Record<string, unknown>) || {}}
                    locale={locale}
                  />
                ) : (
                  <div className="p-4 rounded-md bg-muted/30 text-xs font-mono" dir="ltr">
                    <pre>{JSON.stringify(deal.terms?.specifications, null, 2)}</pre>
                  </div>
                )}
              </div>

              {/* Payment and Delivery */}
              <div className="border-b pb-6">
                <h3 className="text-sm font-semibold mb-4 text-foreground">{t.terms.paymentAndDelivery}</h3>
                <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.paymentTerms}</dt>
                    <dd className="mt-1 font-medium">{deal.terms?.payment_terms || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.deliveryTerms}</dt>
                    <dd className="mt-1 font-medium">{deal.terms?.delivery_terms || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.incoterm}</dt>
                    <dd className="mt-1 font-bold" dir="ltr">{deal.terms?.incoterm || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.deliveryWindow}</dt>
                    <dd className="mt-1 text-xs" dir="ltr">
                      {deal.terms?.delivery_start ?? "—"} ~ {deal.terms?.delivery_end ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.origin}</dt>
                    <dd className="mt-1 text-xs">{deal.terms?.origin || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">{t.terms.destination}</dt>
                    <dd className="mt-1 text-xs">{deal.terms?.destination || "—"}</dd>
                  </div>
                  <div className="sm:col-span-2 lg:col-span-3">
                    <dt className="text-xs text-muted-foreground">{t.terms.logisticsCost}</dt>
                    <dd className="mt-1 text-sm font-medium">
                      {deal.terms?.logistics_cost_status === "KNOWN_SEPARATE" ? (
                        <span dir="ltr" className="font-semibold text-primary">
                          {deal.terms?.logistics_cost_amount} {deal.terms?.currency} ({t.terms.logisticsStatuses.KNOWN_SEPARATE})
                        </span>
                      ) : deal.terms?.logistics_cost_status ? (
                        <span>
                          {t.terms.logisticsStatuses[deal.terms.logistics_cost_status as keyof typeof t.terms.logisticsStatuses] ?? deal.terms.logistics_cost_status}
                        </span>
                      ) : (
                        <span>{t.terms.logisticsStatuses.UNKNOWN}</span>
                      )}
                    </dd>
                  </div>
                </dl>
              </div>

              {/* Additional Cost Snapshots */}
              <div>
                <h3 className="text-sm font-semibold mb-4 text-foreground">{t.terms.additionalCostsTitle}</h3>
                {!deal.terms?.cost_snapshots || deal.terms.cost_snapshots.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t.terms.noAdditionalCosts}</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-start">{t.terms.costKind}</TableHead>
                          <TableHead className="text-start">{t.terms.costAmount}</TableHead>
                          <TableHead className="text-start">{t.terms.costDescription}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {deal.terms.cost_snapshots.map((cost) => (
                          <TableRow key={cost.id}>
                            <TableCell className="text-xs font-medium">{cost.kind}</TableCell>
                            <TableCell className="text-xs font-semibold" dir="ltr">
                              {cost.amount} {cost.currency}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {cost.description_snapshot || "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 3: Parties */}
      {activeTab === "parties" && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">{t.parties.title}</CardTitle>
              <CardDescription className="text-xs">{t.parties.subtitle}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Buyer Card */}
                <Card className="shadow-none border bg-card">
                  <CardHeader className="bg-muted/30 pb-3 border-b">
                    <div className="flex items-center justify-between">
                      <Badge variant="outline" className="text-xs border-primary/30 text-primary bg-primary/5">
                        {t.parties.buyerRole}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px]">
                        {t.badges.snapshotTruth}
                      </Badge>
                    </div>
                    <CardTitle className="text-base mt-2">{buyerParty?.name_snapshot || "—"}</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 space-y-3 text-xs">
                    <div>
                      <span className="text-muted-foreground">{t.parties.partyType}: </span>
                      <span className="font-medium">{t.parties.partyTypeOrg}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">{t.parties.country}: </span>
                      <span className="font-medium" dir="ltr">{buyerParty?.country_snapshot || "—"}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">{t.parties.registrationId}: </span>
                      <span className="font-mono text-foreground" dir="ltr">
                        {buyerParty?.registration_identifier_snapshot || "—"}
                      </span>
                    </div>

                    {buyerParty?.organization_id && (
                      <div className="mt-4 pt-3 border-t">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-muted-foreground font-medium">
                            {t.badges.currentProfile}
                          </span>
                          <Link
                            href={`/${locale}/directory/${buyerParty.organization_id}`}
                            className="text-[11px] text-primary hover:underline inline-flex items-center gap-1"
                          >
                            <span>{t.parties.currentProfileLink}</span>
                            <ExternalLink className="size-3" />
                          </Link>
                        </div>
                        <p className="mt-1 text-[10px] text-muted-foreground leading-relaxed">
                          {t.parties.currentProfileNote}
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Seller Card */}
                <Card className="shadow-none border bg-card">
                  <CardHeader className="bg-muted/30 pb-3 border-b">
                    <div className="flex items-center justify-between">
                      <Badge variant="outline" className="text-xs border-blue-500/30 text-blue-700 bg-blue-500/5">
                        {t.parties.sellerRole}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px]">
                        {t.badges.snapshotTruth}
                      </Badge>
                    </div>
                    <CardTitle className="text-base mt-2 flex items-center gap-2">
                      <span>{sellerParty?.name_snapshot || "—"}</span>
                      {deal.seller_external_counterparty_id && (
                        <Badge variant="outline" className="text-[10px] border-amber-500/40 text-amber-700 bg-amber-500/10">
                          {t.badges.externalCounterparty}
                        </Badge>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 space-y-3 text-xs">
                    <div>
                      <span className="text-muted-foreground">{t.parties.partyType}: </span>
                      <span className="font-medium">
                        {sellerParty?.party_type === "EXTERNAL_COUNTERPARTY"
                          ? t.parties.partyTypeExt
                          : t.parties.partyTypeOrg}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">{t.parties.country}: </span>
                      <span className="font-medium" dir="ltr">{sellerParty?.country_snapshot || "—"}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">{t.parties.registrationId}: </span>
                      <span className="font-mono text-foreground" dir="ltr">
                        {sellerParty?.registration_identifier_snapshot || "—"}
                      </span>
                    </div>

                    {sellerParty?.party_type === "EXTERNAL_COUNTERPARTY" ? (
                      <div className="mt-4 pt-3 border-t">
                        <p className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-500/10 p-2.5 rounded-md leading-relaxed border border-amber-500/20">
                          {t.parties.externalCounterpartyNote}
                        </p>
                      </div>
                    ) : sellerParty?.organization_id ? (
                      <div className="mt-4 pt-3 border-t">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-muted-foreground font-medium">
                            {t.badges.currentProfile}
                          </span>
                          <Link
                            href={`/${locale}/directory/${sellerParty.organization_id}`}
                            className="text-[11px] text-primary hover:underline inline-flex items-center gap-1"
                          >
                            <span>{t.parties.currentProfileLink}</span>
                            <ExternalLink className="size-3" />
                          </Link>
                        </div>
                        <p className="mt-1 text-[10px] text-muted-foreground leading-relaxed">
                          {t.parties.currentProfileNote}
                        </p>
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 4: Attribution */}
      {activeTab === "attribution" && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg">{t.attribution.title}</CardTitle>
                  <CardDescription className="text-xs">{t.attribution.subtitle}</CardDescription>
                </div>
                {!isAttributionPending && (
                  <Badge variant="outline" className="text-emerald-600 border-emerald-500/30 bg-emerald-500/10">
                    <Lock className="size-3 me-1" />
                    <span>{t.attribution.immutableNotice}</span>
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Primary Attribution Summary */}
              <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 text-sm bg-muted/20 p-4 rounded-lg border">
                <div>
                  <dt className="text-xs text-muted-foreground">{t.attribution.primaryChannel}</dt>
                  <dd className="mt-1 font-semibold text-base">{primaryChannelLabel}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t.attribution.status}</dt>
                  <dd className="mt-1">
                    {isAttributionPending ? (
                      <Badge variant="outline" className="text-amber-600 border-amber-500/30 bg-amber-500/10">
                        {t.attribution.statuses.PENDING}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-emerald-600 border-emerald-500/30 bg-emerald-500/10">
                        {t.attribution.statuses.RESOLVED}
                      </Badge>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t.attribution.resolutionMethod}</dt>
                  <dd className="mt-1 font-medium">
                    {deal.attribution?.resolution_method
                      ? t.attribution.methods[deal.attribution.resolution_method as keyof typeof t.attribution.methods] ?? deal.attribution.resolution_method
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">{t.attribution.resolvedAt}</dt>
                  <dd className="mt-1 text-xs font-mono" dir="ltr">
                    {deal.attribution?.resolved_at || "—"}
                  </dd>
                </div>
              </dl>

              {/* Internal Metadata (Operator & Admin Only) */}
              {isOperatorOrAdmin && (
                <div className="space-y-6 border-t pt-6">
                  {deal.attribution?.resolved_by_id && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs bg-muted/40 p-4 rounded-md border">
                      <div>
                        <span className="text-muted-foreground font-medium">{t.attribution.resolvedBy}: </span>
                        <span className="font-mono" dir="ltr">{deal.attribution.resolved_by_id}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground font-medium">{t.attribution.resolutionReason}: </span>
                        <span>{deal.attribution.resolution_reason || "—"}</span>
                      </div>
                    </div>
                  )}

                  {/* Broker Provenance Rows */}
                  <div>
                    <h3 className="text-sm font-semibold mb-3 text-foreground">{t.attribution.brokerProvenanceTitle}</h3>
                    {!deal.broker_attributions || deal.broker_attributions.length === 0 ? (
                      <p className="text-xs text-muted-foreground">{t.attribution.noBrokerRows}</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-start">{t.attribution.brokerOrgId}</TableHead>
                              <TableHead className="text-start">{t.attribution.brokerRole}</TableHead>
                              <TableHead className="text-start">{t.attribution.relatedOpportunityId}</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {deal.broker_attributions.map((row) => (
                              <TableRow key={row.id}>
                                <TableCell className="text-xs font-mono" dir="ltr">
                                  {row.broker_organization_id}
                                </TableCell>
                                <TableCell className="text-xs font-medium">
                                  {t.attribution.brokerRoles[row.role as keyof typeof t.attribution.brokerRoles] ?? row.role}
                                </TableCell>
                                <TableCell className="text-xs font-mono" dir="ltr">
                                  {row.related_opportunity_id || "—"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>

                  {/* Opportunity Provenance Rows */}
                  <div>
                    <h3 className="text-sm font-semibold mb-3 text-foreground">{t.attribution.opportunityProvenanceTitle}</h3>
                    {!deal.opportunity_attributions || deal.opportunity_attributions.length === 0 ? (
                      <p className="text-xs text-muted-foreground">{t.attribution.noOpportunityRows}</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-start">{t.attribution.opportunityId}</TableHead>
                              <TableHead className="text-start">{t.attribution.opportunityRole}</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {deal.opportunity_attributions.map((row) => (
                              <TableRow key={row.id}>
                                <TableCell className="text-xs font-mono" dir="ltr">
                                  {row.opportunity_id}
                                </TableCell>
                                <TableCell className="text-xs font-medium">{row.role}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>

                  {/* Structured Evidence Snapshot */}
                  {deal.attribution?.evidence_snapshot != null && (
                    <div>
                      <h3 className="text-sm font-semibold mb-2 text-foreground">{t.attribution.evidenceSnapshot}</h3>
                      <div className="p-4 rounded-md bg-muted/40 text-xs font-mono max-h-64 overflow-y-auto" dir="ltr">
                        <pre>{JSON.stringify(deal.attribution.evidence_snapshot, null, 2)}</pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Controlled Manual Resolution Form (Operator/Admin Only, PENDING only) */}
              {isOperatorOrAdmin && isAttributionPending && (
                <div className="mt-8 border-t pt-6 bg-accent/20 p-5 rounded-lg border border-primary/20">
                  <h3 className="text-base font-semibold mb-1 text-primary flex items-center gap-2">
                    <CheckCircle2 className="size-4" />
                    <span>{t.attribution.manualResolutionTitle}</span>
                  </h3>
                  <p className="text-xs text-muted-foreground mb-4">
                    {t.attribution.manualResolutionDesc}
                  </p>

                  {resolveSuccess && (
                    <div className="mb-4 p-3 rounded-md bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 text-xs">
                      {t.attribution.resolveSuccess}
                    </div>
                  )}

                  {resolveError && (
                    <div className="mb-4 p-3 rounded-md bg-destructive/10 border border-destructive/30 text-destructive text-xs">
                      {resolveError}
                    </div>
                  )}

                  <form onSubmit={handleResolveAttribution} className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="primary-channel" className="text-xs font-medium">
                        {t.attribution.primaryChannel} *
                      </Label>
                      <Select
                        value={selectedChannel}
                        onValueChange={(val) => setSelectedChannel(val as PrimaryChannelEnum)}
                      >
                        <SelectTrigger id="primary-channel" className="text-xs">
                          <SelectValue placeholder={t.attribution.selectChannel} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="PLATFORM_NETWORK">{t.attribution.channels.PLATFORM_NETWORK}</SelectItem>
                          <SelectItem value="DIRECT_SUPPLIER">{t.attribution.channels.DIRECT_SUPPLIER}</SelectItem>
                          <SelectItem value="BROKER">{t.attribution.channels.BROKER}</SelectItem>
                          <SelectItem value="OPPORTUNITY_DESK">{t.attribution.channels.OPPORTUNITY_DESK}</SelectItem>
                          <SelectItem value="BUYER_EXISTING_SUPPLIER">{t.attribution.channels.BUYER_EXISTING_SUPPLIER}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="resolution-reason" className="text-xs font-medium">
                        {t.attribution.reasonLabel} *
                      </Label>
                      <Textarea
                        id="resolution-reason"
                        rows={3}
                        value={resolutionReason}
                        onChange={(e) => setResolutionReason(e.target.value)}
                        placeholder={t.attribution.reasonPlaceholder}
                        className="text-xs"
                      />
                    </div>

                    <Button
                      type="submit"
                      disabled={isResolving || !selectedChannel || !resolutionReason.trim()}
                      className="text-xs gap-1.5"
                    >
                      {isResolving && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isResolving ? t.attribution.resolving : t.attribution.resolveButton}</span>
                    </Button>
                  </form>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 5: Execution (Staged Honest Empty State) */}
      {activeTab === "execution" && (
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <PlayCircle className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.stagedTabs.execution.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.stagedTabs.execution.description}
          </p>
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              {t.badges.plannedEpic10}
            </Badge>
          </div>
        </Card>
      )}

      {/* Tab 6: Logistics (Staged Honest Empty State) */}
      {activeTab === "logistics" && (
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <Truck className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.stagedTabs.logistics.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.stagedTabs.logistics.description}
          </p>
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              {t.badges.plannedEpic10}
            </Badge>
          </div>
        </Card>
      )}

      {/* Tab 7: Quality (Staged Honest Empty State) */}
      {activeTab === "quality" && (
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <ShieldCheck className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.stagedTabs.quality.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.stagedTabs.quality.description}
          </p>
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              {t.badges.plannedEpic10}
            </Badge>
          </div>
        </Card>
      )}

      {/* Tab 8: Documents (Staged Honest Empty State) */}
      {activeTab === "documents" && (
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <FileText className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.stagedTabs.documents.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.stagedTabs.documents.description}
          </p>
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              {t.badges.plannedEpic10}
            </Badge>
          </div>
        </Card>
      )}

      {/* Tab 9: Issues (Staged Honest Empty State) */}
      {activeTab === "issues" && (
        <Card className="p-12 text-center shadow-none border-dashed">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <AlertTriangle className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.stagedTabs.issues.title}</h2>
          <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
            {t.stagedTabs.issues.description}
          </p>
          <div className="mt-4">
            <Badge variant="outline" className="text-xs">
              {t.badges.plannedEpic10}
            </Badge>
          </div>
        </Card>
      )}

      {/* Tab 10: Activity (Real domain events only) */}
      {activeTab === "activity" && (
        <div className="space-y-6">
          <Card className="shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">{t.activity.title}</CardTitle>
              <CardDescription className="text-xs">{t.activity.subtitle}</CardDescription>
            </CardHeader>
            <CardContent>
              {(() => {
                // Construct real chronological events from immutable backend facts
                const events: { id: string; time: string; title: string; desc: string; icon: React.ComponentType<{ className?: string }> }[] = [];

                if (deal.created_at) {
                  events.push({
                    id: "deal-created",
                    time: deal.created_at,
                    title: t.activity.events.dealMaterialized,
                    desc: t.activity.events.dealMaterializedDesc,
                    icon: CheckCircle2,
                  });
                }

                if (deal.terms?.created_at) {
                  events.push({
                    id: "terms-captured",
                    time: deal.terms.created_at,
                    title: t.activity.events.termsCaptured,
                    desc: t.activity.events.termsCapturedDesc,
                    icon: Scale,
                  });
                }

                if (deal.attribution?.created_at) {
                  events.push({
                    id: "attr-created",
                    time: deal.attribution.created_at,
                    title: t.activity.events.attributionCreated,
                    desc: t.activity.events.attributionCreatedDesc,
                    icon: Award,
                  });
                }

                if (deal.attribution?.resolved_at) {
                  events.push({
                    id: "attr-resolved",
                    time: deal.attribution.resolved_at,
                    title: t.activity.events.attributionResolved,
                    desc: `${t.activity.events.attributionResolvedDesc} (${primaryChannelLabel})`,
                    icon: CheckCircle2,
                  });
                }

                // Sort chronologically ascending
                events.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());

                if (events.length === 0) {
                  return <p className="text-xs text-muted-foreground">{t.activity.empty}</p>;
                }

                return (
                  <div className="relative border-s border-border ms-4 ps-6 space-y-8 my-2">
                    {events.map((event) => {
                      const Icon = event.icon;
                      return (
                        <div key={event.id} className="relative">
                          <span className="absolute -start-[31px] top-1 flex size-5 items-center justify-center rounded-full bg-background border border-primary text-primary">
                            <Icon className="size-3" />
                          </span>
                          <div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1">
                            <h4 className="text-sm font-semibold text-foreground">{event.title}</h4>
                            <span className="text-xs font-mono text-muted-foreground" dir="ltr">
                              {event.time}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                            {event.desc}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

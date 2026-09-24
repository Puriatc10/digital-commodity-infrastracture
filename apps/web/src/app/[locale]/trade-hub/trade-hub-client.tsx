"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Calendar,
  Layers,
  Loader2,
  MapPin,
  Package,
  PlusCircle,
  RefreshCw,
  Search,
  Tag,
  Truck,
  X,
} from "lucide-react";

import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VerificationBadge } from "@/components/verification-badge";

type RFQPublicResponse = components["schemas"]["RFQPublicResponse"];
type RFQBuilderResponse = components["schemas"]["RFQBuilderResponse"];
type SupplyListingPublicResponse = components["schemas"]["SupplyListingPublicResponse"];
type SupplyListingSupplierResponse = components["schemas"]["SupplyListingSupplierResponse"];
type CommodityDefinition = components["schemas"]["CommodityDefinition"];

interface TradeHubClientProps {
  locale: EnabledLocale;
}

export function TradeHubClient({ locale }: TradeHubClientProps) {
  const messages = getMessages(locale);
  const isRtl = locale === "fa";
  const t = messages.tradeHub;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // Active Tab: "demand" | "supply"
  const [activeTab, setActiveTab] = useState<"demand" | "supply">("demand");

  // Filter States
  const [search, setSearch] = useState("");
  const [selectedCommodity, setSelectedCommodity] = useState<string>("");
  const [selectedStatus, setSelectedStatus] = useState<string>("");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");

  // Data States
  const [commodities, setCommodities] = useState<CommodityDefinition[]>([]);
  const [rfqs, setRfqs] = useState<(RFQPublicResponse | RFQBuilderResponse)[]>([]);
  const [supplyListings, setSupplyListings] = useState<(SupplyListingPublicResponse | SupplyListingSupplierResponse)[]>([]);

  // Loading & Error States
  const [isLoadingCommodities, setIsLoadingCommodities] = useState(false);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // User & Organization Permissions
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");

  const currentOrg = state.status === "authenticated" ? state.currentOrganization : null;
  const currentOrgId = currentOrg?.organization.id ?? null;
  const capabilities = currentOrg?.capabilities ?? [];
  const orgRole = currentOrg?.role ?? null;

  const hasBuyerCapability = capabilities.includes("buyer");
  const hasSupplierCapability = capabilities.includes("supplier");
  const isOwnerOrManager = orgRole === "owner" || orgRole === "manager";
  const isMemberOrViewer = !isOwnerOrManager && (orgRole === "member" || orgRole === "viewer");

  const canCreateRfq = isOperatorOrAdmin || (hasBuyerCapability && isOwnerOrManager);
  const canCreateSupply = isOperatorOrAdmin || (hasSupplierCapability && isOwnerOrManager);

  // Invalidate queries when active organization changes to enforce session isolation
  const previousOrgIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (previousOrgIdRef.current && previousOrgIdRef.current !== currentOrgId) {
      queryClient.removeQueries({ queryKey: ["trade-hub-rfqs"] });
      queryClient.removeQueries({ queryKey: ["trade-hub-supply-listings"] });
      setRfqs([]);
      setSupplyListings([]);
    }
    if (currentOrgId) {
      previousOrgIdRef.current = currentOrgId;
    } else if (state.status === "unauthenticated") {
      previousOrgIdRef.current = null;
    }
  }, [currentOrgId, queryClient, state.status]);

  // Fetch Commodities for generic filter dropdown
  useEffect(() => {
    let ignore = false;
    async function loadCommodities() {
      setIsLoadingCommodities(true);
      try {
        const { data, response } = await apiClient.GET("/api/commodities/");
        if (!ignore && response.ok && Array.isArray(data)) {
          setCommodities(data);
        }
      } catch {
        // Fallback: user can still use text search
      } finally {
        if (!ignore) setIsLoadingCommodities(false);
      }
    }
    void loadCommodities();
    return () => {
      ignore = true;
    };
  }, []);

  // Refresh trigger for retries
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const triggerRefresh = useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // Fetch Trade Hub data based on active tab and filters
  useEffect(() => {
    let ignore = false;
    async function loadData() {
      setIsLoadingData(true);
      setErrorMessage(null);
      try {
        const queryParams: {
          search?: string;
          commodity?: string;
          status?: string;
          origin?: string;
          destination?: string;
        } = {};
        if (search.trim()) queryParams.search = search.trim();
        if (selectedCommodity) queryParams.commodity = selectedCommodity;
        if (selectedStatus) queryParams.status = selectedStatus;
        if (origin.trim()) queryParams.origin = origin.trim();
        if (destination.trim()) queryParams.destination = destination.trim();

        if (activeTab === "demand") {
          const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/", {
            params: { query: queryParams },
          });
          if (!ignore) {
            if (response.ok && data) {
              const results =
                (data as { results?: (RFQPublicResponse | RFQBuilderResponse)[] }).results ?? [];
              setRfqs(results);
            } else {
              setErrorMessage(t.states.loadError);
            }
          }
        } else {
          const { data, response } = await apiClient.GET("/api/trade-hub/supply-listings/", {
            params: { query: queryParams },
          });
          if (!ignore) {
            if (response.ok && data) {
              const results =
                (data as {
                  results?: (SupplyListingPublicResponse | SupplyListingSupplierResponse)[];
                }).results ?? [];
              setSupplyListings(results);
            } else {
              setErrorMessage(t.states.loadError);
            }
          }
        }
      } catch {
        if (!ignore) {
          setErrorMessage(t.states.loadError);
        }
      } finally {
        if (!ignore) {
          setIsLoadingData(false);
        }
      }
    }

    void loadData();
    return () => {
      ignore = true;
    };
  }, [
    activeTab,
    currentOrgId,
    search,
    selectedCommodity,
    selectedStatus,
    origin,
    destination,
    refreshTrigger,
    t.states.loadError,
  ]);

  const handleResetFilters = () => {
    setSearch("");
    setSelectedCommodity("");
    setSelectedStatus("");
    setOrigin("");
    setDestination("");
  };

  const hasActiveFilters = Boolean(
    search || selectedCommodity || selectedStatus || origin || destination
  );

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case "published":
      case "active":
        return "default";
      case "draft":
        return "secondary";
      case "collecting_offers":
      case "negotiating":
        return "outline";
      case "awarded":
        return "default";
      case "closed":
      case "expired":
      case "cancelled":
        return "destructive";
      default:
        return "secondary";
    }
  };

  const getVisibilityLabel = (vis: string) => {
    return t.visibility[vis as keyof typeof t.visibility] ?? vis;
  };

  const getStatusLabel = (st: string) => {
    return t.status[st as keyof typeof t.status] ?? st;
  };

  return (
    <div className="flex flex-col gap-6" dir="rtl">
      {/* Header Section */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between border-b pb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-3">
            <Package className="h-7 w-7 text-primary" />
            {t.title}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{t.subtitle}</p>
        </div>

        {/* Actor-Aware Primary Actions */}
        <div className="flex items-center gap-3">
          {activeTab === "demand" && (
            <>
              {canCreateRfq ? (
                <Button
                  onClick={() => router.push(`/${locale}/trade-hub/rfqs/new`)}
                  className="flex items-center gap-2"
                >
                  <PlusCircle className="h-4 w-4" />
                  {t.actions.createRfq}
                </Button>
              ) : isMemberOrViewer && hasBuyerCapability ? (
                <span className="text-xs text-muted-foreground bg-muted px-3 py-2 rounded-md">
                  {t.states.memberRoleNotice}
                </span>
              ) : null}
            </>
          )}

          {activeTab === "supply" && (
            <>
              {canCreateSupply ? (
                <Button
                  onClick={() => router.push(`/${locale}/trade-hub/supply-listings/new`)}
                  className="flex items-center gap-2"
                >
                  <PlusCircle className="h-4 w-4" />
                  {t.actions.createSupply}
                </Button>
              ) : isMemberOrViewer && hasSupplierCapability ? (
                <span className="text-xs text-muted-foreground bg-muted px-3 py-2 rounded-md">
                  {t.states.memberRoleNotice}
                </span>
              ) : null}
            </>
          )}
        </div>
      </div>

      {/* Unauthorized Context Warning */}
      {!currentOrg && !isOperatorOrAdmin && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <p className="text-sm font-medium">{t.states.unauthorizedContext}</p>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="flex border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("demand")}
          className={`flex items-center gap-2 px-6 py-3 font-semibold text-sm transition-colors border-b-2 -mb-px ${
            activeTab === "demand"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          aria-selected={activeTab === "demand"}
          role="tab"
        >
          <Layers className="h-4 w-4" />
          {t.tabs.demand}
          {activeTab === "demand" && !isLoadingData && (
            <span className="rounded-full bg-primary/10 text-primary text-xs px-2 py-0.5">
              {rfqs.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("supply")}
          className={`flex items-center gap-2 px-6 py-3 font-semibold text-sm transition-colors border-b-2 -mb-px ${
            activeTab === "supply"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          aria-selected={activeTab === "supply"}
          role="tab"
        >
          <Truck className="h-4 w-4" />
          {t.tabs.supply}
          {activeTab === "supply" && !isLoadingData && (
            <span className="rounded-full bg-primary/10 text-primary text-xs px-2 py-0.5">
              {supplyListings.length}
            </span>
          )}
        </button>
      </div>

      {/* Search & Filter Bar */}
      <Card className="p-4 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
          {/* Text Search */}
          <div className="relative lg:col-span-2">
            <Search className="absolute start-3 top-2.5 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t.filters.searchPlaceholder}
              className="ps-9 pe-3 text-sm"
              aria-label={t.filters.searchPlaceholder}
            />
          </div>

          {/* Commodity Generic Filter */}
          <div>
            <select
              aria-label={t.filters.commodity}
              className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
              value={selectedCommodity}
              onChange={(e) => setSelectedCommodity(e.target.value)}
              disabled={isLoadingCommodities}
            >
              <option value="">{t.filters.allCommodities}</option>
              {commodities.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name_fa || c.code}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <div>
            <select
              aria-label={t.filters.status}
              className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
            >
              <option value="">{t.filters.allStatuses}</option>
              {activeTab === "demand" ? (
                <>
                  <option value="draft">{t.status.draft}</option>
                  <option value="published">{t.status.published}</option>
                  <option value="closed">{t.status.closed}</option>
                  <option value="cancelled">{t.status.cancelled}</option>
                </>
              ) : (
                <>
                  <option value="draft">{t.status.draft}</option>
                  <option value="active">{t.status.active}</option>
                  <option value="closed">{t.status.closed}</option>
                  <option value="expired">{t.status.expired}</option>
                </>
              )}
            </select>
          </div>

          {/* Reset Filters Action */}
          <div className="flex items-center gap-2">
            {hasActiveFilters && (
              <button
                type="button"
                onClick={handleResetFilters}
                className="w-full flex items-center justify-center gap-1.5 text-xs text-muted-foreground hover:text-foreground py-2 px-3 rounded-md hover:bg-accent transition-colors"
              >
                <X className="h-3.5 w-3.5" />
                {t.actions.resetFilters}
              </button>
            )}
          </div>
        </div>

        {/* Secondary Geo Filters */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 pt-3 border-t">
          <div className="flex items-center gap-2">
            <Label htmlFor="filter-origin" className="text-xs text-muted-foreground shrink-0 w-12">
              {t.filters.origin}:
            </Label>
            <Input
              id="filter-origin"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder={t.filters.originPlaceholder}
              className="h-8 text-xs"
            />
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="filter-dest" className="text-xs text-muted-foreground shrink-0 w-12">
              {t.filters.destination}:
            </Label>
            <Input
              id="filter-dest"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              placeholder={t.filters.destPlaceholder}
              className="h-8 text-xs"
            />
          </div>
        </div>
      </Card>

      {/* Content Area */}
      {isLoadingData ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">{t.states.loading}</span>
        </div>
      ) : errorMessage ? (
        <Card className="border-destructive/30 bg-destructive/5 p-8 text-center">
          <div className="flex flex-col items-center gap-3">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="text-sm font-medium text-destructive">{errorMessage}</p>
            <Button
              variant="outline"
              onClick={triggerRefresh}
              className="mt-2 min-h-8 px-3 py-1 text-xs"
            >
              <RefreshCw className="h-4 w-4" />
              {t.actions.retry}
            </Button>
          </div>
        </Card>
      ) : activeTab === "demand" ? (
        rfqs.length === 0 ? (
          <Card className="p-12 text-center border-dashed">
            <div className="flex flex-col items-center gap-2">
              <Layers className="h-10 w-10 text-muted-foreground/50" />
              <h3 className="text-base font-semibold text-foreground">
                {hasActiveFilters ? t.states.noResults : t.states.emptyDemand}
              </h3>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={handleResetFilters}
                  className="mt-1 text-xs text-primary underline hover:text-primary/80"
                >
                  {t.actions.resetFilters}
                </button>
              )}
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {rfqs.map((rfq) => (
              <Card
                key={rfq.id}
                className="flex flex-col justify-between hover:border-primary/50 transition-colors shadow-sm py-0"
              >
                <CardHeader className="pt-5 pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-col">
                      <CardTitle className="text-base font-bold flex items-center gap-2">
                        {rfq.commodity_name_fa || rfq.commodity_code}
                      </CardTitle>
                      <span className="text-xs text-muted-foreground mt-0.5">
                        {rfq.organization.name}
                      </span>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <Badge variant={getStatusBadgeVariant(rfq.status)}>
                        {getStatusLabel(rfq.status)}
                      </Badge>
                      <span className="text-[11px] text-muted-foreground bg-secondary/50 px-1.5 py-0.5 rounded">
                        {getVisibilityLabel(rfq.visibility)}
                      </span>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pb-4 text-xs">
                  {/* Quantity & Terms */}
                  <div className="grid grid-cols-2 gap-2 bg-muted/40 p-2.5 rounded-md">
                    <div>
                      <span className="text-muted-foreground block">{t.labels.quantity}:</span>
                      <span className="font-semibold text-foreground">
                        <bdi dir="ltr">{Number(rfq.quantity).toLocaleString()} {rfq.unit}</bdi>
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block">{t.labels.targetPrice}:</span>
                      <span className="font-semibold text-foreground">
                        {rfq.target_price ? (
                          <bdi dir="ltr">{Number(rfq.target_price).toLocaleString()} {rfq.currency}</bdi>
                        ) : (
                          t.labels.notSpecified
                        )}
                      </span>
                    </div>
                  </div>

                  {/* Commercial & Delivery Logistics */}
                  <div className="space-y-1.5 text-muted-foreground">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <Tag className="h-3.5 w-3.5 shrink-0" />
                        {t.labels.incoterm}:
                      </span>
                      <span className="text-foreground font-medium">{rfq.incoterm || "—"}</span>
                    </div>

                    {(rfq.origin || rfq.destination) && (
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5">
                          <MapPin className="h-3.5 w-3.5 shrink-0" />
                          {t.labels.origin} / {t.labels.destination}:
                        </span>
                        <span className="text-foreground font-medium truncate max-w-[150px] inline-flex items-center gap-1">
                          <span>{rfq.origin || "—"}</span>
                          <span aria-hidden="true" className="text-muted-foreground">
                            {isRtl ? "←" : "→"}
                          </span>
                          <span>{rfq.destination || "—"}</span>
                        </span>
                      </div>
                    )}

                    {rfq.submission_deadline && (
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5 shrink-0" />
                          {t.labels.deadline}:
                        </span>
                        <span className="text-foreground font-medium">
                          {new Date(rfq.submission_deadline).toLocaleDateString("fa-IR")}
                        </span>
                      </div>
                    )}
                  </div>
                </CardContent>

                <div className="border-t bg-muted/20 px-6 py-3 flex items-center justify-between rounded-b-xl">
                  <div className="flex items-center gap-1.5">
                    <VerificationBadge status={rfq.organization.verification_status || "unverified"} />
                  </div>
                  <Button
                    variant="outline"
                    className="min-h-8 px-3 py-1 text-xs"
                    onClick={() => router.push(`/${locale}/trade-hub/rfqs/${rfq.id}`)}
                  >
                    {t.actions.viewWorkspace}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : (
        supplyListings.length === 0 ? (
          <Card className="p-12 text-center border-dashed">
            <div className="flex flex-col items-center gap-2">
              <Truck className="h-10 w-10 text-muted-foreground/50" />
              <h3 className="text-base font-semibold text-foreground">
                {hasActiveFilters ? t.states.noResults : t.states.emptySupply}
              </h3>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={handleResetFilters}
                  className="mt-1 text-xs text-primary underline hover:text-primary/80"
                >
                  {t.actions.resetFilters}
                </button>
              )}
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {supplyListings.map((listing) => (
              <Card
                key={listing.id}
                className="flex flex-col justify-between hover:border-primary/50 transition-colors shadow-sm py-0"
              >
                <CardHeader className="pt-5 pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-col">
                      <CardTitle className="text-base font-bold flex items-center gap-2">
                        {listing.commodity_name_fa || listing.commodity_code}
                      </CardTitle>
                      <span className="text-xs text-muted-foreground mt-0.5">
                        {listing.organization.name}
                      </span>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <Badge variant={getStatusBadgeVariant(listing.status)}>
                        {getStatusLabel(listing.status)}
                      </Badge>
                      <span className="text-[11px] text-muted-foreground bg-secondary/50 px-1.5 py-0.5 rounded">
                        {getVisibilityLabel(listing.visibility)}
                      </span>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pb-4 text-xs">
                  {/* Quantity & Indicative Price */}
                  <div className="grid grid-cols-2 gap-2 bg-muted/40 p-2.5 rounded-md">
                    <div>
                      <span className="text-muted-foreground block">{t.labels.quantity}:</span>
                      <span className="font-semibold text-foreground">
                        <bdi dir="ltr">{Number(listing.quantity).toLocaleString()} {listing.unit}</bdi>
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block">{t.labels.indicativePrice}:</span>
                      <span className="font-semibold text-foreground">
                        {listing.indicative_price ? (
                          <bdi dir="ltr">{Number(listing.indicative_price).toLocaleString()} {listing.currency}</bdi>
                        ) : (
                          t.labels.notSpecified
                        )}
                      </span>
                    </div>
                  </div>

                  {/* Commercial & Availability Logistics */}
                  <div className="space-y-1.5 text-muted-foreground">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <Tag className="h-3.5 w-3.5 shrink-0" />
                        {t.labels.incoterm}:
                      </span>
                      <span className="text-foreground font-medium">{listing.incoterm || "—"}</span>
                    </div>

                    {(listing.origin || listing.destination) && (
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5">
                          <MapPin className="h-3.5 w-3.5 shrink-0" />
                          {t.labels.origin}:
                        </span>
                        <span className="text-foreground font-medium truncate max-w-[150px]">
                          {listing.origin || "—"}
                        </span>
                      </div>
                    )}

                    {(listing.availability_window_start || listing.availability_window_end) && (
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5 shrink-0" />
                          {t.labels.availability}:
                        </span>
                        <span className="text-foreground font-medium">
                          {listing.availability_window_start
                            ? new Date(listing.availability_window_start).toLocaleDateString("fa-IR")
                            : "—"}{" "}
                          تا{" "}
                          {listing.availability_window_end
                            ? new Date(listing.availability_window_end).toLocaleDateString("fa-IR")
                            : "—"}
                        </span>
                      </div>
                    )}
                  </div>
                </CardContent>

                <div className="border-t bg-muted/20 px-6 py-3 flex items-center justify-between rounded-b-xl">
                  <div className="flex items-center gap-1.5">
                    <VerificationBadge status={listing.organization.verification_status || "unverified"} />
                  </div>
                  <Button
                    variant="outline"
                    className="min-h-8 px-3 py-1 text-xs"
                    onClick={() => router.push(`/${locale}/trade-hub/supply-listings/${listing.id}`)}
                  >
                    {t.actions.viewDetails}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )
      )}
    </div>
  );
}

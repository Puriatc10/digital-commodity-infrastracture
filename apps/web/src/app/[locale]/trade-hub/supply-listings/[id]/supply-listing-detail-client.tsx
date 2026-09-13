"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
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
import {
  AlertTriangle,
  Edit,
  Loader2,
  Package,
  RefreshCw,
  XCircle,
} from "lucide-react";

type SupplyListingSupplierResponse = components["schemas"]["SupplyListingSupplierResponse"];
type SupplyListingPublicResponse = components["schemas"]["SupplyListingPublicResponse"];
type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];

export interface SupplyListingDetailClientProps {
  locale?: EnabledLocale;
  listingId: string;
}

export function SupplyListingDetailClient({
  locale = "fa",
  listingId,
}: SupplyListingDetailClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.supplyListingDetail;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // Core Data State
  const [listing, setListing] = useState<
    SupplyListingSupplierResponse | SupplyListingPublicResponse | null
  >(null);
  const [schema, setSchema] = useState<CommoditySchemaVersion | null>(null);

  // Loading States
  const [isLoadingListing, setIsLoadingListing] = useState<boolean>(true);
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);
  const [isNotFound, setIsNotFound] = useState<boolean>(false);

  // Lifecycle Action States
  const [isActionLoading, setIsActionLoading] = useState<boolean>(false);
  const [showCloseModal, setShowCloseModal] = useState<boolean>(false);
  const [staleConflict, setStaleConflict] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Role & Ownership Resolution
  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");
  const isOwner = Boolean(
    listing?.organization &&
      currentOrgId &&
      listing.organization.id === currentOrgId
  );
  const isOwnerOrOperator = isOwner || isOperatorOrAdmin;

  // Session Invalidation: Clear listing when organization switches
  const previousOrgIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (previousOrgIdRef.current && previousOrgIdRef.current !== currentOrgId) {
      queryClient.removeQueries({ queryKey: ["supply-listing", listingId] });
      setListing(null);
      setSchema(null);
      setStaleConflict(false);
      setActionError(null);
    }
    if (currentOrgId) {
      previousOrgIdRef.current = currentOrgId;
    } else if (state.status === "unauthenticated") {
      previousOrgIdRef.current = null;
    }
  }, [currentOrgId, queryClient, listingId, state.status]);

  // Refresh trigger for reloads / conflict resolution
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const triggerRefresh = useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // 1. Fetch Authoritative Supply Listing
  useEffect(() => {
    let ignore = false;
    async function fetchListing() {
      setIsLoadingListing(true);
      setIsNotFound(false);
      try {
        const { data, response } = await apiClient.GET(
          "/api/trade-hub/supply-listings/{listing_id}/",
          {
            params: { path: { listing_id: listingId } },
          }
        );
        if (ignore) return;
        if (response.status === 404) {
          setIsNotFound(true);
          setListing(null);
          return;
        }
        if (response.ok && data) {
          setListing(data);
          setIsNotFound(false);
        }
      } catch {
        if (!ignore) {
          setIsNotFound(true);
          setListing(null);
        }
      } finally {
        if (!ignore) {
          setIsLoadingListing(false);
        }
      }
    }
    void fetchListing();
    return () => {
      ignore = true;
    };
  }, [listingId, currentOrgId, refreshTrigger]);

  // 2. Fetch Exact Historical Schema (Exact Schema Binding)
  const schemaVersionId = listing?.schema_version_id;
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
        if (!ignore && response.ok && data) {
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

  // Close Listing Action
  const handleCloseListing = async () => {
    if (!listing) return;
    setIsActionLoading(true);
    setActionError(null);
    setStaleConflict(false);

    try {
      const { data, response, error } = await apiClient.POST(
        "/api/trade-hub/supply-listings/{listing_id}/close/",
        {
          params: { path: { listing_id: listingId } },
          body: {
            expected_version: listing.version,
          },
        }
      );

      if (response.ok && data) {
        setListing(data);
        setShowCloseModal(false);
        return;
      }

      if (response.status === 409) {
        setStaleConflict(true);
        setActionError(t.conflicts.staleDescription);
        setShowCloseModal(false);
        triggerRefresh();
        return;
      }

      if (error && typeof error === "object" && "detail" in error) {
        setActionError(String(error.detail));
      } else {
        setActionError(t.errors.actionFailed);
      }
    } catch {
      setActionError(t.errors.actionFailed);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Loading Screen
  if (isLoadingListing) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-4 text-muted-foreground" dir={isRtl ? "rtl" : "ltr"}>
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm font-medium">{t.loadingListing}</p>
      </div>
    );
  }

  // Not Found / Safe 404 Screen (covers hidden listings as well)
  if (isNotFound || !listing) {
    return (
      <div className="mx-auto my-12 max-w-lg" dir={isRtl ? "rtl" : "ltr"}>
        <Card className="border-border text-center shadow-md">
          <CardHeader>
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Package className="h-6 w-6" />
            </div>
            <CardTitle className="text-xl">{t.listingNotFoundTitle}</CardTitle>
            <CardDescription className="mt-2 text-muted-foreground">
              {t.listingNotFoundDescription}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-6">
            <Button variant="outline" onClick={() => router.push(`/${locale}/trade-hub`)}>
              {t.backToHub}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Safe Status Badge styling
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return <Badge className="bg-emerald-600 text-white hover:bg-emerald-700">{t.statuses.active}</Badge>;
      case "draft":
        return <Badge variant="secondary">{t.statuses.draft}</Badge>;
      case "closed":
        return <Badge variant="outline" className="text-muted-foreground">{t.statuses.closed}</Badge>;
      case "expired":
        return <Badge variant="destructive">{t.statuses.expired}</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  // Visibility Badge styling
  const getVisibilityBadge = (vis: string) => {
    switch (vis) {
      case "public":
        return <Badge variant="outline" className="border-blue-500 text-blue-600">{t.visibilities.public}</Badge>;
      case "network":
        return <Badge variant="outline" className="border-purple-500 text-purple-600">{t.visibilities.network}</Badge>;
      case "private":
        return <Badge variant="outline" className="border-amber-500 text-amber-600">{t.visibilities.private}</Badge>;
      default:
        return <Badge variant="outline">{vis}</Badge>;
    }
  };

  const hasNotes = isOwnerOrOperator && "notes" in listing && Boolean(listing.notes);
  const createdByOperator = isOwnerOrOperator && "created_by_operator" in listing && listing.created_by_operator;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* Top Action Bar */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {isRtl ? listing.commodity_name_fa : listing.commodity_name_en}
            </h1>
            {getStatusBadge(listing.status)}
            {getVisibilityBadge(listing.visibility)}
            {createdByOperator && (
              <Badge variant="secondary" className="bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                {t.operatorBadge}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {t.versionLabel} {listing.version} | {listing.organization?.name}
          </p>
        </div>

        {/* Action Controls for Authorized Owner/Operator */}
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={triggerRefresh} className="flex items-center gap-1.5 h-8 px-2.5 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />
            <span>{t.refresh}</span>
          </Button>

          {isOwnerOrOperator && listing.status === "draft" && (
            <Button
              variant="outline"
              onClick={() => router.push(`/${locale}/trade-hub/supply-listings/${listing.id}/edit`)}
              className="flex items-center gap-1.5 h-8 px-2.5 text-xs"
            >
              <Edit className="h-3.5 w-3.5" />
              <span>{t.actions.editDraft}</span>
            </Button>
          )}

          {isOwnerOrOperator && (listing.status === "draft" || listing.status === "active") && (
            <Button
              onClick={() => setShowCloseModal(true)}
              className="flex items-center gap-1.5 h-8 px-2.5 text-xs bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              <XCircle className="h-3.5 w-3.5" />
              <span>{t.actions.closeListing}</span>
            </Button>
          )}
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

      {/* Action Error Banner */}
      {actionError && !staleConflict && (
        <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <span className="text-sm font-medium">{actionError}</span>
        </div>
      )}

      {/* Product Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t.sections.product}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div>
              <span className="text-xs text-muted-foreground">{messages.supplyListingBuilder.product.commodityLabel}:</span>
              <p className="font-medium text-foreground">
                {isRtl ? listing.commodity_name_fa : listing.commodity_name_en} ({listing.commodity_code})
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">{messages.supplyListingBuilder.product.schemaVersion}:</span>
              <p className="font-medium text-foreground">
                v{listing.schema_version_number}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">{messages.supplyListingBuilder.product.quantityLabel}:</span>
              <p className="font-medium text-foreground">
                {listing.quantity} {listing.unit}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">{messages.supplyListingBuilder.visibility.tierLabel}:</span>
              <p className="font-medium capitalize text-foreground">{listing.visibility}</p>
            </div>
          </div>

          {/* Dynamic Technical Specifications View */}
          <div className="border-t pt-4">
            <h4 className="mb-3 text-sm font-semibold text-foreground">
              {messages.supplyListingBuilder.product.specificationsTitle}
            </h4>
            {isLoadingSchema ? (
              <div className="flex h-24 items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <span>{messages.supplyListingBuilder.product.loadingSchema}</span>
              </div>
            ) : schema ? (
              <CommoditySpecificationView
                schema={schema}
                value={(listing.specifications as Record<string, unknown>) || {}}
                locale={locale}
              />
            ) : (
              <p className="text-xs text-muted-foreground">{t.errors.loadSchemaFailed}</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Commercial & Terms Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t.sections.commercial}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.indicativePriceLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.indicative_price
                  ? `${listing.indicative_price} ${listing.currency}`
                  : messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.paymentTermsLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.payment_terms || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.incotermLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.incoterm || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">{t.versionLabel}:</span>
              <p className="font-medium text-foreground">{listing.version}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Geography & Availability Window Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t.sections.availability}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.originLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.origin || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.destinationLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.destination || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.availabilityWindowStartLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.availability_window_start || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">
                {messages.supplyListingBuilder.commercial.availabilityWindowEndLabel}:
              </span>
              <p className="font-medium text-foreground">
                {listing.availability_window_end || messages.supplyListingBuilder.preview.notSpecified}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Quality Notes & Internal Notes (Safe Projection) */}
      {(listing.quality_notes || hasNotes) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{t.sections.quality}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {listing.quality_notes && (
              <div>
                <span className="text-xs text-muted-foreground">
                  {messages.supplyListingBuilder.commercial.qualityNotesLabel}:
                </span>
                <p className="mt-1 text-sm text-foreground whitespace-pre-wrap">
                  {listing.quality_notes}
                </p>
              </div>
            )}

            {hasNotes && (
              <div className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
                <span className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                  {messages.supplyListingBuilder.commercial.notesLabel}:
                </span>
                <p className="mt-1 text-sm text-amber-800 dark:text-amber-300 whitespace-pre-wrap">
                  {"notes" in listing ? String(listing.notes) : ""}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {t.internalNotesNotice}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Close Modal Confirmation */}
      {showCloseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md shadow-xl" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader>
              <CardTitle className="text-lg text-destructive">{t.actions.confirmCloseTitle}</CardTitle>
              <CardDescription>{t.actions.confirmCloseDesc}</CardDescription>
            </CardHeader>
            <CardContent className="flex justify-end gap-3 pb-6">
              <Button
                variant="outline"
                onClick={() => setShowCloseModal(false)}
                disabled={isActionLoading}
              >
                {t.actions.cancelAction}
              </Button>
              <Button
                onClick={() => void handleCloseListing()}
                disabled={isActionLoading}
                className="flex items-center gap-2 bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {isActionLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>{isActionLoading ? t.actions.closing : t.actions.confirmCloseAction}</span>
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

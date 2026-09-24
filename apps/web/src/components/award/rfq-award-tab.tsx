"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  Award,
  CheckCircle2,
  FileCheck,
  Loader2,
  Lock,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";

type AwardDetailResponse = components["schemas"]["AwardDetailResponse"];
type AwardAllocationResponse = components["schemas"]["AwardAllocationResponse"];
type ComparisonRow = components["schemas"]["ComparisonRow"];

export interface RFQAwardTabProps {
  rfqId: string;
  rfqStatus: string;
  rfqQuantity: string | number;
  rfqUnit: string;
  canManage: boolean;
  isOperator: boolean;
  locale?: EnabledLocale;
  onAwardFinalized?: () => void;
}

export function RFQAwardTab({
  rfqId,
  rfqStatus,
  rfqQuantity,
  rfqUnit,
  canManage,
  isOperator,
  locale = "fa",
  onAwardFinalized,
}: RFQAwardTabProps) {
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace.award;
  const isRtl = locale === "fa";
  const { state } = useAuth();
  const canManageAward = canManage || isOperator;

  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;

  // Award State
  const [award, setAward] = useState<AwardDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUnauthorized, setIsUnauthorized] = useState<boolean>(false);
  const [awardNotFound, setAwardNotFound] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [staleConflict, setStaleConflict] = useState<boolean>(false);

  // Available Offers (for allocation)
  const [availableOffers, setAvailableOffers] = useState<ComparisonRow[]>([]);
  const [isLoadingOffers, setIsLoadingOffers] = useState<boolean>(false);

  // Add Allocation Form State
  const [showAddForm, setShowAddForm] = useState<boolean>(false);
  const [selectedOfferVersionId, setSelectedOfferVersionId] = useState<string>("");
  const [allocationQty, setAllocationQty] = useState<string>("");
  const [isAddingAllocation, setIsAddingAllocation] = useState<boolean>(false);

  // Edit Allocation State
  const [editingAllocId, setEditingAllocId] = useState<string | null>(null);
  const [editQty, setEditQty] = useState<string>("");
  const [isUpdatingAlloc, setIsUpdatingAlloc] = useState<boolean>(false);

  // Finalize Modal State
  const [showFinalizeModal, setShowFinalizeModal] = useState<boolean>(false);
  const [isFinalizing, setIsFinalizing] = useState<boolean>(false);

  // In-flight race isolation generation counters
  const fetchGenerationRef = useRef<number>(0);

  // 1. Authoritative Award Fetch
  const fetchAward = useCallback(async () => {
    const generation = ++fetchGenerationRef.current;
    setIsLoading(true);
    setActionError(null);
    setIsUnauthorized(false);
    setStaleConflict(false);

    try {
      const { data, response } = await apiClient.GET("/api/offers/rfqs/{rfq_id}/awards/", {
        params: { path: { rfq_id: rfqId } },
      });

      if (generation !== fetchGenerationRef.current) return;

      if (response.status === 403) {
        setIsUnauthorized(true);
        setAward(null);
        return;
      }

      if (response.status === 404) {
        setAwardNotFound(true);
        setAward(null);
        return;
      }

      if (response.ok && data) {
        setAward(data);
        setAwardNotFound(false);
      }
    } catch {
      if (generation === fetchGenerationRef.current) {
        setActionError(t.validationError);
      }
    } finally {
      if (generation === fetchGenerationRef.current) {
        setIsLoading(false);
      }
    }
  }, [rfqId, t.validationError]);

  // 2. Fetch Comparison Rows (candidate submitted offers for adding allocations)
  const fetchAvailableOffers = useCallback(async () => {
    if (!canManageAward) return;
    setIsLoadingOffers(true);
    try {
      const { data, response } = await apiClient.GET("/api/rfqs/{rfq_id}/comparison/", {
        params: { path: { rfq_id: rfqId } },
      });
      if (response.ok && data) {
        const rows = data.offers || data.items || [];
        setAvailableOffers(rows);
      }
    } catch {
      // Handled silently
    } finally {
      setIsLoadingOffers(false);
    }
  }, [canManageAward, rfqId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchAward();
    void fetchAvailableOffers();
  }, [fetchAward, fetchAvailableOffers, currentOrgId]);

  // Handle Initialize Draft Award
  const handleInitializeAward = async () => {
    setIsLoading(true);
    setActionError(null);
    try {
      const { data, response } = await apiClient.POST("/api/offers/rfqs/{rfq_id}/awards/", {
        params: { path: { rfq_id: rfqId } },
        body: {},
      });
      if (response.ok && data) {
        setAward(data);
        setAwardNotFound(false);
        setActionSuccess(t.initializeAward);
      } else {
        setActionError(t.validationError);
      }
    } catch {
      setActionError(t.validationError);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle Add Allocation
  const handleAddAllocation = async () => {
    if (!award || !selectedOfferVersionId || !allocationQty) return;
    setIsAddingAllocation(true);
    setActionError(null);
    setStaleConflict(false);

    try {
      const { response, error } = await apiClient.POST(
        "/api/offers/awards/{award_id}/allocations/",
        {
          params: { path: { award_id: award.id } },
          body: {
            offer_version_id: selectedOfferVersionId,
            awarded_quantity: allocationQty,
            expected_version: award.version,
          },
        }
      );

      if (response.status === 409) {
        setStaleConflict(true);
        void fetchAward();
        return;
      }

      if (response.ok) {
        setShowAddForm(false);
        setSelectedOfferVersionId("");
        setAllocationQty("");
        void fetchAward();
      } else {
        const errorDetail = (error as { detail?: string })?.detail || t.validationError;
        setActionError(String(errorDetail));
      }
    } catch {
      setActionError(t.validationError);
    } finally {
      setIsAddingAllocation(false);
    }
  };

  // Handle Update Allocation
  const handleUpdateAllocation = async (allocationId: string) => {
    if (!award || !editQty) return;
    setIsUpdatingAlloc(true);
    setActionError(null);
    setStaleConflict(false);

    try {
      const { response, error } = await apiClient.PATCH(
        "/api/offers/awards/allocations/{allocation_id}/",
        {
          params: { path: { allocation_id: allocationId } },
          body: {
            awarded_quantity: editQty,
            expected_version: award.version,
          },
        }
      );

      if (response.status === 409) {
        setStaleConflict(true);
        void fetchAward();
        return;
      }

      if (response.ok) {
        setEditingAllocId(null);
        setEditQty("");
        void fetchAward();
      } else {
        const errorDetail = (error as { detail?: string })?.detail || t.validationError;
        setActionError(String(errorDetail));
      }
    } catch {
      setActionError(t.validationError);
    } finally {
      setIsUpdatingAlloc(false);
    }
  };

  // Handle Remove Allocation
  const handleRemoveAllocation = async (allocationId: string) => {
    if (!award) return;
    setActionError(null);
    setStaleConflict(false);

    try {
      const { response, error } = await apiClient.DELETE(
        "/api/offers/awards/allocations/{allocation_id}/",
        {
          params: {
            path: { allocation_id: allocationId },
            query: { expected_version: award.version },
          },
        }
      );

      if (response.status === 409) {
        setStaleConflict(true);
        void fetchAward();
        return;
      }

      if (response.ok) {
        void fetchAward();
      } else {
        const errorDetail = (error as { detail?: string })?.detail || t.validationError;
        setActionError(String(errorDetail));
      }
    } catch {
      setActionError(t.validationError);
    }
  };

  // Handle Finalize Award
  const handleFinalizeAward = async () => {
    if (!award) return;
    setIsFinalizing(true);
    setActionError(null);
    setStaleConflict(false);

    try {
      const { data, response, error } = await apiClient.POST(
        "/api/offers/awards/{award_id}/finalize/",
        {
          params: { path: { award_id: award.id } },
          body: {
            expected_version: award.version,
          },
        }
      );

      if (response.status === 409) {
        setStaleConflict(true);
        setShowFinalizeModal(false);
        void fetchAward();
        return;
      }

      if (response.ok && data) {
        setAward(data);
        setShowFinalizeModal(false);
        setActionSuccess(t.finalizedStatus);
        if (onAwardFinalized) {
          onAwardFinalized();
        }
      } else {
        const errorDetail = (error as { detail?: string })?.detail || t.validationError;
        setActionError(String(errorDetail));
      }
    } catch {
      setActionError(t.validationError);
    } finally {
      setIsFinalizing(false);
    }
  };

  // -------------------------------------------------------------------------
  // Render States: Unauthorized, Loading, NotFound, and Main
  // -------------------------------------------------------------------------

  if (isUnauthorized) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="p-8 text-center text-destructive">
          <AlertTriangle className="h-8 w-8 mx-auto mb-2 text-destructive" />
          <p className="font-bold">{messages.rfqWorkspace.unauthorizedTitle}</p>
          <p className="text-xs text-muted-foreground mt-1">{t.unauthorized}</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <div className="flex items-center gap-3 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span>{messages.rfqWorkspace.loadingRfq}</span>
        </div>
      </div>
    );
  }

  // If no award exists yet
  if (awardNotFound || !award) {
    return (
      <Card className="border-dashed">
        <CardHeader className="text-center pb-2">
          <CardTitle className="text-base font-semibold flex items-center justify-center gap-2">
            <Award className="h-5 w-5 text-primary" />
            {t.title}
          </CardTitle>
          <CardDescription className="text-xs">{t.description}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center justify-center p-8 text-center space-y-4">
          <Award className="h-12 w-12 text-muted-foreground/40" />
          <p className="max-w-md text-sm text-muted-foreground">
            {canManageAward
              ? "هنوز هیچ پیش‌نویس واگذاری برای این استعلام ایجاد نشده است. می‌توانید با ایجاد پیش‌نویس واگذاری، پیشنهادهای موردنظر خود را تخصیص دهید."
              : "هنوز تصمیمی برای واگذاری این استعلام ثبت نشده است."}
          </p>
          {canManageAward && rfqStatus === "published" && (
            <Button onClick={() => void handleInitializeAward()} className="gap-2">
              <Plus className="h-4 w-4" />
              {t.initializeAward}
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  const isFinalized = award.status === "FINALIZED";
  const requestedTotal = Number(rfqQuantity) || Number(award.rfq_quantity);
  const awardedTotal = Number(award.total_awarded_quantity) || 0;
  const remainingTotal = Math.max(0, requestedTotal - awardedTotal);
  const percentAllocated = requestedTotal > 0 ? Math.min(100, Math.round((awardedTotal / requestedTotal) * 100)) : 0;

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* 1. Header & Status Banner */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Award className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold">{t.title}</h2>
            <Badge variant={isFinalized ? "default" : "secondary"}>
              {isFinalized ? t.finalizedStatus : t.draftStatus}
            </Badge>
            <Badge variant="outline" className="font-mono text-xs">
              v{award.version}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{t.description}</p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => void fetchAward()}
            className="min-h-8 h-8 px-3 text-xs gap-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t.refresh}
          </Button>

          {!isFinalized && canManageAward && (
            <Button
              disabled={award.allocations.length === 0 || isFinalizing}
              onClick={() => setShowFinalizeModal(true)}
              className="min-h-8 h-8 px-3 text-xs gap-1.5"
            >
              <FileCheck className="h-4 w-4" />
              {t.finalizeButton}
            </Button>
          )}
        </div>
      </div>

      {/* 2. Conflict or Alert Banners */}
      {staleConflict && (
        <Card className="border-amber-500 bg-amber-50 dark:bg-amber-950/20">
          <CardContent className="flex items-center gap-2 p-3 text-sm text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
            <span>{t.staleWarning}</span>
            <Button
              variant="outline"
              onClick={() => void fetchAward()}
              className="min-h-7 h-7 px-2 text-xs border-amber-300 text-amber-900 hover:bg-amber-100"
            >
              {t.refresh}
            </Button>
          </CardContent>
        </Card>
      )}

      {actionError && (
        <Card className="border-destructive bg-destructive/10">
          <CardContent className="flex items-center gap-2 p-3 text-sm text-destructive">
            <XCircle className="h-4 w-4 shrink-0" />
            <span>{actionError}</span>
          </CardContent>
        </Card>
      )}

      {actionSuccess && (
        <Card className="border-green-500 bg-green-50 dark:bg-green-950/20">
          <CardContent className="flex items-center gap-2 p-3 text-sm text-green-700 dark:text-green-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>{actionSuccess}</span>
          </CardContent>
        </Card>
      )}

      {isFinalized && (
        <Card className="border-primary/40 bg-primary/5">
          <CardContent className="flex items-center justify-between p-4">
            <div className="flex items-center gap-3">
              <Lock className="h-5 w-5 text-primary shrink-0" />
              <div>
                <p className="text-sm font-semibold text-primary">{t.immutableNotice}</p>
                {award.finalized_at && (
                  <p className="text-xs text-muted-foreground">
                    {t.finalizedAt} {new Date(award.finalized_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                  </p>
                )}
              </div>
            </div>
            <Badge variant="outline" className="text-xs">
              {t.finalizedStatus}
            </Badge>
          </CardContent>
        </Card>
      )}

      {/* 3. Quantity Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-xs font-medium text-muted-foreground">{t.requestedQuantity}</div>
            <div className="text-xl font-bold mt-1">
              <bdi dir="ltr">{requestedTotal.toLocaleString()} {rfqUnit}</bdi>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4">
            <div className="text-xs font-medium text-muted-foreground">{t.totalAwarded}</div>
            <div className="text-xl font-bold mt-1 text-primary">
              <bdi dir="ltr">{awardedTotal.toLocaleString()} {rfqUnit}</bdi>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4">
            <div className="text-xs font-medium text-muted-foreground">{t.remaining}</div>
            <div className={`text-xl font-bold mt-1 ${remainingTotal === 0 ? "text-green-600" : "text-amber-600"}`}>
              <bdi dir="ltr">{remainingTotal.toLocaleString()} {rfqUnit}</bdi>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4">
            <div className="text-xs font-medium text-muted-foreground">{t.allocatedPercent}</div>
            <div className="text-xl font-bold mt-1">
              <bdi dir="ltr">%{percentAllocated}</bdi>
            </div>
            <div className="w-full bg-muted rounded-full h-1.5 mt-2 overflow-hidden">
              <div
                className={`h-1.5 rounded-full transition-all ${
                  percentAllocated === 100 ? "bg-green-600" : "bg-primary"
                }`}
                style={{ width: `${percentAllocated}%` }}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 4. Allocations Table */}
      <Card>
        <CardHeader className="border-b pb-3 flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base font-semibold">{t.allocationsTitle}</CardTitle>
            <CardDescription className="text-xs">
              {award.allocations.length} مورد تخصیص یافته
            </CardDescription>
          </div>

          {!isFinalized && canManageAward && (
            <Button
              variant="outline"
              onClick={() => setShowAddForm(!showAddForm)}
              className="min-h-8 h-8 px-3 text-xs gap-1"
            >
              <Plus className="h-3.5 w-3.5" />
              {t.addAllocation}
            </Button>
          )}
        </CardHeader>

        {/* Add Allocation Inline Form */}
        {showAddForm && !isFinalized && (
          <div className="border-b bg-muted/20 p-4 space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 items-end">
              <div className="space-y-1">
                <Label htmlFor="alloc-offer" className="text-xs font-medium">
                  {t.selectOffer}
                </Label>
                <select
                  id="alloc-offer"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  value={selectedOfferVersionId}
                  disabled={isLoadingOffers}
                  onChange={(e) => {
                    setSelectedOfferVersionId(e.target.value);
                    const selected = availableOffers.find(
                      (r) => r.offer_version_id === e.target.value
                    );
                    if (selected) {
                      const offered = Number(selected.offered_quantity);
                      setAllocationQty(String(Math.min(offered, remainingTotal || offered)));
                    }
                  }}
                >
                  <option value="">
                    {isLoadingOffers ? "در حال بارگذاری پیشنهادها..." : `-- ${t.selectOffer} --`}
                  </option>
                  {availableOffers
                    .filter((row) => {
                      return !award.allocations.some(
                        (a) => a.offer_version_id === row.offer_version_id
                      );
                    })
                    .map((row) => (
                      <option key={row.offer_version_id} value={row.offer_version_id}>
                        {row.offeror_name} — نسخه {row.version_number} (
                        {Number(row.offered_quantity).toLocaleString()} {row.quantity_unit} @ $
                        {Number(row.unit_price).toLocaleString()} {row.currency})
                      </option>
                    ))}
                </select>
              </div>

              <div className="space-y-1">
                <Label htmlFor="alloc-qty" className="text-xs font-medium">
                  {t.awardedQty} ({rfqUnit})
                </Label>
                <Input
                  id="alloc-qty"
                  type="number"
                  step="0.001"
                  placeholder="0.000"
                  value={allocationQty}
                  onChange={(e) => setAllocationQty(e.target.value)}
                  className="text-xs"
                />
              </div>

              <div className="flex gap-2">
                <Button
                  disabled={!selectedOfferVersionId || !allocationQty || isAddingAllocation}
                  onClick={() => void handleAddAllocation()}
                  className="min-h-8 h-8 px-3 text-xs gap-1 flex-1"
                >
                  {isAddingAllocation ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  {t.addAllocation}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowAddForm(false)}
                  className="min-h-8 h-8 px-3 text-xs"
                >
                  انصراف
                </Button>
              </div>
            </div>
          </div>
        )}

        <CardContent className="p-0">
          {award.allocations.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              {t.noAllocations}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t.selectOffer}</TableHead>
                  <TableHead>{t.offerVersion}</TableHead>
                  <TableHead>{t.offeredQty}</TableHead>
                  <TableHead>{t.awardedQty}</TableHead>
                  <TableHead>{t.unitPrice}</TableHead>
                  <TableHead>{t.totalPrice}</TableHead>
                  {!isFinalized && canManageAward && <TableHead className="text-end">{t.actions}</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {award.allocations.map((alloc: AwardAllocationResponse) => {
                  const isEditing = editingAllocId === alloc.id;
                  const unitPrice = Number(alloc.unit_price) || 0;
                  const awardedQtyNum = Number(alloc.awarded_quantity) || 0;
                  const totalPrice = (unitPrice * awardedQtyNum).toLocaleString();

                  return (
                    <TableRow key={alloc.id}>
                      <TableCell className="font-medium">
                        <div className="flex flex-col">
                          <span>{alloc.counterparty_name}</span>
                          {alloc.is_external && (
                            <Badge variant="outline" className="text-[10px] w-fit mt-0.5">
                              خارج از سامانه
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="font-mono text-xs">
                          <bdi dir="ltr">v{alloc.offer_version_number}</bdi>
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <bdi dir="ltr">{Number(alloc.offered_quantity).toLocaleString()} {alloc.quantity_unit}</bdi>
                      </TableCell>
                      <TableCell>
                        {isEditing ? (
                          <div className="flex items-center gap-1.5">
                            <Input
                              type="number"
                              step="0.001"
                              className="h-7 w-24 text-xs"
                              value={editQty}
                              onChange={(e) => setEditQty(e.target.value)}
                            />
                            <Button
                              className="min-h-7 h-7 px-2 text-xs"
                              disabled={isUpdatingAlloc}
                              onClick={() => void handleUpdateAllocation(alloc.id)}
                            >
                              ذخیره
                            </Button>
                            <Button
                              variant="outline"
                              className="min-h-7 h-7 px-1.5 text-xs"
                              onClick={() => setEditingAllocId(null)}
                            >
                              ✕
                            </Button>
                          </div>
                        ) : (
                          <span className="font-semibold text-primary">
                            <bdi dir="ltr">{Number(alloc.awarded_quantity).toLocaleString()} {alloc.quantity_unit}</bdi>
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <bdi dir="ltr">${Number(alloc.unit_price).toLocaleString()} {alloc.currency}</bdi>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        <bdi dir="ltr">${totalPrice}</bdi>
                      </TableCell>
                      {!isFinalized && canManageAward && (
                        <TableCell className="text-end">
                          <div className="flex items-center justify-end gap-1">
                            {!isEditing && (
                              <Button
                                variant="outline"
                                className="min-h-7 h-7 px-2 text-xs border-muted hover:bg-muted"
                                onClick={() => {
                                  setEditingAllocId(alloc.id);
                                  setEditQty(String(alloc.awarded_quantity));
                                }}
                              >
                                {t.editQty}
                              </Button>
                            )}
                            <Button
                              variant="outline"
                              className="min-h-7 h-7 px-2 text-xs border-destructive/30 text-destructive hover:bg-destructive/10"
                              onClick={() => void handleRemoveAllocation(alloc.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 5. System Architectural Notice */}
      <div className="rounded-md border border-muted bg-muted/10 p-3 text-xs text-muted-foreground flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-muted-foreground/80 shrink-0" />
        <span>{t.dealNotice}</span>
      </div>

      {/* --- MODAL: FINALIZE CONFIRMATION --- */}
      {showFinalizeModal && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <Card className="w-full max-w-md shadow-lg" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <FileCheck className="h-5 w-5 text-primary" />
                {t.finalizeTitle}
              </CardTitle>
              <CardDescription className="text-xs">
                {t.finalizeDescription}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-md bg-muted/40 p-3 space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t.requestedQuantity}</span>
                  <span className="font-semibold"><bdi dir="ltr">{requestedTotal.toLocaleString()} {rfqUnit}</bdi></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t.totalAwarded}</span>
                  <span className="font-semibold text-primary"><bdi dir="ltr">{awardedTotal.toLocaleString()} {rfqUnit}</bdi></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t.remaining}</span>
                  <span className="font-semibold"><bdi dir="ltr">{remainingTotal.toLocaleString()} {rfqUnit}</bdi></span>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button
                  variant="outline"
                  onClick={() => setShowFinalizeModal(false)}
                  disabled={isFinalizing}
                  className="min-h-8 h-8 px-3 text-xs"
                >
                  انصراف
                </Button>
                <Button
                  onClick={() => void handleFinalizeAward()}
                  disabled={isFinalizing}
                  className="min-h-8 h-8 px-3 text-xs gap-1"
                >
                  {isFinalizing ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin me-1.5" />
                      {t.finalizing}
                    </>
                  ) : (
                    <>
                      <Lock className="h-3.5 w-3.5 me-1" />
                      {t.finalizeButton}
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

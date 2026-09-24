"use client";

import React, { useState } from "react";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
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
  Loader2,
  Scale,
  Truck,
} from "lucide-react";
import type {
  ExecutionDetail,
  ExecutionLogistics,
  DealResponse,
  TransportModeEnum,
} from "./types";

export interface LogisticsTabProps {
  locale?: EnabledLocale;
  deal: DealResponse;
  execution: ExecutionDetail | null;
  logistics: ExecutionLogistics | null;
  isOperatorOrAdmin: boolean;
  isBuyer: boolean;
  isSeller: boolean;
  isViewer: boolean;
  onRefreshLogistics: () => Promise<void>;
  onRefreshTimeline: () => Promise<void>;
}

export function LogisticsTab({
  locale = "fa",
  deal,
  execution,
  logistics,
  isOperatorOrAdmin,
  isBuyer,
  isSeller,
  isViewer,
  onRefreshLogistics,
  onRefreshTimeline,
}: LogisticsTabProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealWorkspace.executionMonitor.logistics;
  const termsT = messages.dealWorkspace.terms;

  const [activeAction, setActiveAction] = useState<
    "scheduleLoading" | "recordLoading" | "updateTransport" | "updateETA" | "recordDelivery" | "updateCost" | null
  >(null);

  // Form field states (preserving user input across conflicts)
  const [carrierInput, setCarrierInput] = useState<string>("");
  const [transportModeInput, setTransportModeInput] = useState<TransportModeEnum | "">("");
  const [transportRefInput, setTransportRefInput] = useState<string>("");
  const [scheduledLoadingInput, setScheduledLoadingInput] = useState<string>("");
  const [actualLoadingInput, setActualLoadingInput] = useState<string>("");
  const [etaInput, setEtaInput] = useState<string>("");
  const [actualDeliveryInput, setActualDeliveryInput] = useState<string>("");
  const [costInput, setCostInput] = useState<string>("");
  const [currencyInput, setCurrencyInput] = useState<string>("USD");
  const [pickupLocInput, setPickupLocInput] = useState<string>("");
  const [destLocInput, setDestLocInput] = useState<string>("");

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!execution) {
    return (
      <Card className="p-12 text-center shadow-none border-dashed" dir={isRtl ? "rtl" : "ltr"}>
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
          <Truck className="size-6 text-muted-foreground" />
        </div>
        <h2 className="mt-4 text-base font-semibold">{t.title}</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
          {messages.dealWorkspace.executionMonitor.uninitialized.description}
        </p>
      </Card>
    );
  }

  const isOpen = execution.status === "OPEN";
  const canMutate = isOpen && !isViewer;
  const canSellerMutate = canMutate && (isSeller || isOperatorOrAdmin);
  const canBuyerMutate = canMutate && (isBuyer || isOperatorOrAdmin);

  const handleOpenAction = (action: typeof activeAction) => {
    setActiveAction(action);
    setErrorMsg(null);
    if (!logistics) return;

    if (action === "updateTransport") {
      setCarrierInput(logistics.carrier_name || logistics.carrier || "");
      setTransportModeInput((logistics.transport_mode as TransportModeEnum) || "");
      setTransportRefInput(logistics.transport_reference || "");
    } else if (action === "scheduleLoading") {
      setScheduledLoadingInput(logistics.scheduled_loading_at?.slice(0, 16) || "");
      setPickupLocInput(logistics.pickup_location || "");
      setDestLocInput(logistics.destination_location || "");
    } else if (action === "recordLoading") {
      setActualLoadingInput(logistics.actual_loading_at?.slice(0, 16) || "");
    } else if (action === "updateETA") {
      setEtaInput(logistics.eta?.slice(0, 16) || "");
    } else if (action === "recordDelivery") {
      setActualDeliveryInput(logistics.actual_delivery_at?.slice(0, 16) || "");
    } else if (action === "updateCost") {
      setCostInput(logistics.logistics_cost ? String(logistics.logistics_cost) : "");
      setCurrencyInput(logistics.currency || "USD");
    }
  };

  const handleCloseAction = () => {
    setActiveAction(null);
    setErrorMsg(null);
  };

  const handleSubmitAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!execution || !logistics || !activeAction) return;

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      if (activeAction === "scheduleLoading") {
        if (!scheduledLoadingInput) {
          setErrorMsg("لطفاً تاریخ و زمان زمان‌بندی بارگیری را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/schedule-loading/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              scheduled_loading_at: scheduledLoadingInput,
              pickup_location: pickupLocInput.trim(),
              destination_location: destLocInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "recordLoading") {
        if (!actualLoadingInput) {
          setErrorMsg("لطفاً زمان واقعی بارگیری را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/record-loading/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              actual_loading_at: actualLoadingInput,
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "updateTransport") {
        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/update-transport/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              carrier_name: carrierInput.trim(),
              transport_mode: transportModeInput ? (transportModeInput as TransportModeEnum) : null,
              transport_reference: transportRefInput.trim(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "updateETA") {
        if (!etaInput) {
          setErrorMsg("لطفاً زمان تخمینی رسیدن (ETA) را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/update-eta/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              eta: etaInput,
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "recordDelivery") {
        if (!actualDeliveryInput) {
          setErrorMsg("لطفاً زمان واقعی تحویل را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/record-delivery/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              actual_delivery_at: actualDeliveryInput,
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      } else if (activeAction === "updateCost") {
        if (!costInput) {
          setErrorMsg("لطفاً مبلغ هزینه لجستیک را وارد کنید.");
          setIsSubmitting(false);
          return;
        }

        const { response } = await apiClient.POST(
          "/api/execution/{execution_id}/logistics/update-cost/",
          {
            params: { path: { execution_id: execution.id } },
            body: {
              expected_version: logistics.version ?? 0,
              logistics_cost: costInput,
              currency: currencyInput.trim().toUpperCase(),
            },
          }
        );

        if (response.ok) {
          handleCloseAction();
          await onRefreshLogistics();
          await onRefreshTimeline();
        } else if (response.status === 409) {
          setErrorMsg(messages.dealWorkspace.executionMonitor.conflictError);
          await onRefreshLogistics();
        } else {
          setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
        }
      }
    } catch {
      setErrorMsg(messages.dealWorkspace.executionMonitor.genericError);
    } finally {
      setIsSubmitting(false);
    }
  };

  const carrierDisplayName = logistics?.carrier_name || logistics?.carrier || t.notRecorded;
  const transportModeLabel = logistics?.transport_mode
    ? t.modes[logistics.transport_mode as keyof typeof t.modes] ?? logistics.transport_mode
    : t.notRecorded;

  return (
    <div className="space-y-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* 1. Commercial Agreed Terms Card (Read-only historical truth) */}
      <Card className="shadow-none border-primary/20 bg-primary/[0.02]">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Scale className="size-4 text-primary" />
            <span>{t.commercialCardTitle}</span>
          </CardTitle>
          <CardDescription className="text-xs">{t.commercialTermsNotice}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
            <div>
              <dt className="text-muted-foreground font-medium">{termsT.incoterm}</dt>
              <dd className="mt-1 font-semibold" dir="ltr">{deal.terms?.incoterm || "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{termsT.deliveryWindow}</dt>
              <dd className="mt-1 font-mono" dir="ltr">
                {deal.terms?.delivery_start && deal.terms?.delivery_end
                  ? `${deal.terms.delivery_start} ~ ${deal.terms.delivery_end}`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{termsT.origin}</dt>
              <dd className="mt-1">{deal.terms?.origin || "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground font-medium">{termsT.destination}</dt>
              <dd className="mt-1">{deal.terms?.destination || "—"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* 2. Actual Operational Logistics Card */}
      <Card className="shadow-none">
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <Truck className="size-4 text-primary" />
                <span>{t.actualCardTitle}</span>
              </CardTitle>
              <CardDescription className="text-xs mt-1">{t.subtitle}</CardDescription>
            </div>
            {logistics && (
              <Badge variant="outline" className="text-xs font-mono" dir="ltr">
                ver: {logistics.version}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {errorMsg && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-800 flex items-start gap-2">
              <AlertTriangle className="size-4 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {logistics ? (
            <div className="space-y-6">
              <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-xs">
                <div>
                  <dt className="text-muted-foreground font-medium">{t.carrier}</dt>
                  <dd className="mt-1 font-semibold text-sm">{carrierDisplayName}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.transportMode}</dt>
                  <dd className="mt-1 font-semibold">{transportModeLabel}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.transportReference}</dt>
                  <dd className="mt-1 font-mono text-sm" dir="ltr">
                    {logistics.transport_reference || t.notRecorded}
                  </dd>
                </div>

                <div>
                  <dt className="text-muted-foreground font-medium">{t.scheduledLoading}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {logistics.scheduled_loading_at
                      ? logistics.scheduled_loading_at.slice(0, 19).replace("T", " ")
                      : t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.actualLoading}</dt>
                  <dd className="mt-1 font-mono" dir="ltr">
                    {logistics.actual_loading_at
                      ? logistics.actual_loading_at.slice(0, 19).replace("T", " ")
                      : t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.eta}</dt>
                  <dd className="mt-1 font-mono font-semibold text-primary" dir="ltr">
                    {logistics.eta ? logistics.eta.slice(0, 19).replace("T", " ") : t.notRecorded}
                  </dd>
                </div>

                <div>
                  <dt className="text-muted-foreground font-medium">{t.actualDelivery}</dt>
                  <dd className="mt-1 font-mono font-semibold" dir="ltr">
                    {logistics.actual_delivery_at
                      ? logistics.actual_delivery_at.slice(0, 19).replace("T", " ")
                      : t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.logisticsCost}</dt>
                  <dd className="mt-1 font-mono text-sm" dir="ltr">
                    {logistics.logistics_cost
                      ? `${logistics.logistics_cost} ${logistics.currency || ""}`
                      : t.notRecorded}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground font-medium">{t.pickup}</dt>
                  <dd className="mt-1">
                    {logistics.pickup_location || logistics.pickup_area_name_fa || t.notRecorded}
                  </dd>
                </div>

                <div>
                  <dt className="text-muted-foreground font-medium">{t.destination}</dt>
                  <dd className="mt-1">
                    {logistics.destination_location || logistics.destination_area_name_fa || t.notRecorded}
                  </dd>
                </div>
              </dl>

              {/* Action Buttons for Logistics */}
              {canMutate && (
                <div className="flex flex-wrap items-center gap-2 pt-4 border-t">
                  {canSellerMutate && (
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("updateTransport")}
                        className="text-xs"
                      >
                        {t.actions.updateTransport}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("scheduleLoading")}
                        className="text-xs"
                      >
                        {t.actions.scheduleLoading}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("recordLoading")}
                        className="text-xs"
                      >
                        {t.actions.recordLoading}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("updateETA")}
                        className="text-xs"
                      >
                        {t.actions.updateETA}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => handleOpenAction("updateCost")}
                        className="text-xs"
                      >
                        {t.actions.updateCost}
                      </Button>
                    </>
                  )}

                  {canBuyerMutate && (
                    <Button
                      type="button"
                      variant="default"
                      onClick={() => handleOpenAction("recordDelivery")}
                      className="text-xs gap-1"
                    >
                      <CheckCircle2 className="size-3.5" />
                      <span>{t.actions.recordDelivery}</span>
                    </Button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t.notRecorded}</p>
          )}

          {/* Logistics Action Form / Dialog */}
          {activeAction && (
            <Card className="border-primary/40 bg-muted/20 mt-4 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">
                  {activeAction === "scheduleLoading" && t.dialogs.scheduleTitle}
                  {activeAction === "recordLoading" && t.dialogs.recordLoadingTitle}
                  {activeAction === "updateTransport" && t.dialogs.updateTransportTitle}
                  {activeAction === "updateETA" && t.dialogs.updateETATitle}
                  {activeAction === "recordDelivery" && t.dialogs.recordDeliveryTitle}
                  {activeAction === "updateCost" && t.dialogs.updateCostTitle}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmitAction} className="space-y-4">
                  {activeAction === "updateTransport" && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.carrierLabel}</Label>
                        <Input
                          value={carrierInput}
                          onChange={(e) => setCarrierInput(e.target.value)}
                          placeholder={t.dialogs.carrierPlaceholder}
                          className="text-xs"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.modeLabel}</Label>
                        <Select
                          value={transportModeInput}
                          onValueChange={(val) => setTransportModeInput(val as TransportModeEnum)}
                        >
                          <SelectTrigger className="text-xs">
                            <SelectValue placeholder="انتخاب شیوه…" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="ROAD">{t.modes.ROAD}</SelectItem>
                            <SelectItem value="SEA">{t.modes.SEA}</SelectItem>
                            <SelectItem value="RAIL">{t.modes.RAIL}</SelectItem>
                            <SelectItem value="AIR">{t.modes.AIR}</SelectItem>
                            <SelectItem value="MULTIMODAL">{t.modes.MULTIMODAL}</SelectItem>
                            <SelectItem value="OTHER">{t.modes.OTHER}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.referenceLabel}</Label>
                        <Input
                          value={transportRefInput}
                          onChange={(e) => setTransportRefInput(e.target.value)}
                          placeholder={t.dialogs.referencePlaceholder}
                          className="text-xs"
                        />
                      </div>
                    </div>
                  )}

                  {activeAction === "scheduleLoading" && (
                    <div className="space-y-4">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.scheduledLoading} *</Label>
                        <Input
                          type="datetime-local"
                          value={scheduledLoadingInput}
                          onChange={(e) => setScheduledLoadingInput(e.target.value)}
                          required
                          className="text-xs"
                        />
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                          <Label className="text-xs font-medium">{t.dialogs.pickupLocationLabel}</Label>
                          <Input
                            value={pickupLocInput}
                            onChange={(e) => setPickupLocInput(e.target.value)}
                            className="text-xs"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs font-medium">{t.dialogs.destinationLocationLabel}</Label>
                          <Input
                            value={destLocInput}
                            onChange={(e) => setDestLocInput(e.target.value)}
                            className="text-xs"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {activeAction === "recordLoading" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.actualLoading} *</Label>
                      <Input
                        type="datetime-local"
                        value={actualLoadingInput}
                        onChange={(e) => setActualLoadingInput(e.target.value)}
                        required
                        className="text-xs"
                      />
                    </div>
                  )}

                  {activeAction === "updateETA" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.eta} *</Label>
                      <Input
                        type="datetime-local"
                        value={etaInput}
                        onChange={(e) => setEtaInput(e.target.value)}
                        required
                        className="text-xs"
                      />
                    </div>
                  )}

                  {activeAction === "recordDelivery" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">{t.actualDelivery} *</Label>
                      <Input
                        type="datetime-local"
                        value={actualDeliveryInput}
                        onChange={(e) => setActualDeliveryInput(e.target.value)}
                        required
                        className="text-xs"
                      />
                    </div>
                  )}

                  {activeAction === "updateCost" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.costLabel} *</Label>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          value={costInput}
                          onChange={(e) => setCostInput(e.target.value)}
                          required
                          className="text-xs"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">{t.dialogs.currencyLabel} *</Label>
                        <Input
                          maxLength={3}
                          value={currencyInput}
                          onChange={(e) => setCurrencyInput(e.target.value.toUpperCase())}
                          required
                          className="text-xs font-mono"
                        />
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-2 justify-end pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseAction}
                      disabled={isSubmitting}
                      className="text-xs"
                    >
                      {messages.dealWorkspace.executionMonitor.milestones.dialogs.cancel}
                    </Button>
                    <Button
                      type="submit"
                      disabled={isSubmitting}
                      className="text-xs gap-1.5"
                    >
                      {isSubmitting && <Loader2 className="size-3.5 animate-spin" />}
                      <span>{isSubmitting ? "در حال ثبت…" : "تأیید و ثبت"}</span>
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

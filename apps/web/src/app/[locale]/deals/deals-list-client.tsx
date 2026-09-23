"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ArrowLeft, ArrowRight, Handshake, Loader2 } from "lucide-react";

type DealResponse = components["schemas"]["DealResponse"];

export interface DealsListClientProps {
  locale?: EnabledLocale;
}

export function DealsListClient({ locale = "fa" }: DealsListClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.dealsList;
  const tWorkspace = messages.dealWorkspace;
  const queryClient = useQueryClient();
  const { state } = useAuth();

  const [deals, setDeals] = useState<DealResponse[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const currentUserId = state.status === "authenticated" ? state.user.id : null;

  // Track session identity to invalidate data on switch
  const previousSessionKeyRef = useRef<string | null>(null);
  const activeSessionKey = `${currentUserId ?? "anon"}:${currentOrgId ?? "none"}`;

  useEffect(() => {
    if (
      previousSessionKeyRef.current &&
      previousSessionKeyRef.current !== activeSessionKey
    ) {
      queryClient.removeQueries({ queryKey: ["deals-list"] });
      setDeals([]);
      setIsLoading(true);
    }
    previousSessionKeyRef.current = activeSessionKey;
  }, [activeSessionKey, queryClient]);

  useEffect(() => {
    let ignore = false;
    async function fetchDeals() {
      setIsLoading(true);
      try {
        const { data, response } = await apiClient.GET("/api/deals/");
        if (ignore) return;
        if (response.ok && Array.isArray(data)) {
          setDeals(data);
        } else {
          setDeals([]);
        }
      } catch {
        if (!ignore) {
          setDeals([]);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    void fetchDeals();
    return () => {
      ignore = true;
    };
  }, [activeSessionKey]);

  const ArrowIcon = isRtl ? ArrowLeft : ArrowRight;

  return (
    <div className="space-y-8" dir={isRtl ? "rtl" : "ltr"}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t.title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{t.subtitle}</p>
      </div>

      {isLoading ? (
        <Card className="flex items-center justify-center p-12 shadow-none">
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <Loader2 className="size-8 animate-spin text-primary" />
            <p className="text-sm">{t.loading}</p>
          </div>
        </Card>
      ) : deals.length === 0 ? (
        <Card className="p-12 text-center shadow-none">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted">
            <Handshake className="size-6 text-muted-foreground" />
          </div>
          <h2 className="mt-4 text-base font-semibold">{t.emptyTitle}</h2>
          <p className="mt-2 text-sm text-muted-foreground">{t.emptyDescription}</p>
        </Card>
      ) : (
        <Card className="shadow-none overflow-hidden">
          <CardHeader className="border-b bg-muted/40 px-6 py-4">
            <CardTitle className="text-base font-medium">
              {t.title} ({deals.length})
            </CardTitle>
            <CardDescription className="text-xs">
              {tWorkspace?.badges?.immutableNotice}
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-start">{t.table.dealId}</TableHead>
                    <TableHead className="text-start">{t.table.commodity}</TableHead>
                    <TableHead className="text-start">{t.table.quantity}</TableHead>
                    <TableHead className="text-start">{t.table.unitPrice}</TableHead>
                    <TableHead className="text-start">{t.table.productCost}</TableHead>
                    <TableHead className="text-start">{t.table.counterparty}</TableHead>
                    <TableHead className="text-start">{t.table.channel}</TableHead>
                    <TableHead className="text-start">{t.table.status}</TableHead>
                    <TableHead className="text-start">{t.table.actions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {deals.map((deal) => {
                    const commodityName =
                      locale === "fa"
                        ? deal.terms?.commodity_name_fa || deal.terms?.commodity_code
                        : deal.terms?.commodity_name_en || deal.terms?.commodity_code;

                    const buyerParty = deal.parties?.find((p) => p.role === "BUYER");
                    const sellerParty = deal.parties?.find((p) => p.role === "SELLER");

                    const channelKey = deal.attribution?.primary_channel;
                    const channelLabel = channelKey
                      ? tWorkspace?.attribution?.channels?.[channelKey as keyof typeof tWorkspace.attribution.channels] ?? channelKey
                      : "—";

                    const isPending = deal.attribution?.status === "PENDING";

                    return (
                      <TableRow key={deal.id}>
                        <TableCell className="font-mono text-xs">
                          <span dir="ltr">{deal.id.slice(0, 8)}…</span>
                        </TableCell>
                        <TableCell className="font-medium text-sm">
                          {commodityName || "—"}
                        </TableCell>
                        <TableCell className="text-sm">
                          <span dir="ltr">
                            {deal.terms?.quantity} {deal.terms?.quantity_unit}
                          </span>
                        </TableCell>
                        <TableCell className="text-sm">
                          <span dir="ltr">
                            {deal.terms?.unit_price} {deal.terms?.currency}
                          </span>
                        </TableCell>
                        <TableCell className="text-sm font-semibold">
                          <span dir="ltr">
                            {deal.terms?.product_cost_snapshot} {deal.terms?.currency}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs">
                          <div className="flex flex-col gap-0.5">
                            <span className="font-medium">
                              {sellerParty?.name_snapshot || "—"}
                            </span>
                            {deal.seller_external_counterparty_id && (
                              <Badge variant="outline" className="w-fit text-[10px] px-1.5 py-0 border-amber-500/40 text-amber-700 bg-amber-500/10">
                                {tWorkspace?.badges?.externalCounterparty}
                              </Badge>
                            )}
                            <span className="text-muted-foreground text-[11px]">
                              {buyerParty?.name_snapshot}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">
                          <span className="text-muted-foreground">{channelLabel}</span>
                        </TableCell>
                        <TableCell>
                          {isPending ? (
                            <Badge variant="outline" className="text-amber-600 border-amber-500/30 bg-amber-500/10">
                              {tWorkspace?.attribution?.statuses?.PENDING}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-emerald-600 border-emerald-500/30 bg-emerald-500/10">
                              {tWorkspace?.attribution?.statuses?.RESOLVED}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Button asChild variant="outline" className="min-h-8 px-2.5 py-1 text-xs gap-1">
                            <Link href={`/${locale}/deals/${deal.id}`}>
                              <span>{t.table.viewDeal}</span>
                              <ArrowIcon className="size-3.5" />
                            </Link>
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

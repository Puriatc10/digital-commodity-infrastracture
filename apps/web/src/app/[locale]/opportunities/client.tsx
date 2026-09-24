"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  Inbox,
  UserCheck,
  CheckCircle2,
  Clock,
  ArrowRightLeft,
  XCircle,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Building2,
  User,
  Handshake,
} from "lucide-react";

import { apiClient as client } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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

type OpportunityDetail = components["schemas"]["OpportunityDetail"];
type DeskView =
  | "inbox"
  | "assigned_to_me"
  | "qualified"
  | "follow_up_required"
  | "converted"
  | "lost";

interface OpportunityDeskClientProps {
  locale: EnabledLocale;
}

export function OpportunityDeskClient({ locale }: OpportunityDeskClientProps) {
  const messages = getMessages(locale);
  const oppMsg = messages.opportunities;
  const { state: authState } = useAuth();
  const queryClient = useQueryClient();

  const [activeView, setActiveView] = useState<DeskView>("inbox");
  const [directionFilter, setDirectionFilter] = useState<string>("all");
  const [commodityFilter, setCommodityFilter] = useState<string>("");
  const [identifierFilter, setIdentifierFilter] = useState<string>("");
  const [page, setPage] = useState<number>(1);

  const isOperatorOrAdmin =
    authState.status === "authenticated" &&
    authState.systemRoles.some((r) => r === "operator" || r === "admin");

  const currentUserId =
    authState.status === "authenticated" ? authState.user.id : null;
  const prevUserRef = useRef<number | null>(currentUserId);

  // Session Cache Isolation
  useEffect(() => {
    if (prevUserRef.current !== currentUserId) {
      queryClient.removeQueries({ queryKey: ["opportunities"] });
      queryClient.removeQueries({ queryKey: ["opportunity"] });
      prevUserRef.current = currentUserId;
    }
  }, [currentUserId, queryClient]);

  const queryParams = {
    page,
    page_size: 20,
    ...(directionFilter !== "all" ? { direction: directionFilter } : {}),
    ...(commodityFilter.trim() ? { commodity: commodityFilter.trim() } : {}),
    ...(identifierFilter.trim() ? { identifier: identifierFilter.trim() } : {}),
    ...(activeView === "inbox" ? { status: "active" } : {}),
    ...(activeView === "assigned_to_me" ? { assigned_to_me: true } : {}),
    ...(activeView === "qualified" ? { status: "Qualified" } : {}),
    ...(activeView === "follow_up_required" ? { follow_up_required: true } : {}),
    ...(activeView === "converted" ? { status: "Converted" } : {}),
    ...(activeView === "lost" ? { status: "Lost" } : {}),
  };

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: [
      "opportunities",
      activeView,
      currentUserId,
      page,
      directionFilter,
      commodityFilter,
      identifierFilter,
    ],
    queryFn: async () => {
      const response = await client.GET("/api/opportunities/opportunities/", {
        params: {
          query: queryParams,
        },
      });

      if (!response.response.ok || !response.data) {
        throw new Error("Failed to fetch opportunities");
      }

      return response.data;
    },
    enabled: isOperatorOrAdmin,
  });

  if (authState.status === "loading") {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="sr-only">{oppMsg.states.loading}</span>
      </div>
    );
  }

  if (!isOperatorOrAdmin) {
    return (
      <Card className="p-8 text-center">
        <div className="flex flex-col items-center gap-3">
          <ShieldAlert className="h-10 w-10 text-destructive" />
          <h2 className="text-lg font-semibold text-destructive">
            {messages.rfqBuilder.unauthorizedTitle}
          </h2>
          <p className="text-sm text-muted-foreground">
            {oppMsg.states.unauthorized}
          </p>
        </div>
      </Card>
    );
  }

  const results: OpportunityDetail[] = data?.results ?? [];
  const totalCount = data?.count ?? 0;
  const hasNext = Boolean(data?.next);
  const hasPrev = Boolean(data?.previous);

  const getStatusBadge = (status: string) => {
    const label = oppMsg.status[status as keyof typeof oppMsg.status] || status;
    switch (status) {
      case "Qualified":
        return <Badge variant="default" className="bg-emerald-600 text-white">{label}</Badge>;
      case "Converted":
        return <Badge variant="default" className="bg-blue-600 text-white">{label}</Badge>;
      case "Contacted":
        return <Badge variant="secondary" className="bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300">{label}</Badge>;
      case "Matching":
        return <Badge variant="secondary" className="bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">{label}</Badge>;
      case "On Hold":
        return <Badge variant="outline" className="border-amber-500 text-amber-600">{label}</Badge>;
      case "Lost":
      case "Rejected":
      case "Expired":
        return <Badge variant="destructive">{label}</Badge>;
      default:
        return <Badge variant="secondary">{label}</Badge>;
    }
  };

  const getDirectionBadge = (direction: string) => {
    const isDemand = direction.toLowerCase() === "demand";
    return (
      <Badge
        variant="outline"
        className={isDemand ? "border-blue-500 text-blue-600" : "border-emerald-500 text-emerald-600"}
      >
        {isDemand ? oppMsg.direction.Demand : oppMsg.direction.Supply}
      </Badge>
    );
  };

  const viewsConfig: Array<{ id: DeskView; label: string; icon: React.ReactNode }> = [
    { id: "inbox", label: oppMsg.views.inbox, icon: <Inbox className="h-4 w-4" /> },
    { id: "assigned_to_me", label: oppMsg.views.assigned_to_me, icon: <UserCheck className="h-4 w-4" /> },
    { id: "qualified", label: oppMsg.views.qualified, icon: <CheckCircle2 className="h-4 w-4" /> },
    { id: "follow_up_required", label: oppMsg.views.follow_up_required, icon: <Clock className="h-4 w-4" /> },
    { id: "converted", label: oppMsg.views.converted, icon: <ArrowRightLeft className="h-4 w-4" /> },
    { id: "lost", label: oppMsg.views.lost, icon: <XCircle className="h-4 w-4" /> },
  ];

  return (
    <div className="space-y-6">
      {/* Desk Views Navigation Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b pb-4" role="tablist">
        {viewsConfig.map((view) => {
          const isActive = activeView === view.id;
          return (
            <Button
              key={view.id}
              role="tab"
              aria-selected={isActive}
              variant={isActive ? "default" : "outline"}
              onClick={() => {
                setActiveView(view.id);
                setPage(1);
              }}
              className="flex items-center gap-2 min-h-8 px-3 text-xs"
            >
              {view.icon}
              <span>{view.label}</span>
            </Button>
          );
        })}
      </div>

      {/* Filters Bar */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex flex-wrap items-center gap-3">
            {/* Direction Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                {oppMsg.fields.direction}:
              </span>
              <Select
                value={directionFilter}
                onValueChange={(val) => {
                  setDirectionFilter(val);
                  setPage(1);
                }}
              >
                <SelectTrigger className="h-8 w-28 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{oppMsg.direction.all}</SelectItem>
                  <SelectItem value="Demand">{oppMsg.direction.Demand}</SelectItem>
                  <SelectItem value="Supply">{oppMsg.direction.Supply}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Commodity Code Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                {oppMsg.fields.commodity}:
              </span>
              <Input
                placeholder="bitumen..."
                value={commodityFilter}
                onChange={(e) => {
                  setCommodityFilter(e.target.value);
                  setPage(1);
                }}
                className="h-8 w-32 text-xs"
              />
            </div>

            {/* Identifier Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                {oppMsg.fields.identifier}:
              </span>
              <Input
                placeholder="OPP-2026-..."
                value={identifierFilter}
                onChange={(e) => {
                  setIdentifierFilter(e.target.value);
                  setPage(1);
                }}
                className="h-8 w-36 text-xs"
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="flex items-center gap-1 min-h-8 px-3 text-xs"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
              <span>{oppMsg.actions.refresh}</span>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Main Table / State Container */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-base font-bold">
            {viewsConfig.find((v) => v.id === activeView)?.label}
            <span className="ms-2 text-xs font-normal text-muted-foreground">
              ({totalCount} {oppMsg.title})
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <span className="sr-only">{oppMsg.states.loading}</span>
            </div>
          ) : isError ? (
            <div className="p-8 text-center text-destructive">
              <p className="text-sm font-semibold">{oppMsg.states.loadError}</p>
              <Button
                variant="outline"
                onClick={() => void refetch()}
                className="mt-3 min-h-8 px-3 text-xs"
              >
                {oppMsg.actions.refresh}
              </Button>
            </div>
          ) : results.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground">
              <Inbox className="mx-auto mb-3 h-8 w-8 text-muted-foreground/60" />
              <p className="text-sm font-medium">{oppMsg.states.emptyList}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{oppMsg.fields.identifier}</TableHead>
                  <TableHead>{oppMsg.fields.direction}</TableHead>
                  <TableHead>{oppMsg.fields.counterparty}</TableHead>
                  <TableHead>{oppMsg.fields.commodity}</TableHead>
                  <TableHead>{oppMsg.fields.quantity}</TableHead>
                  <TableHead>{oppMsg.fields.indicativePrice}</TableHead>
                  <TableHead>{oppMsg.fields.source}</TableHead>
                  <TableHead>{oppMsg.fields.status}</TableHead>
                  <TableHead>{oppMsg.fields.updatedAt}</TableHead>
                  <TableHead className="text-end">{oppMsg.fields.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((opp) => {
                  const counterpartyDisplay = opp.organization
                    ? opp.organization.name
                    : opp.external_counterparty
                    ? opp.external_counterparty.company_name
                    : oppMsg.counterpartyType.unknown;

                  const isExternal = Boolean(opp.external_counterparty);
                  const sourceLabel =
                    oppMsg.source[opp.source as keyof typeof oppMsg.source] || opp.source;

                  return (
                    <TableRow key={opp.id}>
                      <TableCell className="font-mono font-medium">
                        <Link
                          href={`/${locale}/opportunities/${opp.id}`}
                          className="text-primary hover:underline"
                        >
                          <bdi dir="ltr">{opp.identifier || opp.id.slice(0, 8)}</bdi>
                        </Link>
                      </TableCell>

                      <TableCell>{getDirectionBadge(opp.direction)}</TableCell>

                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          {isExternal ? (
                            <User className="h-3.5 w-3.5 text-muted-foreground" />
                          ) : (
                            <Building2 className="h-3.5 w-3.5 text-primary" />
                          )}
                          <span className="font-medium text-sm">{counterpartyDisplay}</span>
                          {isExternal && (
                            <Badge variant="outline" className="text-[10px] px-1 py-0 border-amber-400 text-amber-600">
                              برون‌سامانه‌ای
                            </Badge>
                          )}
                        </div>
                      </TableCell>

                      <TableCell>
                        <span className="text-sm font-medium">
                          {opp.commodity?.name_fa || opp.commodity?.code || "—"}
                        </span>
                      </TableCell>

                      <TableCell className="text-sm">
                        {opp.quantity ? <bdi dir="ltr">{opp.quantity} {opp.unit}</bdi> : "—"}
                      </TableCell>

                      <TableCell className="text-sm">
                        {opp.indicative_price
                          ? <bdi dir="ltr">{opp.indicative_price} {opp.currency}</bdi>
                          : "—"}
                      </TableCell>

                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs text-muted-foreground">{sourceLabel}</span>
                          {opp.broker && (
                            <div className="flex items-center gap-1 text-[11px] text-primary">
                              <Handshake className="h-3 w-3" />
                              <span>{opp.broker.name}</span>
                            </div>
                          )}
                        </div>
                      </TableCell>

                      <TableCell>
                        <div className="flex flex-col gap-1">
                          {getStatusBadge(opp.status)}
                          {opp.converted_rfq_id && (
                            <Link
                              href={`/${locale}/trade-hub/rfqs/${opp.converted_rfq_id}`}
                              className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline"
                            >
                              <span>استعلام مرتبط</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </Link>
                          )}
                          {opp.converted_supply_listing_id && (
                            <Link
                              href={`/${locale}/trade-hub/supply-listings/${opp.converted_supply_listing_id}`}
                              className="inline-flex items-center gap-1 text-[11px] text-emerald-600 hover:underline"
                            >
                              <span>آگهی مرتبط</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </Link>
                          )}
                        </div>
                      </TableCell>

                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(opp.updated_at).toLocaleDateString("fa-IR")}
                      </TableCell>

                      <TableCell className="text-end">
                        <Link href={`/${locale}/opportunities/${opp.id}`}>
                          <Button variant="outline" className="min-h-7 px-2.5 py-1 text-xs">
                            {oppMsg.actions.viewDetails}
                          </Button>
                        </Link>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          {/* Pagination Controls */}
          {totalCount > 20 && (
            <div className="flex items-center justify-between border-t p-4">
              <span className="text-xs text-muted-foreground">
                صفحه {page} از {Math.ceil(totalCount / 20)}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={!hasPrev || isFetching}
                  className="min-h-8 px-2.5 py-1 gap-1 text-xs"
                >
                  <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
                  <span>قبلی</span>
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!hasNext || isFetching}
                  className="min-h-8 px-2.5 py-1 gap-1 text-xs"
                >
                  <span>بعدی</span>
                  <ChevronRight className="h-4 w-4 rtl:rotate-180" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

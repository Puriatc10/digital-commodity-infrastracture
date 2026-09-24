"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Link from "next/link";
import { VerificationBadge } from "@/components/verification-badge";
import { useAuth } from "@/lib/auth-context";
import { Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";

type VerificationQueueItem = components["schemas"]["VerificationQueue"];

export function VerificationQueueClient({ locale }: { locale: string }) {
  const messages = getMessages((locale || "fa") as EnabledLocale);
  const t = messages.verification.queue;
  const vStatuses = messages.verification.statuses;

  const { state: authState } = useAuth();
  const [filterMode, setFilterMode] = useState<"pending" | "all" | string>("pending");

  const isOperatorOrAdmin =
    authState.status === "authenticated" &&
    authState.systemRoles.some((r) => r === "operator" || r === "admin");

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["verificationQueue", filterMode],
    queryFn: async () => {
      const isPendingParam = filterMode === "pending" ? true : undefined;
      const statusParam =
        filterMode !== "pending" && filterMode !== "all" ? filterMode : undefined;

      const response = await client.GET("/api/organizations/verification/cases/", {
        params: {
          query: {
            is_pending: isPendingParam,
            status: statusParam,
          },
        },
      });

      const raw = response.data;
      if (Array.isArray(raw)) {
        return raw as VerificationQueueItem[];
      }
      if (raw && typeof raw === "object" && "results" in raw && Array.isArray((raw as { results?: unknown }).results)) {
        return (raw as { results: VerificationQueueItem[] }).results;
      }
      return [] as VerificationQueueItem[];
    },
    enabled: isOperatorOrAdmin,
  });

  if (authState.status === "loading") {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isOperatorOrAdmin) {
    return (
      <Card className="p-8 text-center">
        <div className="flex flex-col items-center gap-3">
          <ShieldAlert className="h-10 w-10 text-destructive" />
          <h2 className="text-lg font-semibold text-destructive">{t.unauthorizedTitle}</h2>
          <p className="text-sm text-muted-foreground">
            {t.unauthorizedDesc}
          </p>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-4">
          <CardTitle className="text-lg font-bold">{t.tableTitle}</CardTitle>
          <Button
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 min-h-8 px-2.5 py-1 text-xs"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            {t.refresh}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="w-64 space-y-1">
              <label className="text-sm font-medium">{t.filterLabel}</label>
              <Select value={filterMode} onValueChange={(val) => setFilterMode(val)}>
                <SelectTrigger>
                  <SelectValue placeholder={t.filterLabel} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pending">{t.pendingOnly}</SelectItem>
                  <SelectItem value="all">{t.allCases}</SelectItem>
                  <SelectItem value="documents_submitted">{vStatuses.documents_submitted}</SelectItem>
                  <SelectItem value="under_review">{vStatuses.under_review}</SelectItem>
                  <SelectItem value="basic_verified">{vStatuses.basic_verified}</SelectItem>
                  <SelectItem value="verified">{vStatuses.verified}</SelectItem>
                  <SelectItem value="suspended">{vStatuses.suspended}</SelectItem>
                  <SelectItem value="unverified">{vStatuses.unverified}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : isError ? (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-center text-sm text-destructive">
              {t.table.error}
            </div>
          ) : !data || data.length === 0 ? (
            <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
              {t.table.empty}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t.table.orgName}</TableHead>
                    <TableHead>{t.table.status}</TableHead>
                    <TableHead>{t.table.version}</TableHead>
                    <TableHead>{t.table.updatedAt}</TableHead>
                    <TableHead>{t.table.actions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-medium">{item.organization_name}</TableCell>
                      <TableCell>
                        <VerificationBadge status={item.status} />
                      </TableCell>
                      <TableCell>v{item.version}</TableCell>
                      <TableCell>
                        {new Date(item.updated_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/${locale}/operator/verification/${item.organization_id}`}
                          className="inline-flex items-center justify-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
                        >
                          {t.table.reviewAction}
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

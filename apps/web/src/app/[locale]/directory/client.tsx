"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Loader2 } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { FormEvent } from "react";
import Link from "next/link";
import { VerificationBadge } from "@/components/verification-badge";
import type { components } from "@/lib/api/generated/schema";
import { getMessages, type Messages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";

type Organization = components["schemas"]["DirectoryOrganization"];
type CommodityItem = components["schemas"]["CommodityDefinition"];

function getCapabilityBadge(cap: string, t: Messages["directory"]) {
  switch (cap) {
    case "buyer":
      return (
        <Badge variant="outline" key={cap}>
          {t.filters.roles.buyer}
        </Badge>
      );
    case "supplier":
      return (
        <Badge variant="outline" key={cap}>
          {t.filters.roles.supplier}
        </Badge>
      );
    case "broker":
      return (
        <Badge variant="outline" key={cap}>
          {t.filters.roles.broker}
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" key={cap}>
          {cap}
        </Badge>
      );
  }
}

export function DirectoryClient() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const locale = ((pathname?.split("/")[1] as EnabledLocale) || "fa") as EnabledLocale;
  const messages = getMessages(locale);
  const t = messages.directory;
  const vStatuses = messages.verification.statuses;

  const search = searchParams.get("search") || "";
  const capability = searchParams.get("capability") || "";
  const country = searchParams.get("country") || "";
  const commodity = searchParams.get("commodity") || "";
  const verification = searchParams.get("verification") || "";

  // Fetch available commodities for the filter dropdown
  const { data: commodities } = useQuery<CommodityItem[]>({
    queryKey: ["commodities"],
    queryFn: async () => {
      const { data, error, response } = await client.GET("/api/commodities/");
      if (error || !response.ok || !data) return [];
      return data as CommodityItem[];
    },
  });

  // Fetch directory organizations with filters
  const { data, isLoading, isError } = useQuery<Organization[]>({
    queryKey: [
      "organizations",
      "directory",
      { search, capability, country, commodity, verification },
    ],
    queryFn: async () => {
      const { data, error, response } = await client.GET(
        "/api/organizations/directory/",
        {
          params: {
            query: {
              search: search || undefined,
              capability: capability ? [capability] : undefined,
              country: country || undefined,
              commodity: commodity ? [commodity] : undefined,
              verification: verification ? [verification] : undefined,
            },
          },
        }
      );
      if (error || !response.ok || !data) {
        throw error || new Error("Failed to load directory");
      }
      return data as Organization[];
    },
  });

  const updateFilters = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  const handleSearchSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const searchVal = formData.get("search") as string;
    updateFilters("search", searchVal);
  };

  return (
    <div className="flex flex-col gap-4">
      <Card className="p-4 shadow-sm">
        <form
          onSubmit={handleSearchSubmit}
          className="flex flex-col gap-4 sm:flex-row sm:items-end flex-wrap"
        >
          {/* Search by Name */}
          <div className="flex-1 min-w-[200px] space-y-1">
            <label htmlFor="search" className="text-sm font-medium">
              {t.filters.searchLabel}
            </label>
            <div className="relative">
              <Search className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="search"
                name="search"
                defaultValue={search}
                placeholder={t.filters.searchPlaceholder}
                className="pl-8 pr-8"
              />
            </div>
          </div>

          {/* Country filter */}
          <div className="w-full sm:w-36 space-y-1">
            <label htmlFor="country" className="text-sm font-medium">
              {t.filters.countryLabel}
            </label>
            <Input
              id="country"
              name="country"
              defaultValue={country}
              placeholder={t.filters.countryPlaceholder}
              onChange={(e) => updateFilters("country", e.target.value.trim().toUpperCase())}
            />
          </div>

          {/* Capability filter */}
          <div className="w-full sm:w-40 space-y-1">
            <label className="text-sm font-medium">{t.filters.capabilityLabel}</label>
            <Select
              value={capability}
              onValueChange={(val) => updateFilters("capability", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t.filters.capabilityAll} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t.filters.capabilityAll}</SelectItem>
                <SelectItem value="buyer">{t.filters.roles.buyer}</SelectItem>
                <SelectItem value="supplier">{t.filters.roles.supplier}</SelectItem>
                <SelectItem value="broker">{t.filters.roles.broker}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Commodity filter */}
          <div className="w-full sm:w-44 space-y-1">
            <label className="text-sm font-medium">{t.filters.commodityLabel}</label>
            <Select
              value={commodity}
              onValueChange={(val) => updateFilters("commodity", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t.filters.commodityAll} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t.filters.commodityAll}</SelectItem>
                {commodities
                  ?.filter((c) => c && typeof c.code === "string" && c.code.length > 0)
                  .map((c) => (
                    <SelectItem key={c.code} value={c.code}>
                      {c.name_fa || c.name_en || c.code}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>

          {/* Verification Status filter */}
          <div className="w-full sm:w-48 space-y-1">
            <label className="text-sm font-medium">{t.filters.verificationLabel}</label>
            <Select
              value={verification}
              onValueChange={(val) => updateFilters("verification", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t.filters.verificationAll} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t.filters.verificationAll}</SelectItem>
                <SelectItem value="verified">{vStatuses.verified}</SelectItem>
                <SelectItem value="basic_verified">{vStatuses.basic_verified}</SelectItem>
                <SelectItem value="documents_submitted">{vStatuses.documents_submitted}</SelectItem>
                <SelectItem value="under_review">{vStatuses.under_review}</SelectItem>
                <SelectItem value="unverified">{vStatuses.unverified}</SelectItem>
                <SelectItem value="suspended">{vStatuses.suspended}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button type="submit" variant="outline" className="w-full sm:w-auto">
            {t.filters.apply}
          </Button>
        </form>
      </Card>

      <Card className="shadow-sm">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.table.name}</TableHead>
                <TableHead>{t.table.country}</TableHead>
                <TableHead>{t.table.capabilities}</TableHead>
                <TableHead>{t.table.commodities}</TableHead>
                <TableHead>{t.table.verification}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-primary" />
                  </TableCell>
                </TableRow>
              ) : isError ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-destructive">
                    {t.table.error}
                  </TableCell>
                </TableRow>
              ) : data && data.length > 0 ? (
                data.map((org: Organization) => (
                  <TableRow key={org.id}>
                    <TableCell className="font-medium">
                      <Link
                        href={`/${locale}/directory/${org.id}`}
                        className="text-primary hover:underline font-semibold"
                      >
                        {org.name}
                      </Link>
                    </TableCell>
                    <TableCell>{org.country || "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {org.capabilities.length > 0
                          ? org.capabilities.map((cap) => getCapabilityBadge(cap, t))
                          : "-"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {org.commodities.length > 0
                          ? org.commodities.map((comm) => (
                              <Badge variant="secondary" key={comm}>
                                {comm}
                              </Badge>
                            ))
                          : "-"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <VerificationBadge status={org.verification_status} />
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    {t.table.empty}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

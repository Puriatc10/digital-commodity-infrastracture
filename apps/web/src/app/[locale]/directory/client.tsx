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

type Organization = components["schemas"]["DirectoryOrganization"];
type CommodityItem = components["schemas"]["CommodityDefinition"];

function getCapabilityBadge(cap: string) {
  switch (cap) {
    case "buyer":
      return (
        <Badge variant="outline" key={cap}>
          خریدار
        </Badge>
      );
    case "supplier":
      return (
        <Badge variant="outline" key={cap}>
          تامین‌کننده
        </Badge>
      );
    case "broker":
      return (
        <Badge variant="outline" key={cap}>
          کارگزار
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
  const locale = pathname.split("/")[1] || "fa";

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
              جستجو در نام سازمان
            </label>
            <div className="relative">
              <Search className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="search"
                name="search"
                defaultValue={search}
                placeholder="نام سازمان..."
                className="pl-8 pr-8"
              />
            </div>
          </div>

          {/* Country filter */}
          <div className="w-full sm:w-36 space-y-1">
            <label htmlFor="country" className="text-sm font-medium">
              فیلتر کشور
            </label>
            <Input
              id="country"
              name="country"
              defaultValue={country}
              placeholder="مثلاً IR..."
              onChange={(e) => updateFilters("country", e.target.value.trim().toUpperCase())}
            />
          </div>

          {/* Capability filter */}
          <div className="w-full sm:w-40 space-y-1">
            <label className="text-sm font-medium">نقش</label>
            <Select
              value={capability}
              onValueChange={(val) => updateFilters("capability", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder="همه" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">همه</SelectItem>
                <SelectItem value="buyer">خریدار</SelectItem>
                <SelectItem value="supplier">تامین‌کننده</SelectItem>
                <SelectItem value="broker">کارگزار</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Commodity filter */}
          <div className="w-full sm:w-44 space-y-1">
            <label className="text-sm font-medium">کالا</label>
            <Select
              value={commodity}
              onValueChange={(val) => updateFilters("commodity", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder="همه کالاها" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">همه کالاها</SelectItem>
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
            <label className="text-sm font-medium">وضعیت تاییدیه</label>
            <Select
              value={verification}
              onValueChange={(val) => updateFilters("verification", val === "all" ? "" : val)}
            >
              <SelectTrigger>
                <SelectValue placeholder="همه وضعیت‌ها" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">همه وضعیت‌ها</SelectItem>
                <SelectItem value="verified">تایید شده</SelectItem>
                <SelectItem value="basic_verified">تایید اولیه</SelectItem>
                <SelectItem value="documents_submitted">مدارک ارسال شده</SelectItem>
                <SelectItem value="under_review">در حال بررسی</SelectItem>
                <SelectItem value="unverified">تایید نشده</SelectItem>
                <SelectItem value="suspended">تعلیق شده</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button type="submit" variant="outline" className="w-full sm:w-auto">
            اعمال
          </Button>
        </form>
      </Card>

      <Card className="shadow-sm">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>نام شرکت</TableHead>
                <TableHead>کشور</TableHead>
                <TableHead>نقش‌ها</TableHead>
                <TableHead>کالاها</TableHead>
                <TableHead>تاییدیه</TableHead>
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
                    خطا در دریافت اطلاعات
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
                          ? org.capabilities.map((cap) => getCapabilityBadge(cap))
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
                    شرکتی یافت نشد.
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

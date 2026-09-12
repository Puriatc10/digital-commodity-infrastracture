"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search, Loader2 } from "lucide-react";
import Link from "next/link";
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
import { components } from "@/lib/api/generated/schema";

type Organization = components["schemas"]["DirectoryOrganization"];

function getVerificationBadge(status: string) {
  switch (status) {
    case "verified":
      return <Badge variant="default" className="bg-green-600 hover:bg-green-700">تایید شده</Badge>;
    case "basic_verified":
      return <Badge variant="default" className="bg-blue-600 hover:bg-blue-700">تاییدیه پایه</Badge>;
    case "under_review":
      return <Badge variant="secondary">در حال بررسی</Badge>;
    case "documents_submitted":
      return <Badge variant="outline" className="border-blue-500 text-blue-600">مدارک ارسال شده</Badge>;
    case "suspended":
      return <Badge variant="destructive">معلق</Badge>;
    case "unverified":
    default:
      return <Badge variant="outline">تایید نشده</Badge>;
  }
}

function getCapabilityBadge(cap: string) {
  switch (cap) {
    case "buyer":
      return <Badge variant="outline" key={cap}>خریدار</Badge>;
    case "supplier":
      return <Badge variant="outline" key={cap}>تامین‌کننده</Badge>;
    case "broker":
      return <Badge variant="outline" key={cap}>کارگزار</Badge>;
    default:
      return <Badge variant="outline" key={cap}>{cap}</Badge>;
  }
}

export function DirectoryClient() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const locale = pathname.split('/')[1] || 'fa';

  const search = searchParams.get("search") || "";
  const capability = searchParams.get("capability") || "";
  const country = searchParams.get("country") || "";
  const commodity = searchParams.get("commodity") || "";
  const verification = searchParams.get("verification") || "";

  const { data, isLoading, isError } = useQuery({
    queryKey: ["organizations", "directory", { search, capability, country, commodity, verification }],
    queryFn: async () => {
      const { data, error } = await client.GET("/api/organizations/directory/", {
        params: {
          query: {
            search: search || undefined,
            capability: capability ? [capability] : undefined,
            country: country || undefined,
            commodity: commodity ? [commodity] : undefined,
            verification: verification ? [verification] : undefined,
          } as unknown as undefined,
        },
      });
      if (error) throw error;
      return data;
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
        <form onSubmit={handleSearchSubmit} className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <label htmlFor="search" className="text-sm font-medium">جستجو</label>
            <div className="relative">
              <Search className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="search"
                name="search"
                defaultValue={search}
                placeholder="نام شرکت..."
                className="pl-8 pr-8"
              />
            </div>
          </div>

          <div className="w-full sm:w-48 space-y-1">
            <label className="text-sm font-medium">نقش</label>
            <Select value={capability} onValueChange={(val) => updateFilters("capability", val === "all" ? "" : val)}>
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

          <div className="w-full sm:w-48 space-y-1">
            <label htmlFor="country" className="text-sm font-medium">کشور</label>
            <Input
              id="country"
              name="country"
              defaultValue={country}
              placeholder="مثال: IR"
              onBlur={(e) => updateFilters("country", e.target.value)}
            />
          </div>

          <div className="w-full sm:w-48 space-y-1">
            <label htmlFor="commodity" className="text-sm font-medium">کالا</label>
            <Input
              id="commodity"
              name="commodity"
              defaultValue={commodity}
              placeholder="کد کالا..."
              onBlur={(e) => updateFilters("commodity", e.target.value)}
            />
          </div>

          <div className="w-full sm:w-48 space-y-1">
            <label className="text-sm font-medium">وضعیت تاییدیه</label>
            <Select value={verification} onValueChange={(val) => updateFilters("verification", val === "all" ? "" : val)}>
              <SelectTrigger>
                <SelectValue placeholder="همه" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">همه</SelectItem>
                <SelectItem value="verified">تایید شده</SelectItem>
                <SelectItem value="basic_verified">تاییدیه پایه</SelectItem>
                <SelectItem value="under_review">در حال بررسی</SelectItem>
                <SelectItem value="documents_submitted">مدارک ارسال شده</SelectItem>
                <SelectItem value="unverified">تایید نشده</SelectItem>
                <SelectItem value="suspended">معلق</SelectItem>
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
                      <Link href={`/${locale}/directory/${org.id}`} className="text-blue-600 hover:underline">
                        {org.name}
                      </Link>
                    </TableCell>
                    <TableCell>{org.country || "-"}</TableCell>
                    <TableCell className="flex gap-1 flex-wrap">
                      {org.capabilities.length > 0
                        ? org.capabilities.map(cap => getCapabilityBadge(cap))
                        : "-"
                      }
                    </TableCell>
                    <TableCell>
                      {org.commodities.length > 0
                        ? org.commodities.join(", ")
                        : "-"
                      }
                    </TableCell>
                    <TableCell>
                      {getVerificationBadge(org.verification_status)}
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

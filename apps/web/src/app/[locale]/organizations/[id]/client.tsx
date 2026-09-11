"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface OrganizationProfileClientProps {
  id: string;
}

function getVerificationBadge(status: string) {
  switch (status) {
    case "verified":
      return <Badge variant="default" className="bg-green-600 hover:bg-green-700">تایید شده</Badge>;
    case "basic_verified":
      return <Badge variant="default" className="bg-blue-600 hover:bg-blue-700">تاییدیه پایه</Badge>;
    case "under_review":
      return <Badge variant="outline">در حال بررسی</Badge>;
    case "suspended":
      return <Badge variant="destructive">معلق</Badge>;
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

export function OrganizationProfileClient({ id }: OrganizationProfileClientProps) {
  const { data: org, isLoading, isError, error } = useQuery({
    queryKey: ["organization", id],
    queryFn: async () => {
      const { data, error } = await client.GET("/api/organizations/{id}/", {
        params: {
          path: {
            id,
          },
        },
      });
      if (error) {
        throw error;
      }
      return data;
    },
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (isError || !org) {
    return (
      <Card className="border-destructive shadow-sm">
        <CardContent className="pt-6">
          <div className="text-center text-destructive">
            شرکت مورد نظر یافت نشد یا دسترسی به آن امکان‌پذیر نیست.
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      {/* Company Information */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">اطلاعات شرکت</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex justify-between border-b pb-2">
            <span className="text-sm text-muted-foreground">نام</span>
            <span className="font-medium">{org.name}</span>
          </div>
          <div className="flex justify-between border-b pb-2">
            <span className="text-sm text-muted-foreground">شناسه ثبت</span>
            <span className="font-medium">{org.registration_identifier || "-"}</span>
          </div>
          <div className="flex justify-between border-b pb-2">
            <span className="text-sm text-muted-foreground">وب‌سایت</span>
            <span className="font-medium" dir="ltr">
              {org.website ? (
                <a href={org.website} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                  {org.website}
                </a>
              ) : (
                "-"
              )}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Capabilities & Commodities */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">نقش‌ها و کالاها</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <span className="text-sm text-muted-foreground block">نقش‌های تجاری</span>
            <div className="flex flex-wrap gap-2">
              {org.capabilities && org.capabilities.length > 0 ? (
                org.capabilities.map(cap => getCapabilityBadge(cap))
              ) : (
                <span className="text-sm">-</span>
              )}
            </div>
          </div>
          <div className="space-y-2">
            <span className="text-sm text-muted-foreground block">کالاهای فعال</span>
            <div className="flex flex-wrap gap-2">
              {org.commodities && org.commodities.length > 0 ? (
                org.commodities.map(comm => (
                  <Badge variant="secondary" key={comm}>{comm}</Badge>
                ))
              ) : (
                <span className="text-sm">-</span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Geography & Verification */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">جغرافیا و تاییدیه</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex justify-between border-b pb-2 items-center">
            <span className="text-sm text-muted-foreground">کشور</span>
            <span className="font-medium">{org.country || "-"}</span>
          </div>
          <div className="flex justify-between border-b pb-2 items-center">
            <span className="text-sm text-muted-foreground">وضعیت تاییدیه</span>
            <span>{getVerificationBadge(org.verification_status || "unverified")}</span>
          </div>
        </CardContent>
      </Card>

      {/* Activity Summary */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">خلاصه فعالیت</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md bg-muted p-4 text-center text-sm text-muted-foreground">
            داده‌های فعالیت در حال حاضر در دسترس نیست.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

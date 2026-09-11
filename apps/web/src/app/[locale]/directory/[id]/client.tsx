"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";



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

export function ProfileClient({ id }: { id: string }) {
  const { data: profile, isLoading, isError } = useQuery({
    queryKey: ["organizations", "profiles", id],
    queryFn: async () => {
      const { data, error, response } = await client.GET("/api/organizations/profiles/{id}/", {
        params: { path: { id } },
      });
      if (error || !response.ok) throw error || new Error("Profile not found");
      return data;
    },
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <Card className="p-8 text-center text-destructive">
        شرکت یافت نشد یا دسترسی مجاز نیست.
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>اطلاعات شرکت</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-muted-foreground">نام شرکت</p>
            <p className="text-base">{profile.name}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">کشور</p>
            <p className="text-base">{profile.country || "-"}</p>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground">وب‌سایت</p>
            <p className="text-base">
              {profile.website ? (
                <a href={profile.website} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  {profile.website}
                </a>
              ) : (
                "-"
              )}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>وضعیت تاییدیه</CardTitle>
        </CardHeader>
        <CardContent>
          <div>
            {getVerificationBadge(profile.verification_status)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>نقش‌ها و کالاها</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">نقش‌ها</p>
            <div className="flex gap-2 flex-wrap">
              {profile.capabilities.length > 0
                ? profile.capabilities.map((cap) => getCapabilityBadge(cap))
                : "-"
              }
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">کالاها</p>
            <div className="flex gap-2 flex-wrap">
              {profile.commodities.length > 0
                ? profile.commodities.map((comm) => <Badge variant="secondary" key={comm}>{comm}</Badge>)
                : "-"
              }
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>خلاصه فعالیت</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">اطلاعات فعالیت در حال حاضر در دسترس نیست.</p>
        </CardContent>
      </Card>
    </div>
  );
}

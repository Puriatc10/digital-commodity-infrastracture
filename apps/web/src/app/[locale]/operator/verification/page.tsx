"use client";

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
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

export default function VerificationQueuePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["verificationQueue", "pending"],
    queryFn: async () => {
      const response = await client.GET("/api/organizations/verification/cases/", {
        params: {
          query: { is_pending: true } as unknown as never,
        },
      });

      if ((response as { error?: { detail?: string } }).error) {

        throw new Error((response as { error?: { detail?: string } }).error?.detail || "خطا در بارگذاری صف بررسی.");
      }

      return (response as { data?: unknown[] }).data || [];
    },
  });

  return (
    <div className="container mx-auto p-4 space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>صف بررسی</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <p>در حال بارگذاری...</p>}
          {isError && <p className="text-red-500">خطا در بارگذاری صف بررسی.</p>}
          {!isLoading && !isError && data && data.length === 0 && (
            <p>پرونده بررسی در انتظار وجود ندارد.</p>
          )}
          {!isLoading && !isError && data && data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>سازمان</TableHead>
                  <TableHead>وضعیت</TableHead>
                  <TableHead>آخرین بروزرسانی</TableHead>
                  <TableHead>عملیات</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
{(data as { id: string, organization_id: string, organization_name: string, status: string, updated_at: string }[]).map((caseItem) => (
                  <TableRow key={caseItem.id}>
                    <TableCell className="font-medium">
                      {caseItem.organization_name}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          caseItem.status === "documents_submitted"
                            ? "outline"
                            : caseItem.status === "under_review"
                            ? "secondary"
                            : "default"
                        }
                      >
                        {caseItem.status.replace("_", " ")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {new Date(caseItem.updated_at).toLocaleString("fa-IR")}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/fa/operator/verification/${caseItem.organization_id}`}
                        className="text-blue-600 hover:underline"
                      >
                        Review
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

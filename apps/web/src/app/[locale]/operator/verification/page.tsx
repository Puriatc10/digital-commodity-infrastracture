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
          query: {
            is_pending: true,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any,
        },
      });
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((response as any).error) {
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        throw new Error((response.error as any)?.detail || "Failed to load queue");
      }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ((response.data as any)?.results || response.data) || [];
    },
  });

  return (
    <div className="container mx-auto p-4 space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Verification Queue</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <p>Loading queue...</p>}
          {isError && <p className="text-red-500">Error loading verification queue.</p>}
          {!isLoading && !isError && data && data.length === 0 && (
            <p>No pending verification cases.</p>
          )}
          {!isLoading && !isError && data && data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Organization</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Updated</TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
{data.map((caseItem: any /* eslint-disable-line @typescript-eslint/no-explicit-any */) => (
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

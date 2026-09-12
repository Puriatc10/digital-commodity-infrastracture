"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient as client } from "@/lib/api/client";
import { useParams } from "next/navigation";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";


export default function VerificationCaseDetailPage() {
  const params = useParams();
  const organizationId = params.id as string;
  const queryClient = useQueryClient();
  const { state: authState } = useAuth();

  const isOperatorOrAdmin = authState.status === "authenticated" && authState.systemRoles.some(r => r === "operator" || r === "admin");
  const [reason, setReason] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [actionError, setActionError] = useState("");

  const { data: verificationData, isLoading, isError, refetch } = useQuery({
    queryKey: ["verificationCase", organizationId],
    queryFn: async () => {
      const response = await client.GET(
        "/api/organizations/{org_id}/verification/",
        {
          params: { path: { org_id: organizationId } },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((response as any).error) {
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        throw new Error((response.error as any)?.detail || "Failed to load case detail");
      }
      return response.data;
    },
  });

  const { data: documentsData, refetch: refetchDocs, isError: documentsIsError } = useQuery({
    queryKey: ["verificationDocuments", organizationId],
    queryFn: async () => {
      const response = await client.GET("/api/documents/", {
        params: { query: { organization: organizationId } },
      });
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((response as any).error) {
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        throw new Error((response.error as any)?.detail || "Failed to load documents");
      }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ((response.data as any)?.results || response.data) || [];
    },
  });

  const handleMutationSuccess = () => {
    setActionError("");
    setReason("");
    setInternalNote("");
    queryClient.invalidateQueries({ queryKey: ["verificationCase", organizationId] });
    queryClient.invalidateQueries({ queryKey: ["verificationDocuments", organizationId] });
  };


// eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleMutationError = (error: any) => {
    setActionError(error.message || "Action failed");
    // Force refetch on error to catch stale state
    refetch();
    refetchDocs();
  };

  const startReviewMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/start_review/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to start review");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const approveBasicMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/approve_basic/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to approve basic");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const approveFullMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/approve_full/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to approve full");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const rejectMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/reject/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0, reason },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to reject");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const suspendMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/suspend/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0, reason },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to suspend");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const reopenMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/reopen/",
        {
          params: { path: { org_id: organizationId } },
          body: { expected_version: verificationData?.version ?? 0 },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to reopen");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const addNoteMutation = useMutation({
    mutationFn: async () => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/notes/",
        {
          params: { path: { org_id: organizationId } },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          body: { note: internalNote } as any,
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((res as any).error) throw new Error(((res as any).error as any)?.detail || "Failed to add note");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

  const reviewChecklistMutation = useMutation({
    mutationFn: async ({ documentId, outcome }: { documentId: string; outcome: "accepted" | "rejected" }) => {
      const res = await client.POST(
        "/api/organizations/{org_id}/verification/checklist/",
        {
          params: { path: { org_id: organizationId } },
          body: { document_id: documentId, outcome, expected_version: verificationData?.version ?? 0 },
        }
      );
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (res.error) throw new Error((res.error as any)?.detail || "Failed to review checklist");
      return res.data;
    },
    onSuccess: handleMutationSuccess,
    onError: handleMutationError,
  });

    if (authState.status === "loading") return <div>Loading case details...</div>;
  if (!isOperatorOrAdmin) return <div className="text-red-500">Unauthorized</div>;
  if (isLoading) return <div>Loading case details...</div>;
  if (isError || !verificationData) return <div className="text-red-500">Error loading case details.</div>;

  return (
    <div className="container mx-auto p-4 space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Case Verification Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <strong>Status: </strong>
            <Badge variant="outline">{verificationData.status.replace("_", " ")}</Badge>
          </div>
          <div>
            <strong>Version: </strong> {verificationData.version}
          </div>

          {actionError && <div className="text-red-600 bg-red-100 p-2 rounded">{actionError}</div>}

          <div className="flex gap-2 flex-wrap">
            {verificationData.status === "documents_submitted" && (
              <Button onClick={() => startReviewMutation.mutate()} disabled={startReviewMutation.isPending}>
                Start Review
              </Button>
            )}
            {verificationData.status === "under_review" && (
              <>
                <Button onClick={() => approveBasicMutation.mutate()} disabled={approveBasicMutation.isPending} variant="outline">
                  Approve Basic
                </Button>
                <Button onClick={() => approveFullMutation.mutate()} disabled={approveFullMutation.isPending} variant="default">
                  Approve Full
                </Button>
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="Rejection Reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                  <Button
                    onClick={() => rejectMutation.mutate()}
                    disabled={rejectMutation.isPending || !reason}
                    variant="outline"
                  >
                    Reject
                  </Button>
                </div>
              </>
            )}
            {(verificationData.status === "basic_verified" || verificationData.status === "verified") && (
              <div className="flex items-center gap-2">
                <Input
                  placeholder="Suspension Reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <Button
                  onClick={() => suspendMutation.mutate()}
                  disabled={suspendMutation.isPending || !reason}
                  variant="outline"
                >
                  Suspend
                </Button>
              </div>
            )}
            {(verificationData.status === "suspended" || verificationData.status === "basic_verified") && (
              <Button onClick={() => reopenMutation.mutate()} disabled={reopenMutation.isPending} variant="outline">
                Reopen to Under Review
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documents Checklist</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-4">
{documentsIsError ? <p className="text-red-500">Error loading documents.</p> : documentsData && documentsData.length > 0 ? documentsData.map((doc: any /* eslint-disable-line @typescript-eslint/no-explicit-any */) => (
              <li key={doc.id} className="flex items-center justify-between border p-2 rounded">
                <div>
                  <strong>{doc.type}</strong> - {doc.verification_status}
                </div>
                {verificationData.status === "under_review" && doc.verification_status !== "replaced" && (
                  <div className="flex gap-2">
                    <Button

                      variant="outline"
                      onClick={() => reviewChecklistMutation.mutate({ documentId: doc.id, outcome: "accepted" })}
                    >
                      Accept
                    </Button>
                    <Button

                      variant="outline"
                      onClick={() => reviewChecklistMutation.mutate({ documentId: doc.id, outcome: "rejected" })}
                    >
                      Reject
                    </Button>
                  </div>
                )}
                {doc.verification_status === "replaced" && <Badge variant="outline">Replaced</Badge>}
              </li>
            )) : <p>No documents found.</p>}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Internal Notes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="space-y-2">
{verificationData.notes?.map((note: any /* eslint-disable-line @typescript-eslint/no-explicit-any */) => (
              <li key={note.id} className="border p-2 rounded bg-gray-50">
                <p className="text-sm text-gray-500">{note.actor_email} - {new Date(note.created_at).toLocaleString()}</p>
                <p>{note.note}</p>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <Input
              placeholder="Add internal note..."
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
            />
            <Button onClick={() => addNoteMutation.mutate()} disabled={addNoteMutation.isPending || !internalNote}>
              Add Note
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Decision History</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
{verificationData.decisions?.map((decision: any /* eslint-disable-line @typescript-eslint/no-explicit-any */) => (
              <li key={decision.id} className="border p-2 rounded">
                <p className="text-sm text-gray-500">{decision.actor_email} - {new Date(decision.created_at).toLocaleString()}</p>
                <p>{decision.previous_status} ➔ {decision.new_status}</p>
                {decision.reason && <p className="text-sm text-gray-700 mt-1">Reason: {decision.reason}</p>}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

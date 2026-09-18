"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { CommoditySpecificationView } from "@/components/commodity/commodity-specification-view";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  FileText,
  History,
  Layers,
  Loader2,
  MessageSquare,
  Package,
  RefreshCw,
  Scale,
  Send,
  ShieldCheck,
  Sparkles,
  Tag,
  Users,
  XCircle,
} from "lucide-react";
import { RFQMatchingTab } from "@/components/matching/rfq-matching-tab";
import { RFQComparisonTab } from "@/components/comparison/rfq-comparison-tab";
import { RFQNegotiationTab } from "@/components/negotiation/rfq-negotiation-tab";

type RFQBuilderResponse = components["schemas"]["RFQBuilderResponse"];
type RFQPublicResponse = components["schemas"]["RFQPublicResponse"];
type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
type RFQInvitationResponse = components["schemas"]["RFQInvitationResponse"];
type RFQActivityItem = components["schemas"]["RFQActivityItem"];
type DirectoryOrganization = components["schemas"]["DirectoryOrganization"];

export type WorkspaceTab =
  | "overview"
  | "participants"
  | "activity"
  | "offers"
  | "comparison"
  | "negotiation"
  | "documents"
  | "matches";

export interface RFQWorkspaceClientProps {
  locale?: EnabledLocale;
  rfqId: string;
}

export function RFQWorkspaceClient({ locale = "fa", rfqId }: RFQWorkspaceClientProps) {
  const isRtl = locale === "fa";
  const messages = getMessages(locale);
  const t = messages.rfqWorkspace;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { state } = useAuth();

  // Active navigation tab
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");

  // Core Data State
  const [rfq, setRfq] = useState<RFQBuilderResponse | RFQPublicResponse | null>(null);
  const [schema, setSchema] = useState<CommoditySchemaVersion | null>(null);
  const [invitations, setInvitations] = useState<RFQInvitationResponse[]>([]);
  const [ownInvitation, setOwnInvitation] = useState<RFQInvitationResponse | null>(null);
  const [activity, setActivity] = useState<RFQActivityItem[]>([]);
  const [directoryOrgs, setDirectoryOrgs] = useState<DirectoryOrganization[]>([]);

  // Loading States
  const [isLoadingRfq, setIsLoadingRfq] = useState<boolean>(true);
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);
  const [isLoadingInvitations, setIsLoadingInvitations] = useState<boolean>(false);
  const [isLoadingActivity, setIsLoadingActivity] = useState<boolean>(false);
  const [isNotFound, setIsNotFound] = useState<boolean>(false);

  // Lifecycle Action States
  const [isActionLoading, setIsActionLoading] = useState<boolean>(false);
  const [showCloseModal, setShowCloseModal] = useState<boolean>(false);
  const [showCancelModal, setShowCancelModal] = useState<boolean>(false);
  const [cancelReason, setCancelReason] = useState<string>("");
  const [cancelReasonError, setCancelReasonError] = useState<string | null>(null);
  const [staleConflict, setStaleConflict] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Invite Modal States (for Buyer)
  const [showInviteModal, setShowInviteModal] = useState<boolean>(false);
  const [inviteSearch, setInviteSearch] = useState<string>("");
  const [isInvitingId, setIsInvitingId] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null);

  // Decline Modal States (for Invitee)
  const [showDeclineModal, setShowDeclineModal] = useState<boolean>(false);
  const [declineReason, setDeclineReason] = useState<string>("");
  const [isDeclining, setIsDeclining] = useState<boolean>(false);

  // Session & Role Checks
  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");
  const currentOrgId =
    state.status === "authenticated" ? state.currentOrganization?.organization.id : null;
  const currentOrgRole =
    state.status === "authenticated" ? state.currentOrganization?.role : null;
  const isOwnerOrg = Boolean(rfq && currentOrgId && rfq.organization.id === currentOrgId);
  const isOwnerOrManager = currentOrgRole === "owner" || currentOrgRole === "manager";
  const canManage = isOperatorOrAdmin || (isOwnerOrg && isOwnerOrManager);
  const isExternal = Boolean(rfq && !isOperatorOrAdmin && !isOwnerOrg);
  const canAccessMatching = Boolean(rfq && (isOperatorOrAdmin || isOwnerOrg));
  const canAccessComparison = Boolean(rfq && (isOperatorOrAdmin || isOwnerOrg));

  // Track previous organization ID to invalidate cache on switch
  const previousOrgIdRef = useRef<string | null>(null);

  // Session Invalidation Effect
  useEffect(() => {
    if (
      previousOrgIdRef.current &&
      previousOrgIdRef.current !== currentOrgId
    ) {
      queryClient.removeQueries({ queryKey: ["rfq", rfqId] });
      queryClient.removeQueries({ queryKey: ["rfq-comparison", rfqId] });
      queryClient.removeQueries({ queryKey: ["rfq-decision-run", rfqId] });
      queryClient.removeQueries({ queryKey: ["rfq-invitations", rfqId] });
      queryClient.removeQueries({ queryKey: ["rfq-activity", rfqId] });
      queryClient.removeQueries({ queryKey: ["rfq-invitation-me", rfqId] });
      queryClient.removeQueries({ queryKey: ["matching-runs", rfqId] });
      queryClient.removeQueries({ queryKey: ["matching-candidates"] });
      queryClient.removeQueries({ queryKey: ["offer-history"] });
      setRfq(null);
      setSchema(null);
      setInvitations([]);
      setOwnInvitation(null);
      setActivity([]);
      setStaleConflict(false);
      setActionError(null);
      setActionSuccess(null);
      setActiveTab("overview");
    }
    if (currentOrgId) {
      previousOrgIdRef.current = currentOrgId;
    } else if (state.status === "unauthenticated") {
      previousOrgIdRef.current = null;
    }
  }, [currentOrgId, queryClient, rfqId, state.status]);

  // Trigger to refetch all workspace data on mutations / conflict
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const triggerRefresh = useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // 1. Authoritative RFQ Fetch
  useEffect(() => {
    let ignore = false;
    async function fetchRfq() {
      try {
        const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/", {
          params: { path: { rfq_id: rfqId } },
        });
        if (ignore) return;
        if (response.status === 404) {
          setIsNotFound(true);
          setRfq(null);
          return;
        }
        if (response.ok && data) {
          setRfq(data);
          setIsNotFound(false);
        }
      } catch {
        if (!ignore) {
          setIsNotFound(true);
          setRfq(null);
        }
      } finally {
        if (!ignore) {
          setIsLoadingRfq(false);
        }
      }
    }
    void fetchRfq();
    return () => {
      ignore = true;
    };
  }, [rfqId, currentOrgId, refreshTrigger]);

  // 2. Exact Historical Schema Fetch
  const schemaVersionId = rfq?.schema_version_id;
  useEffect(() => {
    if (!schemaVersionId) return;
    const currentSchemaId = schemaVersionId;
    let ignore = false;
    async function loadExactSchema() {
      try {
        const { data, response } = await apiClient.GET("/api/commodity-schemas/{id}/", {
          params: { path: { id: currentSchemaId } },
        });
        if (!ignore && response.ok && data) {
          setSchema(data);
        }
      } catch {
        if (!ignore) {
          setSchema(null);
        }
      } finally {
        if (!ignore) {
          setIsLoadingSchema(false);
        }
      }
    }
    void loadExactSchema();
    return () => {
      ignore = true;
    };
  }, [schemaVersionId]);

  // 3. Invitations Fetch (Context-Aware)
  useEffect(() => {
    let ignore = false;
    async function fetchInvitations() {
      if (canManage) {
        try {
          const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/invitations/", {
            params: { path: { rfq_id: rfqId } },
          });
          if (!ignore && response.ok && Array.isArray(data)) {
            setInvitations(data);
          }
        } catch {
          if (!ignore) {
            setInvitations([]);
          }
        } finally {
          if (!ignore) {
            setIsLoadingInvitations(false);
          }
        }
      } else if (isExternal) {
        try {
          const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/invitations/me/", {
            params: { path: { rfq_id: rfqId } },
          });
          if (!ignore && response.ok && data) {
            setOwnInvitation(data);
            // If invitation is in "invited" status, record view automatically
            if (data.status === "invited") {
              void apiClient.POST(
                "/api/trade-hub/rfqs/{rfq_id}/invitations/{invitation_id}/view/",
                {
                  params: {
                    path: { rfq_id: rfqId, invitation_id: data.id },
                  },
                }
              );
            }
          } else if (!ignore) {
            setOwnInvitation(null);
          }
        } catch {
          if (!ignore) {
            setOwnInvitation(null);
          }
        }
      }
    }
    void fetchInvitations();
    return () => {
      ignore = true;
    };
  }, [canManage, isExternal, rfqId, refreshTrigger]);

  // 4. Activity Timeline Fetch
  const hasRfq = Boolean(rfq);
  useEffect(() => {
    if (!hasRfq) return;
    let ignore = false;
    async function fetchActivity() {
      try {
        const { data, response } = await apiClient.GET("/api/trade-hub/rfqs/{rfq_id}/activity/", {
          params: { path: { rfq_id: rfqId } },
        });
        if (!ignore && response.ok && Array.isArray(data)) {
          setActivity(data);
        }
      } catch {
        if (!ignore) {
          setActivity([]);
        }
      } finally {
        if (!ignore) {
          setIsLoadingActivity(false);
        }
      }
    }
    void fetchActivity();
    return () => {
      ignore = true;
    };
  }, [hasRfq, rfqId, refreshTrigger]);

  // 5. Load Directory Organizations for Invite Modal
  const orgId = rfq?.organization.id;
  useEffect(() => {
    if (!showInviteModal) return;
    let ignore = false;
    async function fetchDirectory() {
      try {
        const { data, response } = await apiClient.GET("/api/organizations/directory/");
        if (!ignore && response.ok && Array.isArray(data)) {
          const eligible = data.filter(
            (org) =>
              org.id !== orgId &&
              (org.capabilities.includes("supplier") || org.capabilities.includes("broker"))
          );
          setDirectoryOrgs(eligible);
        }
      } catch {
        // Ignored
      }
    }
    void fetchDirectory();
    return () => {
      ignore = true;
    };
  }, [showInviteModal, orgId]);

  // Lifecycle Action: Close RFQ
  const handleCloseRfq = async () => {
    if (!rfq) return;
    setIsActionLoading(true);
    setActionError(null);
    setStaleConflict(false);
    try {
      const { data, response } = await apiClient.POST("/api/trade-hub/rfqs/{rfq_id}/close/", {
        params: { path: { rfq_id: rfqId } },
        body: { expected_version: rfq.version },
      });
      if (response.status === 409) {
        setStaleConflict(true);
        setShowCloseModal(false);
        triggerRefresh();
        return;
      }
      if (response.ok && data) {
        setRfq(data);
        setShowCloseModal(false);
        setActionSuccess(t.actions.confirmCloseTitle);
        triggerRefresh();
      } else {
        setActionError(t.errors.actionFailed);
      }
    } catch {
      setActionError(t.errors.actionFailed);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Lifecycle Action: Cancel RFQ
  const handleCancelRfq = async () => {
    if (!rfq) return;
    if (rfq.status === "published" && !cancelReason.trim()) {
      setCancelReasonError(t.actions.cancelReasonRequired);
      return;
    }
    setCancelReasonError(null);
    setIsActionLoading(true);
    setActionError(null);
    setStaleConflict(false);
    try {
      const { data, response } = await apiClient.POST("/api/trade-hub/rfqs/{rfq_id}/cancel/", {
        params: { path: { rfq_id: rfqId } },
        body: {
          expected_version: rfq.version,
          reason: cancelReason.trim(),
        },
      });
      if (response.status === 409) {
        setStaleConflict(true);
        setShowCancelModal(false);
        triggerRefresh();
        return;
      }
      if (response.ok && data) {
        setRfq(data);
        setShowCancelModal(false);
        setActionSuccess(t.actions.confirmCancelTitle);
        triggerRefresh();
      } else {
        setActionError(t.errors.actionFailed);
      }
    } catch {
      setActionError(t.errors.actionFailed);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Invite Organization Action
  const handleInviteOrganization = async (targetOrgId: string) => {
    setIsInvitingId(targetOrgId);
    setInviteError(null);
    setInviteSuccess(null);
    try {
      const { response } = await apiClient.POST(
        "/api/trade-hub/rfqs/{rfq_id}/invitations/",
        {
          params: { path: { rfq_id: rfqId } },
          body: { organization_id: targetOrgId },
        }
      );
      if (response.ok) {
        setInviteSuccess(t.participants.inviteSuccess);
        triggerRefresh();
      } else {
        setInviteError(t.participants.inviteError);
      }
    } catch {
      setInviteError(t.participants.inviteError);
    } finally {
      setIsInvitingId(null);
    }
  };

  // Decline Invitation Action (for external participant)
  const handleDeclineInvitation = async () => {
    if (!ownInvitation) return;
    setIsDeclining(true);
    try {
      const { response } = await apiClient.POST(
        "/api/trade-hub/rfqs/{rfq_id}/invitations/{invitation_id}/decline/",
        {
          params: {
            path: { rfq_id: rfqId, invitation_id: ownInvitation.id },
          },
          body: { reason: declineReason.trim() },
        }
      );
      if (response.ok) {
        setShowDeclineModal(false);
        triggerRefresh();
      }
    } catch {
      // Handled
    } finally {
      setIsDeclining(false);
    }
  };

  // 404 / Hidden RFQ Guard
  if (isNotFound) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 text-center" dir={isRtl ? "rtl" : "ltr"}>
        <div className="rounded-full bg-destructive/10 p-4">
          <XCircle className="h-10 w-10 text-destructive" />
        </div>
        <h2 className="text-xl font-bold">{t.rfqNotFoundTitle}</h2>
        <p className="max-w-md text-sm text-muted-foreground">{t.rfqNotFoundDescription}</p>
        <Button variant="outline" onClick={() => router.push(`/${locale}/trade-hub`)}>
          <ArrowRight className="ml-2 h-4 w-4 rtl:mr-2 rtl:ml-0" />
          {t.backToHub}
        </Button>
      </div>
    );
  }

  // Loading Screen
  if (isLoadingRfq || !rfq) {
    return (
      <div className="flex min-h-[400px] items-center justify-center" dir={isRtl ? "rtl" : "ltr"}>
        <div className="flex items-center gap-3 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span>{t.loadingRfq}</span>
        </div>
      </div>
    );
  }

  const getStatusBadgeVariant = (status: string) => {
    switch (status) {
      case "draft":
        return "secondary";
      case "published":
        return "default";
      case "closed":
        return "outline";
      case "cancelled":
        return "destructive";
      default:
        return "secondary";
    }
  };

  const getStatusLabel = (status: string) => {
    return t.statuses[status as keyof typeof t.statuses] || status;
  };

  const getVisibilityLabel = (vis: string) => {
    return t.visibilities[vis as keyof typeof t.visibilities] || vis;
  };

  const filteredDirectory = directoryOrgs.filter((org) => {
    const query = inviteSearch.trim().toLowerCase();
    if (!query) return true;
    return org.name.toLowerCase().includes(query);
  });

  return (
    <div className="flex flex-col gap-6" dir={isRtl ? "rtl" : "ltr"}>
      {/* 1. Header & Operational Status Toolbar */}
      <div className="flex flex-col gap-4 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">
              {rfq.commodity_name_fa || rfq.commodity_name_en} ({rfq.commodity_code})
            </h1>
            <Badge variant={getStatusBadgeVariant(rfq.status)}>
              {getStatusLabel(rfq.status)}
            </Badge>
            <Badge variant="outline">
              {getVisibilityLabel(rfq.visibility)}
            </Badge>
            <Badge variant="secondary" className="font-mono text-xs">
              {t.versionLabel} v{rfq.version}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            {rfq.organization.name} · {rfq.id}
          </p>
        </div>

        {/* Management Toolbar (Buyer Owner/Manager or Operator) */}
        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            {rfq.status === "draft" && (
              <>
                <Button
                  variant="outline"
                  className="min-h-8 px-3 py-1.5 text-xs"
                  onClick={() => router.push(`/${locale}/trade-hub/rfqs/${rfqId}/edit`)}
                >
                  {t.actions.editDraft}
                </Button>
                <Button
                  className="min-h-8 px-3 py-1.5 text-xs bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => {
                    setCancelReason("");
                    setShowCancelModal(true);
                  }}
                >
                  {t.actions.cancelRfq}
                </Button>
              </>
            )}
            {rfq.status === "published" && (
              <>
                <Button
                  variant="outline"
                  className="min-h-8 px-3 py-1.5 text-xs"
                  onClick={() => setShowCloseModal(true)}
                >
                  {t.actions.closeRfq}
                </Button>
                <Button
                  className="min-h-8 px-3 py-1.5 text-xs bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => {
                    setCancelReason("");
                    setShowCancelModal(true);
                  }}
                >
                  {t.actions.cancelRfq}
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      {/* 2. Optimistic Concurrency Conflict Alert */}
      {staleConflict && (
        <Card className="border-amber-500 bg-amber-50 dark:bg-amber-950/20">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="space-y-1 text-sm">
              <p className="font-semibold text-amber-800 dark:text-amber-300">
                {t.conflicts.staleTitle}
              </p>
              <p className="text-amber-700 dark:text-amber-400">
                {t.conflicts.staleDescription}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Action Error / Success alerts */}
      {actionError && (
        <Card className="border-destructive bg-destructive/10">
          <CardContent className="flex items-center gap-2 p-3 text-sm text-destructive">
            <XCircle className="h-4 w-4 shrink-0" />
            <span>{actionError}</span>
          </CardContent>
        </Card>
      )}
      {actionSuccess && (
        <Card className="border-green-500 bg-green-50 dark:bg-green-950/20">
          <CardContent className="flex items-center gap-2 p-3 text-sm text-green-700 dark:text-green-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>{actionSuccess}</span>
          </CardContent>
        </Card>
      )}

      {/* 3. Navigation Tabs */}
      <div className="flex border-b border-border overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Package className="h-4 w-4" />
          {t.tabs.overview}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("participants")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "participants"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Users className="h-4 w-4" />
          {t.tabs.participants}
          {canManage && invitations.length > 0 && (
            <Badge variant="secondary" className="ml-1 text-xs px-1.5 py-0.5">
              {invitations.length}
            </Badge>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("activity")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "activity"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <History className="h-4 w-4" />
          {t.tabs.activity}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("offers")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "offers"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Tag className="h-4 w-4" />
          {t.tabs.offers}
        </button>

        {canAccessComparison && (
          <button
            type="button"
            onClick={() => setActiveTab("comparison")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === "comparison"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Scale className="h-4 w-4" />
            {t.tabs.comparison}
          </button>
        )}

        <button
          type="button"
          onClick={() => setActiveTab("negotiation")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "negotiation"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <MessageSquare className="h-4 w-4" />
          {t.tabs.negotiation}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("documents")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
            activeTab === "documents"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <FileText className="h-4 w-4" />
          {t.tabs.documents}
        </button>

        {canAccessMatching && (
          <button
            type="button"
            onClick={() => setActiveTab("matches")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
              activeTab === "matches"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Sparkles className="h-4 w-4" />
            {t.tabs.matches}
          </button>
        )}
      </div>

      {/* 4. Tab Contents */}

      {/* --- OVERVIEW TAB --- */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left/Main Column: Specs & Terms */}
          <div className="space-y-6 lg:col-span-2">
            {/* Dynamic Commodity Specifications */}
            <Card>
              <CardHeader className="border-b pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base font-semibold flex items-center gap-2">
                    <Layers className="h-4 w-4 text-primary" />
                    {t.overview.technicalSpecsTitle}
                  </CardTitle>
                  <Badge variant="outline" className="text-xs">
                    v{rfq.schema_version_number}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="pt-4">
                {isLoadingSchema ? (
                  <div className="flex items-center justify-center p-6 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin mr-2" />
                    <span>{t.errors.loadSchemaFailed}</span>
                  </div>
                ) : schema ? (
                  <CommoditySpecificationView
                    schema={schema}
                    value={(rfq.specifications as Record<string, unknown>) || {}}
                    locale={locale}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">{t.overview.notSpecified}</p>
                )}
              </CardContent>
            </Card>

            {/* Commercial Terms */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Tag className="h-4 w-4 text-primary" />
                  {t.overview.commercialTermsTitle}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.quantity}</dt>
                    <dd className="text-sm font-semibold mt-1">
                      {Number(rfq.quantity).toLocaleString()} {rfq.unit}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.targetPrice}</dt>
                    <dd className="text-sm font-semibold mt-1">
                      {rfq.target_price
                        ? `${Number(rfq.target_price).toLocaleString()} ${rfq.currency}`
                        : t.overview.notSpecified}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.paymentTerms}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {rfq.payment_terms || t.overview.notSpecified}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.incoterm}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {rfq.incoterm || t.overview.notSpecified}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>

            {/* Delivery Terms */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Clock className="h-4 w-4 text-primary" />
                  {t.overview.deliveryTermsTitle}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.origin}</dt>
                    <dd className="text-sm font-medium mt-1">{rfq.origin || t.overview.notSpecified}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.destination}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {rfq.destination || t.overview.notSpecified}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.deliveryWindow}</dt>
                    <dd className="text-sm font-medium mt-1">
                      {rfq.delivery_window_start && rfq.delivery_window_end
                        ? `${rfq.delivery_window_start} تا ${rfq.delivery_window_end}`
                        : rfq.delivery_window_start || rfq.delivery_window_end || t.overview.notSpecified}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t.overview.submissionDeadline}
                    </dt>
                    <dd className="text-sm font-medium mt-1">
                      {rfq.submission_deadline
                        ? new Date(rfq.submission_deadline).toLocaleString(
                            locale === "fa" ? "fa-IR" : "en-US"
                          )
                        : t.overview.notSpecified}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </div>

          {/* Right/Side Column: Quality, Notes, Lifecycle */}
          <div className="space-y-6">
            {/* Quality & Inspection */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  {t.overview.qualityTitle}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 space-y-3">
                <div>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t.overview.inspectionRequired}
                  </dt>
                  <dd className="text-sm font-semibold mt-1">
                    {rfq.inspection_required ? t.overview.yes : t.overview.no}
                  </dd>
                </div>
                {rfq.quality_notes && (
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">{t.overview.qualityNotes}</dt>
                    <dd className="text-sm text-muted-foreground mt-1 whitespace-pre-wrap">
                      {rfq.quality_notes}
                    </dd>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* General Notes (Buyer only) */}
            {"notes" in rfq && rfq.notes && (
              <Card>
                <CardHeader className="border-b pb-3">
                  <CardTitle className="text-base font-semibold">{t.overview.notesTitle}</CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <p className="text-sm text-muted-foreground whitespace-pre-wrap">{rfq.notes}</p>
                </CardContent>
              </Card>
            )}

            {/* Lifecycle Timestamps & Provenance */}
            <Card>
              <CardHeader className="border-b pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <History className="h-4 w-4 text-primary" />
                  اطلاعات چرخه عمر
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4 space-y-2 text-xs text-muted-foreground">
                <div className="flex justify-between">
                  <span>تاریخ ایجاد:</span>
                  <span className="font-medium text-foreground">
                    {new Date(rfq.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                  </span>
                </div>
                {rfq.published_at && (
                  <div className="flex justify-between">
                    <span>{t.publishedAt}</span>
                    <span className="font-medium text-foreground">
                      {new Date(rfq.published_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                    </span>
                  </div>
                )}
                {"closed_at" in rfq && rfq.closed_at && (
                  <div className="flex justify-between">
                    <span>{t.closedAt}</span>
                    <span className="font-medium text-foreground">
                      {new Date(rfq.closed_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                    </span>
                  </div>
                )}
                {"cancelled_at" in rfq && rfq.cancelled_at && (
                  <div className="space-y-1">
                    <div className="flex justify-between">
                      <span>{t.cancelledAt}</span>
                      <span className="font-medium text-destructive">
                        {new Date(rfq.cancelled_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                      </span>
                    </div>
                    {rfq.cancellation_reason && (
                      <p className="text-xs text-destructive/80 mt-1">
                        {t.cancellationReason} {rfq.cancellation_reason}
                      </p>
                    )}
                  </div>
                )}
                {"updated_at" in rfq && rfq.updated_at && (
                  <div className="flex justify-between border-t pt-2 mt-2">
                    <span>{t.lastUpdated}</span>
                    <span className="font-medium">
                      {new Date(rfq.updated_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* --- PARTICIPANTS TAB --- */}
      {activeTab === "participants" && (
        <div className="space-y-6">
          {/* Buyer Owner/Manager or Operator View: Participant Management */}
          {canManage ? (
            <Card>
              <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
                <div>
                  <CardTitle className="text-base font-semibold">{t.participants.title}</CardTitle>
                  <CardDescription className="text-xs mt-1">
                    {t.participants.subtitle}
                  </CardDescription>
                </div>
                {rfq.status !== "closed" && rfq.status !== "cancelled" && (
                  <Button
                    className="min-h-8 px-3 py-1.5 text-xs"
                    onClick={() => setShowInviteModal(true)}
                  >
                    <Users className="h-4 w-4 mr-2 rtl:ml-2 rtl:mr-0" />
                    {t.participants.inviteMore}
                  </Button>
                )}
              </CardHeader>
              <CardContent className="pt-4">
                {isLoadingInvitations ? (
                  <div className="flex items-center justify-center p-8 text-muted-foreground">
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  </div>
                ) : invitations.length === 0 ? (
                  <div className="p-8 text-center text-sm text-muted-foreground">
                    {t.participants.noParticipants}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t.participants.table.organization}</TableHead>
                        <TableHead>{t.participants.table.capabilities}</TableHead>
                        <TableHead>{t.participants.table.status}</TableHead>
                        <TableHead>{t.participants.table.invitedAt}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {invitations.map((inv) => (
                        <TableRow key={inv.id}>
                          <TableCell className="font-medium">
                            {inv.organization.name}
                            {inv.organization.verification_status === "verified" && (
                              <Badge variant="outline" className="ml-2 text-xs text-green-600 border-green-200">
                                معتبر
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex gap-1">
                              {(inv.organization.capabilities || []).map((cap) => (
                                <Badge key={cap} variant="secondary" className="text-xs">
                                  {t.participants.roles[cap as keyof typeof t.participants.roles] || cap}
                                </Badge>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                inv.status === "declined"
                                  ? "destructive"
                                  : inv.status === "viewed" || inv.status === "responded"
                                  ? "default"
                                  : "secondary"
                              }
                            >
                              {t.participants.statusLabels[inv.status as keyof typeof t.participants.statusLabels] ||
                                inv.status}
                            </Badge>
                            {inv.decline_reason && (
                              <p className="text-xs text-muted-foreground mt-1">
                                {inv.decline_reason}
                              </p>
                            )}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {new Date(inv.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-US")}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          ) : (
            /* External Participant Context: Own status only, never competitor list */
            <Card>
              <CardHeader className="border-b pb-4">
                <CardTitle className="text-base font-semibold">
                  {t.participants.ownStatusTitle}
                </CardTitle>
                <CardDescription className="text-xs mt-1">
                  {t.participants.ownStatusDesc}
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-6">
                {ownInvitation ? (
                  <div className="space-y-4 max-w-md">
                    <div className="flex items-center justify-between border-b pb-3">
                      <span className="text-sm font-medium text-muted-foreground">
                        {t.participants.table.status}:
                      </span>
                      <Badge
                        variant={
                          ownInvitation.status === "declined"
                            ? "destructive"
                            : ownInvitation.status === "viewed" || ownInvitation.status === "responded"
                            ? "default"
                            : "secondary"
                        }
                      >
                        {t.participants.statusLabels[
                          ownInvitation.status as keyof typeof t.participants.statusLabels
                        ] || ownInvitation.status}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between border-b pb-3 text-xs text-muted-foreground">
                      <span>{t.participants.table.invitedAt}:</span>
                      <span className="font-medium text-foreground">
                        {new Date(ownInvitation.created_at).toLocaleString(
                          locale === "fa" ? "fa-IR" : "en-US"
                        )}
                      </span>
                    </div>
                    {ownInvitation.status !== "declined" &&
                      ownInvitation.status !== "responded" &&
                      rfq.status === "published" && (
                        <div className="pt-2">
                          <Button
                            variant="outline"
                            className="min-h-8 px-3 py-1.5 text-xs text-destructive hover:bg-destructive/10"
                            onClick={() => setShowDeclineModal(true)}
                          >
                            {t.participants.declineAction}
                          </Button>
                        </div>
                      )}
                    {ownInvitation.status === "declined" && ownInvitation.decline_reason && (
                      <p className="text-xs text-muted-foreground">
                        {t.participants.declineReasonLabel}: {ownInvitation.decline_reason}
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t.participants.publicParticipationNote}
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* --- ACTIVITY TAB --- */}
      {activeTab === "activity" && (
        <Card>
          <CardHeader className="border-b pb-4">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">{t.activity.title}</CardTitle>
                <CardDescription className="text-xs mt-1">{t.activity.subtitle}</CardDescription>
              </div>
              <Button
                variant="outline"
                className="min-h-8 px-2 py-1 text-xs border-transparent hover:bg-muted"
                onClick={() => triggerRefresh()}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            {isLoadingActivity ? (
              <div className="flex items-center justify-center p-8 text-muted-foreground">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : activity.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                {t.activity.noActivity}
              </div>
            ) : (
              <div className="relative border-r border-border pr-4 space-y-6 rtl:border-r rtl:border-l-0 rtl:pr-4">
                {activity.map((item) => {
                  const eventTitle =
                    t.activity.events[item.event_type as keyof typeof t.activity.events] ||
                    item.event_type;
                  const actorLabel =
                    t.activity.actors[item.actor_type as keyof typeof t.activity.actors] ||
                    item.actor_type;

                  return (
                    <div key={item.id} className="relative flex flex-col gap-1">
                      <div className="absolute -right-[23px] top-1 h-3 w-3 rounded-full border-2 border-background bg-primary rtl:-right-[23px]" />
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{eventTitle}</span>
                        {item.organization_name && (
                          <span className="text-xs font-medium text-foreground">
                            ({item.organization_name})
                          </span>
                        )}
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {actorLabel}
                        </Badge>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {new Date(item.timestamp).toLocaleString(
                          locale === "fa" ? "fa-IR" : "en-US"
                        )}
                      </span>
                      {typeof item.details === "object" &&
                        item.details !== null &&
                        "reason" in item.details && (
                          <p className="text-xs text-muted-foreground mt-1 rounded bg-muted/40 p-2">
                            {String((item.details as Record<string, unknown>).reason)}
                          </p>
                        )}
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* --- OFFERS TAB (STAGED PLACEHOLDER) --- */}
      {activeTab === "offers" && (
        <Card className="border-dashed">
          <CardHeader className="text-center pb-2">
            <CardTitle className="text-base font-semibold">{t.staged.offersTitle}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <Tag className="h-10 w-10 text-muted-foreground/50 mb-3" />
            <p className="max-w-md text-sm leading-relaxed">{t.staged.offersPlaceholder}</p>
          </CardContent>
        </Card>
      )}

      {/* --- COMPARISON TAB --- */}
      {activeTab === "comparison" && canAccessComparison && (
        <RFQComparisonTab
          rfqId={rfqId}
          canManage={canManage}
          isOperator={Boolean(isOperatorOrAdmin)}
          locale={locale}
        />
      )}

      {/* --- NEGOTIATION TAB --- */}
      {activeTab === "negotiation" && (
        <RFQNegotiationTab
          rfqId={rfqId}
          canManage={canManage}
          isOperator={Boolean(isOperatorOrAdmin)}
          locale={locale}
        />
      )}

      {/* --- DOCUMENTS TAB (STAGED PLACEHOLDER) --- */}
      {activeTab === "documents" && (
        <Card className="border-dashed">
          <CardHeader className="text-center pb-2">
            <CardTitle className="text-base font-semibold">{t.staged.documentsTitle}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <FileText className="h-10 w-10 text-muted-foreground/50 mb-3" />
            <p className="max-w-md text-sm leading-relaxed">{t.staged.documentsPlaceholder}</p>
          </CardContent>
        </Card>
      )}

      {/* --- MATCHES TAB --- */}
      {activeTab === "matches" && (
        canAccessMatching ? (
          <RFQMatchingTab
            rfq={rfq}
            locale={locale}
            canManage={canManage}
            isOperatorOrAdmin={isOperatorOrAdmin}
            invitations={invitations}
            onInvitationCreated={triggerRefresh}
          />
        ) : (
          <Card className="border-destructive/40 bg-destructive/5">
            <CardContent className="p-8 text-center text-destructive">
              <AlertTriangle className="h-8 w-8 mx-auto mb-2 text-destructive" />
              <p className="font-bold">{t.unauthorizedTitle}</p>
              <p className="text-xs text-muted-foreground mt-1">{t.unauthorizedDescription}</p>
            </CardContent>
          </Card>
        )
      )}

      {/* --- MODAL: CLOSE RFQ CONFIRMATION --- */}
      {showCloseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <Card className="w-full max-w-md shadow-lg" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base font-semibold">{t.actions.confirmCloseTitle}</CardTitle>
              <CardDescription className="text-xs">{t.actions.confirmCloseDesc}</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                className="min-h-8 px-3 py-1.5 text-xs"
                onClick={() => setShowCloseModal(false)}
                disabled={isActionLoading}
              >
                {t.actions.dismiss}
              </Button>
              <Button
                className="min-h-8 px-3 py-1.5 text-xs"
                onClick={() => void handleCloseRfq()}
                disabled={isActionLoading}
              >
                {isActionLoading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2 rtl:ml-2 rtl:mr-0" />
                    {t.actions.closing}
                  </>
                ) : (
                  t.actions.confirm
                )}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* --- MODAL: CANCEL RFQ CONFIRMATION --- */}
      {showCancelModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <Card className="w-full max-w-md shadow-lg" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base font-semibold text-destructive">
                {t.actions.confirmCancelTitle}
              </CardTitle>
              <CardDescription className="text-xs">{t.actions.confirmCancelDesc}</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="cancel-reason" className="text-xs font-medium">
                  {t.actions.cancelReasonLabel}
                  {rfq.status === "published" && <span className="text-destructive ml-1">*</span>}
                </Label>
                <Textarea
                  id="cancel-reason"
                  placeholder={t.actions.cancelReasonPlaceholder}
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  className="min-h-[80px]"
                />
                {cancelReasonError && (
                  <p className="text-xs text-destructive">{cancelReasonError}</p>
                )}
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button
                  variant="outline"
                  className="min-h-8 px-3 py-1.5 text-xs"
                  onClick={() => setShowCancelModal(false)}
                  disabled={isActionLoading}
                >
                  {t.actions.dismiss}
                </Button>
                <Button
                  className="min-h-8 px-3 py-1.5 text-xs bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => void handleCancelRfq()}
                  disabled={isActionLoading}
                >
                  {isActionLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2 rtl:ml-2 rtl:mr-0" />
                      {t.actions.cancelling}
                    </>
                  ) : (
                    t.actions.confirm
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* --- MODAL: INVITE ORGANIZATION (BUYER) --- */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <Card className="w-full max-w-lg shadow-lg" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base font-semibold">
                {t.participants.inviteModalTitle}
              </CardTitle>
              <CardDescription className="text-xs">
                {t.participants.inviteModalDesc}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <Input
                placeholder={t.participants.searchPlaceholder}
                value={inviteSearch}
                onChange={(e) => setInviteSearch(e.target.value)}
                className="text-sm"
              />

              {inviteError && (
                <p className="text-xs text-destructive">{inviteError}</p>
              )}
              {inviteSuccess && (
                <p className="text-xs text-green-600">{inviteSuccess}</p>
              )}

              <div className="max-h-60 overflow-y-auto divide-y divide-border border rounded-md">
                {filteredDirectory.length === 0 ? (
                  <div className="p-4 text-center text-xs text-muted-foreground">
                    سازمانی یافت نشد.
                  </div>
                ) : (
                  filteredDirectory.map((org) => {
                    const isAlreadyInvited = invitations.some(
                      (inv) => inv.organization.id === org.id
                    );

                    return (
                      <div
                        key={org.id}
                        className="flex items-center justify-between p-3 text-sm hover:bg-muted/50"
                      >
                        <div className="space-y-0.5">
                          <p className="font-medium">{org.name}</p>
                          <div className="flex gap-1">
                            {org.capabilities.map((c) => (
                              <Badge key={c} variant="secondary" className="text-[10px]">
                                {t.participants.roles[c as keyof typeof t.participants.roles] || c}
                              </Badge>
                            ))}
                          </div>
                        </div>

                        {isAlreadyInvited ? (
                          <Badge variant="outline" className="text-xs text-muted-foreground">
                            {t.participants.alreadyInvited}
                          </Badge>
                        ) : (
                          <Button
                            className="min-h-8 px-3 py-1.5 text-xs"
                            disabled={isInvitingId === org.id}
                            onClick={() => void handleInviteOrganization(org.id)}
                          >
                            {isInvitingId === org.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Send className="h-3.5 w-3.5 mr-1 rtl:ml-1 rtl:mr-0" />
                            )}
                            ارسال دعوت
                          </Button>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              <div className="flex justify-end pt-2">
                <Button
                  variant="outline"
                  className="min-h-8 px-3 py-1.5 text-xs"
                  onClick={() => setShowInviteModal(false)}
                >
                  بستن
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* --- MODAL: DECLINE INVITATION (INVITEE) --- */}
      {showDeclineModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <Card className="w-full max-w-md shadow-lg" dir={isRtl ? "rtl" : "ltr"}>
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base font-semibold text-destructive">
                {t.participants.declineModalTitle}
              </CardTitle>
              <CardDescription className="text-xs">
                {t.participants.declineModalDesc}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="decline-reason" className="text-xs font-medium">
                  {t.participants.declineReasonLabel}
                </Label>
                <Textarea
                  id="decline-reason"
                  placeholder="علت رد دعوت را وارد کنید…"
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  className="min-h-[80px]"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button
                  variant="outline"
                  className="min-h-8 px-3 py-1.5 text-xs"
                  onClick={() => setShowDeclineModal(false)}
                  disabled={isDeclining}
                >
                  {t.actions.dismiss}
                </Button>
                <Button
                  className="min-h-8 px-3 py-1.5 text-xs bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => void handleDeclineInvitation()}
                  disabled={isDeclining}
                >
                  {isDeclining ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2 rtl:ml-2 rtl:mr-0" />
                      {t.participants.declining}
                    </>
                  ) : (
                    t.actions.confirm
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

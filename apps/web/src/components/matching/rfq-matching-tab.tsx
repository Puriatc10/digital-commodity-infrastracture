"use client";

import React, { useState, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { MatchingRunHeader } from "./matching-run-header";
import { MatchingLaneView } from "./matching-lane-view";
import { MatchingSignalExplanationDialog } from "./matching-signal-explanation-dialog";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertTriangle,
  CheckCircle2,
  Play,
  XCircle,
} from "lucide-react";
import {
  LoadingState,
  EmptyState,
  ErrorState,
  AccessDeniedState,
} from "@/components/states";

type RFQBuilderResponse = components["schemas"]["RFQBuilderResponse"];
type RFQPublicResponse = components["schemas"]["RFQPublicResponse"];
type MatchingRun = components["schemas"]["MatchingRunResponse"];
type MatchingCandidate = components["schemas"]["MatchingCandidateResponse"];
type AudienceEnum = components["schemas"]["AudienceEnum"];
type RFQInvitationResponse = components["schemas"]["RFQInvitationResponse"];

interface RFQMatchingTabProps {
  rfq: RFQBuilderResponse | RFQPublicResponse;
  locale?: EnabledLocale;
  canManage: boolean;
  isOperatorOrAdmin: boolean;
  invitations: RFQInvitationResponse[];
  onInvitationCreated?: () => void;
}

export function RFQMatchingTab({
  rfq,
  locale = "fa",
  canManage,
  isOperatorOrAdmin,
  invitations,
  onInvitationCreated,
}: RFQMatchingTabProps) {
  const messages = getMessages(locale);
  const t = messages.matching;
  const queryClient = useQueryClient();
  const { state: authState } = useAuth();

  const currentOrgId =
    authState.status === "authenticated"
      ? authState.currentOrganization?.organization.id
      : null;

  // In-flight race protection counter
  const requestVersionRef = useRef<number>(0);
  const prevOrgRef = useRef<string | null>(null);
  const prevRolesRef = useRef<string[]>([]);

  // State
  const [runs, setRuns] = useState<MatchingRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<MatchingRun | null>(null);
  const [candidates, setCandidates] = useState<MatchingCandidate[]>([]);
  const [operatorSelectedAudience, setOperatorSelectedAudience] = useState<AudienceEnum>("OPERATOR");

  // Audience guard: non-operator/admin can NEVER target or escalate to OPERATOR
  const targetAudience: AudienceEnum = isOperatorOrAdmin ? operatorSelectedAudience : "BUYER";
  const setTargetAudience = (aud: AudienceEnum) => {
    if (isOperatorOrAdmin) {
      setOperatorSelectedAudience(aud);
    }
  };

  // Loading & Error States
  const [isLoadingRuns, setIsLoadingRuns] = useState<boolean>(true);
  const [isLoadingCandidates, setIsLoadingCandidates] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [isInvitingId, setIsInvitingId] = useState<string | null>(null);
  const [unauthorizedStatus, setUnauthorizedStatus] = useState<401 | 403 | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState<number>(0);

  // Explanation Dialog State
  const [explanationCandidate, setExplanationCandidate] =
    useState<MatchingCandidate | null>(null);

  // Session & Persona Switch Isolation
  useEffect(() => {
    const roles = authState.status === "authenticated" ? authState.systemRoles : [];
    const rolesChanged =
      JSON.stringify([...prevRolesRef.current].sort()) !== JSON.stringify([...roles].sort());
    const orgChanged = prevOrgRef.current !== null && prevOrgRef.current !== currentOrgId;

    if (rolesChanged || orgChanged) {
      // Invalidate current in-flight requests immediately
      requestVersionRef.current += 1;

      // Clear all matching data from memory immediately
      setRuns([]);
      setSelectedRun(null);
      setCandidates([]);
      setExplanationCandidate(null);
      setActionError(null);
      setActionSuccess(null);
      setUnauthorizedStatus(null);
      setLoadError(null);

      // Remove queries from queryClient
      queryClient.removeQueries({ queryKey: ["matching-runs", rfq.id] });
      queryClient.removeQueries({ queryKey: ["matching-candidates"] });
    }

    prevOrgRef.current = currentOrgId ?? null;
    prevRolesRef.current = roles;
  }, [currentOrgId, authState, queryClient, rfq.id]);

  // 1. Fetch historical runs for RFQ
  useEffect(() => {
    let ignore = false;
    const version = ++requestVersionRef.current;

    async function loadRuns() {
      setIsLoadingRuns(true);
      setActionError(null);
      setUnauthorizedStatus(null);
      setLoadError(null);

      try {
        const { data, response } = await apiClient.GET("/api/matching/rfqs/{rfq_id}/runs/", {
          params: { path: { rfq_id: rfq.id } },
        });

        // Discard if session changed or newer request initiated
        if (ignore || version !== requestVersionRef.current) return;

        if (response.status === 401 || response.status === 403) {
          setUnauthorizedStatus(response.status as 401 | 403);
          setRuns([]);
          setSelectedRun(null);
          return;
        }

        if (response.ok && Array.isArray(data)) {
          // Enforce audience privacy strictly in client:
          // If not operator/admin, filter out any non-BUYER runs
          const safeRuns = isOperatorOrAdmin
            ? data
            : data.filter((r) => r.audience === "BUYER");

          setRuns(safeRuns);

          // Select the latest run by default if available
          if (safeRuns.length > 0) {
            setSelectedRun(safeRuns[0]);
          } else {
            setSelectedRun(null);
            setCandidates([]);
          }
        } else {
          setLoadError(
            response.status >= 500
              ? messages.states.error.serverError
              : messages.states.error.defaultDescription
          );
          setRuns([]);
          setSelectedRun(null);
        }
      } catch {
        if (!ignore && version === requestVersionRef.current) {
          setLoadError(messages.states.error.networkError);
          setRuns([]);
          setSelectedRun(null);
        }
      } finally {
        if (!ignore && version === requestVersionRef.current) {
          setIsLoadingRuns(false);
        }
      }
    }

    void loadRuns();
    return () => {
      ignore = true;
    };
  }, [rfq.id, isOperatorOrAdmin, messages.states.error, refreshIndex]);

  // 2. Fetch evaluated candidates for selected run
  useEffect(() => {
    if (!selectedRun) {
      return;
    }

    let ignore = false;
    const version = ++requestVersionRef.current;
    const runId = selectedRun.id;

    async function loadCandidates() {
      setIsLoadingCandidates(true);
      try {
        const { data, response } = await apiClient.GET("/api/matching/runs/{run_id}/candidates/", {
          params: { path: { run_id: runId } },
        });

        if (ignore || version !== requestVersionRef.current) return;

        if (response.ok && Array.isArray(data)) {
          // Strict Buyer privacy guard: Buyer can NEVER see SUPPLY_OPPORTUNITY
          const audienceSafeCandidates = isOperatorOrAdmin
            ? data
            : data.filter((c) => c.candidate_kind !== "SUPPLY_OPPORTUNITY");

          setCandidates(audienceSafeCandidates);
        } else {
          setCandidates([]);
        }
      } catch {
        if (!ignore && version === requestVersionRef.current) {
          setCandidates([]);
        }
      } finally {
        if (!ignore && version === requestVersionRef.current) {
          setIsLoadingCandidates(false);
        }
      }
    }

    void loadCandidates();
    return () => {
      ignore = true;
    };
  }, [selectedRun, isOperatorOrAdmin]);

  // 3. Trigger new matching run
  const handleGenerateRun = async (audience: AudienceEnum) => {
    // Non-operator is strictly locked to BUYER
    const safeAudience = isOperatorOrAdmin ? audience : "BUYER";

    setIsGenerating(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { data, response } = await apiClient.POST("/api/matching/rfqs/{rfq_id}/runs/", {
        params: { path: { rfq_id: rfq.id } },
        body: { audience: safeAudience },
      });

      if (response.status === 400) {
        const errData = data as { code?: string; detail?: unknown } | undefined;
        if (errData?.code === "rfq_not_matchable") {
          setActionError(t.states.rfqNotPublished);
        } else if (errData?.code === "no_published_policy") {
          setActionError(t.states.noPolicy);
        } else {
          setActionError(typeof errData?.detail === "string" ? errData.detail : t.states.error);
        }
        return;
      }

      if (response.status === 403) {
        setActionError(t.states.unauthorized);
        return;
      }

      if (response.status === 201 && data) {
        const newRun = data as MatchingRun;
        // Prepend new run to runs history
        setRuns((prev) => [newRun, ...prev]);
        setSelectedRun(newRun);
        setActionSuccess(t.actions.generate);
      } else {
        setActionError(t.states.error);
      }
    } catch {
      setActionError(t.states.error);
    } finally {
      setIsGenerating(false);
    }
  };

  // 4. Safe Domain Action: Invite to RFQ
  const handleInvite = async (organizationId: string) => {
    setIsInvitingId(organizationId);
    setActionError(null);
    setActionSuccess(null);

    try {
      const { response } = await apiClient.POST("/api/trade-hub/rfqs/{rfq_id}/invitations/", {
        params: { path: { rfq_id: rfq.id } },
        body: { organization_id: organizationId },
      });

      if (response.ok) {
        setActionSuccess(t.states.inviteSuccess);
        if (onInvitationCreated) {
          onInvitationCreated();
        }
      } else {
        setActionError(t.states.inviteError);
      }
    } catch {
      setActionError(t.states.inviteError);
    } finally {
      setIsInvitingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Tab Header & Description */}
      <div className="space-y-1">
        <h2 className="text-xl font-bold tracking-tight">
          {t.tabTitle}
        </h2>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {t.tabSubtitle}
        </p>
      </div>

      {/* Action Alerts */}
      {actionError && (
        <Card className="border-destructive bg-destructive/10">
          <CardContent className="flex items-center gap-2 p-3 text-xs text-destructive">
            <XCircle className="h-4 w-4 shrink-0" />
            <span>{actionError}</span>
          </CardContent>
        </Card>
      )}

      {actionSuccess && (
        <Card className="border-green-500 bg-green-50 dark:bg-green-950/20">
          <CardContent className="flex items-center gap-2 p-3 text-xs text-green-700 dark:text-green-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>{actionSuccess}</span>
          </CardContent>
        </Card>
      )}

      {/* Lifecycle Status Notice if Draft */}
      {rfq.status === "draft" && (
        <Card className="border-amber-400 bg-amber-50/70 dark:bg-amber-950/20">
          <CardContent className="flex items-center gap-3 p-4 text-xs text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
            <p className="leading-relaxed">
              {t.states.rfqNotPublished}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Run Header: Controls & Historical Selector */}
      <MatchingRunHeader
        runs={runs}
        selectedRun={selectedRun}
        onSelectRun={(run) => setSelectedRun(run)}
        onGenerateRun={handleGenerateRun}
        isGenerating={isGenerating}
        isOperatorOrAdmin={isOperatorOrAdmin}
        canManage={canManage && rfq.status === "published"}
        targetAudience={targetAudience}
        setTargetAudience={setTargetAudience}
        locale={locale}
      />

      {/* Main Content: Loading / Unauthorized / Error / Empty / Lanes */}
      {isLoadingRuns ? (
        <LoadingState variant="section" message={t.states.loadingRuns} locale={locale} />
      ) : unauthorizedStatus ? (
        <AccessDeniedState
          statusCode={unauthorizedStatus}
          description={t.states.unauthorized}
          locale={locale}
        />
      ) : loadError ? (
        <ErrorState
          errorMessage={loadError}
          onRetry={() => setRefreshIndex((k) => k + 1)}
          locale={locale}
        />
      ) : runs.length === 0 ? (
        <EmptyState
          icon={<Play className="h-6 w-6 text-primary" />}
          title={t.states.noRuns}
          description={t.states.noRunsPrompt}
          action={
            canManage && rfq.status === "published"
              ? {
                  label: t.actions.generate,
                  onClick: () => void handleGenerateRun(targetAudience),
                  disabled: isGenerating,
                  loading: isGenerating,
                }
              : undefined
          }
          locale={locale}
        />
      ) : isLoadingCandidates ? (
        <LoadingState variant="section" message={t.states.loadingCandidates} locale={locale} />
      ) : (
        /* Three Lanes Rendering */
        <MatchingLaneView
          candidates={candidates}
          locale={locale}
          canManage={canManage}
          isOperatorOrAdmin={isOperatorOrAdmin}
          invitations={invitations}
          onInvite={handleInvite}
          isInvitingId={isInvitingId}
          onExplain={(cand) => setExplanationCandidate(cand)}
        />
      )}

      {/* Explainability Dialog */}
      <MatchingSignalExplanationDialog
        candidate={explanationCandidate}
        onClose={() => setExplanationCandidate(null)}
        locale={locale}
      />
    </div>
  );
}

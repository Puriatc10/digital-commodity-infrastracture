"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  ArrowLeft,
  Building2,
  User,
  Handshake,
  Package,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Phone,
  MessageSquare,
  Mail,
  Users,
  StickyNote,
  Plus,
  ExternalLink,
  Ban,
  PauseCircle,
  PlayCircle,
  Check,
  X,
  FileCode,
} from "lucide-react";

import { apiClient as client } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { useAuth } from "@/lib/auth-context";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type OpportunityDetail = components["schemas"]["OpportunityDetail"];
type OpportunityContactAttemptDetail = components["schemas"]["OpportunityContactAttemptDetail"];
type OpportunityTaskDetail = components["schemas"]["OpportunityTaskDetail"];
type ContactAttemptType = components["schemas"]["ContactAttemptTypeEnum"];
type QualificationIssue = components["schemas"]["QualificationIssue"];

interface OpportunityDetailClientProps {
  locale: EnabledLocale;
  opportunityId: string;
}

export function OpportunityDetailClient({
  locale,
  opportunityId,
}: OpportunityDetailClientProps) {
  const messages = getMessages(locale);
  const oppMsg = messages.opportunities;
  const { state: authState } = useAuth();
  const queryClient = useQueryClient();

  const isOperatorOrAdmin =
    authState.status === "authenticated" &&
    authState.systemRoles.some((r) => r === "operator" || r === "admin");

  const currentUserId =
    authState.status === "authenticated" ? authState.user.id : null;
  const prevUserRef = useRef<number | null>(currentUserId);

  // Modal / Action states
  const [activeModal, setActiveModal] = useState<
    "none" | "contact_attempt" | "create_task" | "reason_action" | "convert_rfq" | "convert_supply"
  >("none");
  const [reasonActionType, setReasonActionType] = useState<"hold" | "reject" | "lost">("hold");
  const [actionReason, setActionReason] = useState<string>("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [conflictAlert, setConflictAlert] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // New Contact Attempt form state
  const [contactType, setContactType] = useState<ContactAttemptType>("CALL");
  const [contactNotes, setContactNotes] = useState<string>("");

  // New Task form state
  const [taskTitle, setTaskTitle] = useState<string>("");
  const [taskDueAt, setTaskDueAt] = useState<string>("");
  const [taskDescription, setTaskDescription] = useState<string>("");
  const [taskAssignToMe, setTaskAssignToMe] = useState<boolean>(true);

  // Conversion form state
  const [convertBuyerOrgId, setConvertBuyerOrgId] = useState<string>("");
  const [convertSupplierOrgId, setConvertSupplierOrgId] = useState<string>("");
  const [convertDestination, setConvertDestination] = useState<string>("");
  const [convertOrigin, setConvertOrigin] = useState<string>("");
  const [convertIncoterm, setConvertIncoterm] = useState<string>("FOB");
  const [convertVisibility, setConvertVisibility] = useState<"private" | "network" | "public">("private");
  const [convertNotes, setConvertNotes] = useState<string>("");

  // Qualification structured errors state
  const [qualificationErrors, setQualificationErrors] = useState<QualificationIssue[]>([]);

  // Session Cache Isolation
  useEffect(() => {
    if (prevUserRef.current !== currentUserId) {
      queryClient.removeQueries({ queryKey: ["opportunity", opportunityId] });
      queryClient.removeQueries({ queryKey: ["opportunity-contact-attempts", opportunityId] });
      queryClient.removeQueries({ queryKey: ["opportunity-tasks", opportunityId] });
      prevUserRef.current = currentUserId;
    }
  }, [currentUserId, opportunityId, queryClient]);

  // Fetch Opportunity Detail
  const {
    data: opp,
    isLoading: isOppLoading,
    isError: isOppError,
    refetch: refetchOpp,
    isFetching: isOppFetching,
  } = useQuery({
    queryKey: ["opportunity", opportunityId, currentUserId],
    queryFn: async () => {
      const resp = await client.GET("/api/opportunities/opportunities/{id}/", {
        params: { path: { id: opportunityId } },
      });
      if (!resp.response.ok || !resp.data) {
        throw new Error("Opportunity not found");
      }
      return resp.data as OpportunityDetail;
    },
    enabled: isOperatorOrAdmin,
  });

  // Fetch Contact Attempts
  const {
    data: contactAttempts = [],
    refetch: refetchContacts,
  } = useQuery({
    queryKey: ["opportunity-contact-attempts", opportunityId, currentUserId],
    queryFn: async () => {
      const resp = await client.GET(
        "/api/opportunities/opportunities/{opportunity_id}/contact-attempts/",
        {
          params: { path: { opportunity_id: opportunityId } },
        }
      );
      if (!resp.response.ok || !resp.data) {
        return [];
      }
      return resp.data as OpportunityContactAttemptDetail[];
    },
    enabled: isOperatorOrAdmin && Boolean(opp),
  });

  // Fetch Tasks
  const {
    data: tasks = [],
    refetch: refetchTasks,
  } = useQuery({
    queryKey: ["opportunity-tasks", opportunityId, currentUserId],
    queryFn: async () => {
      const resp = await client.GET(
        "/api/opportunities/opportunities/{opportunity_id}/tasks/",
        {
          params: { path: { opportunity_id: opportunityId } },
        }
      );
      if (!resp.response.ok || !resp.data) {
        return [];
      }
      return resp.data as OpportunityTaskDetail[];
    },
    enabled: isOperatorOrAdmin && Boolean(opp),
  });


  if (authState.status === "loading") {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="sr-only">{oppMsg.states.loadingDetail}</span>
      </div>
    );
  }

  if (!isOperatorOrAdmin) {
    return (
      <Card className="p-8 text-center">
        <div className="flex flex-col items-center gap-3">
          <ShieldAlert className="h-10 w-10 text-destructive" />
          <h2 className="text-lg font-semibold text-destructive">
            {messages.rfqBuilder.unauthorizedTitle}
          </h2>
          <p className="text-sm text-muted-foreground">
            {oppMsg.states.unauthorized}
          </p>
        </div>
      </Card>
    );
  }

  if (isOppLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="sr-only">{oppMsg.states.loadingDetail}</span>
      </div>
    );
  }

  if (isOppError || !opp) {
    return (
      <Card className="p-8 text-center">
        <div className="flex flex-col items-center gap-3">
          <AlertTriangle className="h-10 w-10 text-amber-500" />
          <h2 className="text-lg font-semibold">{oppMsg.states.notFound}</h2>
          <p className="text-sm text-muted-foreground">{oppMsg.states.loadError}</p>
          <Link href={`/${locale}/opportunities`}>
            <Button variant="outline" className="min-h-8 px-3 text-xs mt-2">
              {oppMsg.actions.backToList}
            </Button>
          </Link>
        </div>
      </Card>
    );
  }

  // 409 Conflict handler
  const handleConflict = async () => {
    setConflictAlert(true);
    setActionError(null);
    setActiveModal("none");
    await refetchOpp();
  };

  // Helper for lifecycle transitions
  const executeLifecycleAction = async (
    actionName: "contact" | "qualify" | "match" | "resume" | "expire"
  ) => {
    setIsSubmitting(true);
    setActionError(null);
    setActionSuccess(null);
    setQualificationErrors([]);

    try {
      let resp;
      if (actionName === "contact") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/contact/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version },
        });
      } else if (actionName === "qualify") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/qualify/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version },
        });
      } else if (actionName === "match") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/match/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version },
        });
      } else if (actionName === "resume") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/resume/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version },
        });
      } else {
        resp = await client.POST("/api/opportunities/opportunities/{id}/expire/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version, reason: "" },
        });
      }

      if (resp.response.status === 409) {
        await handleConflict();
        return;
      }

      if (!resp.response.ok) {
        // Check for structured qualification errors
        const errData = resp.error as {
          detail?: string;
          missing_requirements?: QualificationIssue[];
          invalid_requirements?: QualificationIssue[];
        } | undefined;

        if (errData?.missing_requirements || errData?.invalid_requirements) {
          const combined = [
            ...(errData.missing_requirements || []),
            ...(errData.invalid_requirements || []),
          ];
          setQualificationErrors(combined);
        }

        throw new Error(errData?.detail || oppMsg.states.actionError);
      }

      setActionSuccess(oppMsg.states.lifecycleSuccess);
      await refetchOpp();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.actionError);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper for reasoned actions (hold, reject, lost)
  const submitReasonAction = async () => {
    if (!actionReason.trim()) {
      setActionError("وارد کردن علت اقدام الزامی است.");
      return;
    }

    setIsSubmitting(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      let resp;
      if (reasonActionType === "hold") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/hold/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version, reason: actionReason.trim() },
        });
      } else if (reasonActionType === "reject") {
        resp = await client.POST("/api/opportunities/opportunities/{id}/reject/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version, reason: actionReason.trim() },
        });
      } else {
        resp = await client.POST("/api/opportunities/opportunities/{id}/lost/", {
          params: { path: { id: opp.id } },
          body: { expected_version: opp.version, reason: actionReason.trim() },
        });
      }

      if (resp.response.status === 409) {
        await handleConflict();
        return;
      }

      if (!resp.response.ok) {
        const errData = resp.error as { detail?: string } | undefined;
        throw new Error(errData?.detail || oppMsg.states.actionError);
      }

      setActionSuccess(oppMsg.states.lifecycleSuccess);
      setActiveModal("none");
      setActionReason("");
      await refetchOpp();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.actionError);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper for Contact Attempt creation
  const submitContactAttempt = async () => {
    if (!contactNotes.trim()) {
      setActionError("یادداشت تعامل الزامی است.");
      return;
    }

    setIsSubmitting(true);
    setActionError(null);

    try {
      const resp = await client.POST(
        "/api/opportunities/opportunities/{opportunity_id}/contact-attempts/",
        {
          params: { path: { opportunity_id: opp.id } },
          body: {
            type: contactType,
            occurred_at: new Date().toISOString(),
            notes: contactNotes.trim(),
          },
        }
      );

      if (!resp.response.ok) {
        const errData = resp.error as { detail?: string } | undefined;
        throw new Error(errData?.detail || oppMsg.states.contactError);
      }

      setActionSuccess(oppMsg.states.attemptRecorded);
      setActiveModal("none");
      setContactNotes("");
      await refetchContacts();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.contactError);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper for Task creation
  const submitTask = async () => {
    if (!taskTitle.trim() || !taskDueAt) {
      setActionError("عنوان و مهلت انجام وظیفه الزامی است.");
      return;
    }

    setIsSubmitting(true);
    setActionError(null);

    try {
      const resp = await client.POST(
        "/api/opportunities/opportunities/{opportunity_id}/tasks/",
        {
          params: { path: { opportunity_id: opp.id } },
          body: {
            title: taskTitle.trim(),
            due_at: new Date(taskDueAt).toISOString(),
            description: taskDescription.trim(),
            assigned_to: taskAssignToMe && currentUserId ? currentUserId : null,
          },
        }
      );

      if (!resp.response.ok) {
        const errData = resp.error as { detail?: string } | undefined;
        throw new Error(errData?.detail || oppMsg.states.taskError);
      }

      setActionSuccess(oppMsg.states.taskCreated);
      setActiveModal("none");
      setTaskTitle("");
      setTaskDueAt("");
      setTaskDescription("");
      await refetchTasks();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.taskError);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Complete / Cancel task actions
  const executeTaskAction = async (taskId: string, action: "complete" | "cancel") => {
    setActionError(null);
    try {
      let resp;
      if (action === "complete") {
        resp = await client.POST(
          "/api/opportunities/opportunities/{opportunity_id}/tasks/{task_id}/complete/",
          {
            params: { path: { opportunity_id: opp.id, task_id: taskId } },
          }
        );
      } else {
        resp = await client.POST(
          "/api/opportunities/opportunities/{opportunity_id}/tasks/{task_id}/cancel/",
          {
            params: { path: { opportunity_id: opp.id, task_id: taskId } },
          }
        );
      }

      if (!resp.response.ok) {
        throw new Error(oppMsg.states.taskError);
      }

      setActionSuccess(
        action === "complete"
          ? oppMsg.states.taskCompleted
          : oppMsg.states.taskCancelled
      );
      await refetchTasks();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.taskError);
    }
  };

  // Helper for Demand -> RFQ Conversion
  const submitConvertToRfq = async () => {
    setIsSubmitting(true);
    setActionError(null);

    try {
      const resp = await client.POST(
        "/api/opportunities/opportunities/{id}/convert-to-rfq/",
        {
          params: { path: { id: opp.id } },
          body: {
            expected_version: opp.version,
            destination: convertDestination.trim(),
            origin: convertOrigin.trim(),
            incoterm: convertIncoterm.trim(),
            visibility: convertVisibility,
            notes: convertNotes.trim(),
            ...(convertBuyerOrgId.trim() ? { buyer_organization_id: convertBuyerOrgId.trim() } : {}),
          },
        }
      );

      if (resp.response.status === 409) {
        await handleConflict();
        return;
      }

      if (!resp.response.ok) {
        const errData = resp.error as { detail?: string } | undefined;
        throw new Error(errData?.detail || oppMsg.states.conversionError);
      }

      setActionSuccess(oppMsg.states.conversionSuccess);
      setActiveModal("none");
      await refetchOpp();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.conversionError);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper for Supply -> Supply Listing Conversion
  const submitConvertToSupply = async () => {
    setIsSubmitting(true);
    setActionError(null);

    try {
      const resp = await client.POST(
        "/api/opportunities/opportunities/{id}/convert-to-supply-listing/",
        {
          params: { path: { id: opp.id } },
          body: {
            expected_version: opp.version,
            origin: convertOrigin.trim(),
            destination: convertDestination.trim(),
            incoterm: convertIncoterm.trim(),
            quality_notes: "",
            visibility: convertVisibility,
            notes: convertNotes.trim(),
            ...(convertSupplierOrgId.trim() ? { supplier_organization_id: convertSupplierOrgId.trim() } : {}),
          },
        }
      );

      if (resp.response.status === 409) {
        await handleConflict();
        return;
      }

      if (!resp.response.ok) {
        const errData = resp.error as { detail?: string } | undefined;
        throw new Error(errData?.detail || oppMsg.states.supplyConversionError);
      }

      setActionSuccess(oppMsg.states.conversionSuccess);
      setActiveModal("none");
      await refetchOpp();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : oppMsg.states.supplyConversionError);
    } finally {
      setIsSubmitting(false);
    }
  };

  const getContactTypeIcon = (type: string) => {
    switch (type) {
      case "CALL":
        return <Phone className="h-4 w-4 text-emerald-600" />;
      case "MESSAGE":
        return <MessageSquare className="h-4 w-4 text-sky-600" />;
      case "EMAIL":
        return <Mail className="h-4 w-4 text-blue-600" />;
      case "MEETING":
        return <Users className="h-4 w-4 text-purple-600" />;
      default:
        return <StickyNote className="h-4 w-4 text-amber-600" />;
    }
  };

  const counterpartyName = opp.organization
    ? opp.organization.name
    : opp.external_counterparty
    ? opp.external_counterparty.company_name
    : oppMsg.counterpartyType.unknown;

  const isExternal = Boolean(opp.external_counterparty);
  const isDemand = opp.direction.toLowerCase() === "demand";
  const isConverted = opp.status === "Converted";
  const isQualified = opp.status === "Qualified" || opp.status === "Matching" || opp.status === "Converted";
  const isHold = opp.status === "On Hold";
  const isTerminal = ["Converted", "Rejected", "Lost", "Expired"].includes(opp.status);

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Actions Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b pb-4">
        <div className="flex items-center gap-3">
          <Link href={`/${locale}/opportunities`}>
            <Button variant="outline" className="min-h-8 px-2.5 py-1 text-xs gap-1">
              <ArrowLeft className="h-3.5 w-3.5 rtl:rotate-180" />
              <span>{oppMsg.actions.backToList}</span>
            </Button>
          </Link>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold font-mono">
              <bdi dir="ltr">{opp.identifier || opp.id}</bdi>
            </h1>
            <Badge
              variant="outline"
              className={isDemand ? "border-blue-500 text-blue-600" : "border-emerald-500 text-emerald-600"}
            >
              {isDemand ? oppMsg.direction.Demand : oppMsg.direction.Supply}
            </Badge>
            <Badge variant="default" className="bg-primary">
              {oppMsg.status[opp.status as keyof typeof oppMsg.status] || opp.status}
            </Badge>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {oppMsg.fields.version}: <strong className="font-mono"><bdi dir="ltr">{opp.version}</bdi></strong>
          </span>
          <Button
            variant="outline"
            onClick={() => void refetchOpp()}
            disabled={isOppFetching}
            className="min-h-8 px-2.5 py-1 text-xs gap-1"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isOppFetching ? "animate-spin" : ""}`} />
            <span>{oppMsg.actions.refresh}</span>
          </Button>
        </div>
      </div>

      {/* 409 Conflict Alert */}
      {conflictAlert && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-sm">
                {oppMsg.concurrency.staleWarning}
              </h3>
              <p className="text-xs mt-1">
                {oppMsg.concurrency.conflictAlert}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Global Action Alerts */}
      {actionError && (
        <div className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-destructive text-sm flex items-center justify-between">
          <span>{actionError}</span>
          <Button
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => setActionError(null)}
          >
            {messages.notFound.back}
          </Button>
        </div>
      )}

      {actionSuccess && (
        <div className="rounded-md border border-emerald-500/20 bg-emerald-500/10 p-4 text-emerald-700 dark:text-emerald-300 text-sm flex items-center justify-between">
          <span>{actionSuccess}</span>
          <Button
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => setActionSuccess(null)}
          >
            {messages.notFound.back}
          </Button>
        </div>
      )}

      {/* Converted Destination Banner */}
      {isConverted && (
        <Card className="border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20">
          <CardContent className="p-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-blue-600" />
              <div>
                <h3 className="font-semibold text-sm text-blue-900 dark:text-blue-200">
                  {opp.converted_rfq_id
                    ? oppMsg.conversionStatus.convertedToRfq
                    : oppMsg.conversionStatus.convertedToSupply}
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  زمان تبدیل: {opp.converted_at ? new Date(opp.converted_at).toLocaleString("fa-IR") : "—"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {opp.converted_rfq_id && (
                <Link href={`/${locale}/trade-hub/rfqs/${opp.converted_rfq_id}`}>
                  <Button variant="default" className="min-h-8 px-3 text-xs gap-1.5 bg-blue-600 hover:bg-blue-700 text-white">
                    <span>{oppMsg.actions.viewRfq}</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              )}
              {opp.converted_supply_listing_id && (
                <Link href={`/${locale}/trade-hub/supply-listings/${opp.converted_supply_listing_id}`}>
                  <Button variant="default" className="min-h-8 px-3 text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white">
                    <span>{oppMsg.actions.viewSupplyListing}</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Lifecycle Actions Bar */}
      {!isTerminal && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">{oppMsg.sections.lifecycle}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2 pt-0">
            {/* Captured -> Contacted */}
            {opp.status === "Captured" && (
              <Button
                variant="outline"
                onClick={() => void executeLifecycleAction("contact")}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1"
              >
                <Phone className="h-3.5 w-3.5 text-sky-600" />
                <span>{oppMsg.actions.contact}</span>
              </Button>
            )}

            {/* Captured/Contacted -> Qualify */}
            {(opp.status === "Captured" || opp.status === "Contacted") && (
              <Button
                variant="default"
                onClick={() => void executeLifecycleAction("qualify")}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.qualify}</span>
              </Button>
            )}

            {/* Qualified -> Matching */}
            {opp.status === "Qualified" && (
              <Button
                variant="outline"
                onClick={() => void executeLifecycleAction("match")}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 border-purple-400 text-purple-700 hover:bg-purple-50"
              >
                <Users className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.match}</span>
              </Button>
            )}

            {/* Conversion Actions */}
            {isQualified && isDemand && !isConverted && (
              <Button
                variant="default"
                onClick={() => {
                  setActionError(null);
                  setConvertDestination(opp.geography || "");
                  setConvertOrigin(opp.geography || "");
                  setActiveModal("convert_rfq");
                }}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 bg-blue-600 hover:bg-blue-700 text-white"
              >
                <FileText className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.convertToRfq}</span>
              </Button>
            )}

            {isQualified && !isDemand && !isConverted && (
              <Button
                variant="default"
                onClick={() => {
                  setActionError(null);
                  setConvertDestination(opp.geography || "");
                  setConvertOrigin(opp.geography || "");
                  setActiveModal("convert_supply");
                }}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                <Package className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.convertToSupplyListing}</span>
              </Button>
            )}

            {/* Hold / Resume */}
            {isHold ? (
              <Button
                variant="outline"
                onClick={() => void executeLifecycleAction("resume")}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 text-emerald-600"
              >
                <PlayCircle className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.resume}</span>
              </Button>
            ) : (
              <Button
                variant="outline"
                onClick={() => {
                  setActionError(null);
                  setReasonActionType("hold");
                  setActiveModal("reason_action");
                }}
                disabled={isSubmitting}
                className="min-h-8 px-3 text-xs gap-1 text-amber-600"
              >
                <PauseCircle className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.hold}</span>
              </Button>
            )}

            {/* Reject */}
            <Button
              variant="outline"
              onClick={() => {
                setActionError(null);
                setReasonActionType("reject");
                setActiveModal("reason_action");
              }}
              disabled={isSubmitting}
              className="min-h-8 px-3 text-xs gap-1 text-destructive hover:bg-destructive/10"
            >
              <Ban className="h-3.5 w-3.5" />
              <span>{oppMsg.actions.reject}</span>
            </Button>

            {/* Mark Lost */}
            <Button
              variant="outline"
              onClick={() => {
                setActionError(null);
                setReasonActionType("lost");
                setActiveModal("reason_action");
              }}
              disabled={isSubmitting}
              className="min-h-8 px-3 text-xs gap-1 text-destructive hover:bg-destructive/10"
            >
              <X className="h-3.5 w-3.5" />
              <span>{oppMsg.actions.markLost}</span>
            </Button>

            {/* Expire */}
            <Button
              variant="outline"
              onClick={() => void executeLifecycleAction("expire")}
              disabled={isSubmitting}
              className="min-h-8 px-3 text-xs gap-1 text-muted-foreground"
            >
              <Clock className="h-3.5 w-3.5" />
              <span>{oppMsg.actions.expire}</span>
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Main Grid: Overview & Counterparty */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Left 2 Cols: Commercial Details & Qualification */}
        <div className="md:col-span-2 space-y-6">
          {/* Overview Card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold">{oppMsg.sections.overview}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.commodity}</span>
                  <p className="font-semibold">{opp.commodity.name_fa || opp.commodity.code}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.quantity}</span>
                  <p className="font-semibold">{opp.quantity ? `${opp.quantity} ${opp.unit}` : "—"}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.indicativePrice}</span>
                  <p className="font-semibold">
                    {opp.indicative_price ? `${opp.indicative_price} ${opp.currency}` : "—"}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.deliveryWindow}</span>
                  <p className="font-medium text-xs">
                    {opp.delivery_window_start || "—"} تا {opp.delivery_window_end || "—"}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.paymentTerms}</span>
                  <p className="font-medium text-xs">{opp.payment_terms || "—"}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.geography}</span>
                  <p className="font-medium text-xs">{opp.geography || "—"}</p>
                </div>
              </div>

              {opp.notes && (
                <div className="border-t pt-3">
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.notes}</span>
                  <p className="text-sm mt-1 whitespace-pre-wrap">{opp.notes}</p>
                </div>
              )}

              {/* Dynamic Specifications */}
              {typeof opp.specifications === "object" &&
                opp.specifications !== null &&
                !Array.isArray(opp.specifications) &&
                Object.keys(opp.specifications).length > 0 && (
                <div className="border-t pt-3">
                  <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1 mb-2">
                    <FileCode className="h-3.5 w-3.5" />
                    <span>{oppMsg.fields.specifications}</span>
                  </span>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 bg-muted/40 p-3 rounded-md text-xs font-mono">
                    {Object.entries(opp.specifications as Record<string, unknown>).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-muted-foreground">{k}: </span>
                        <span className="font-semibold">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Status Reasons (Hold / Rejection / Lost) */}
              {(opp.hold_reason || opp.rejection_reason || opp.lost_reason) && (
                <div className="rounded-md bg-muted p-3 text-xs space-y-1">
                  {opp.hold_reason && (
                    <p><strong className="text-amber-600">علت تعلیق:</strong> {opp.hold_reason}</p>
                  )}
                  {opp.rejection_reason && (
                    <p><strong className="text-destructive">علت رد:</strong> {opp.rejection_reason}</p>
                  )}
                  {opp.lost_reason && (
                    <p><strong className="text-destructive">علت از دست رفتن:</strong> {opp.lost_reason}</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Qualification Readiness Section */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                <span>{oppMsg.sections.qualification}</span>
              </CardTitle>
              {opp.can_qualify ? (
                <Badge variant="default" className="bg-emerald-600 text-white">
                  {oppMsg.qualificationStatus.ready}
                </Badge>
              ) : isQualified ? (
                <Badge variant="default" className="bg-emerald-600 text-white">
                  {oppMsg.qualificationStatus.qualifiedSuccess}
                </Badge>
              ) : (
                <Badge variant="outline" className="border-amber-500 text-amber-600">
                  {oppMsg.qualificationStatus.notReady}
                </Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-3 pt-0">
              {opp.qualified_at && (
                <p className="text-xs text-muted-foreground">
                  تاریخ احراز صلاحیت: {new Date(opp.qualified_at).toLocaleString("fa-IR")}
                </p>
              )}

              {/* Qualification Issues if blocking */}
              {((opp.qualification_issues && opp.qualification_issues.length > 0) ||
                qualificationErrors.length > 0) && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:bg-amber-950/20 dark:border-amber-800">
                  <p className="text-xs font-semibold text-amber-900 dark:text-amber-200 mb-2">
                    {oppMsg.qualificationStatus.missingRequirements}
                  </p>
                  <ul className="list-disc list-inside space-y-1 text-xs text-amber-800 dark:text-amber-300">
                    {(qualificationErrors.length > 0 ? qualificationErrors : opp.qualification_issues || []).map(
                      (issue, idx) => (
                        <li key={idx}>
                          <span className="font-mono font-bold">{issue.field}:</span> {issue.message}
                        </li>
                      )
                    )}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Contact Attempts Timeline (T0606) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Phone className="h-4 w-4 text-primary" />
                <span>{oppMsg.sections.contacts}</span>
              </CardTitle>
              <Button
                variant="outline"
                onClick={() => {
                  setActionError(null);
                  setActiveModal("contact_attempt");
                }}
                className="min-h-8 px-2.5 py-1 text-xs gap-1"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.addContact}</span>
              </Button>
            </CardHeader>
            <CardContent className="pt-0">
              {contactAttempts.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">
                  {oppMsg.states.emptyContacts}
                </p>
              ) : (
                <div className="space-y-3">
                  {contactAttempts.map((attempt) => {
                    const typeLabel =
                      oppMsg.contactType[attempt.type as keyof typeof oppMsg.contactType] || attempt.type;

                    return (
                      <div
                        key={attempt.id}
                        className="rounded-md border p-3 text-xs flex flex-col gap-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {getContactTypeIcon(attempt.type)}
                            <span className="font-bold">{typeLabel}</span>
                          </div>
                          <span className="text-muted-foreground text-[11px]">
                            {new Date(attempt.occurred_at).toLocaleString("fa-IR")}
                          </span>
                        </div>
                        <p className="text-sm text-foreground whitespace-pre-wrap">
                          {attempt.notes}
                        </p>
                        {attempt.recorded_by_email && (
                          <span className="text-[10px] text-muted-foreground">
                            ثبت شده توسط: <bdi dir="ltr">{attempt.recorded_by_email}</bdi>
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Follow-up Tasks List (T0607) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Clock className="h-4 w-4 text-primary" />
                <span>{oppMsg.sections.followUps}</span>
              </CardTitle>
              <Button
                variant="outline"
                onClick={() => {
                  setActionError(null);
                  setActiveModal("create_task");
                }}
                className="min-h-8 px-2.5 py-1 text-xs gap-1"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>{oppMsg.actions.createTask}</span>
              </Button>
            </CardHeader>
            <CardContent className="pt-0">
              {tasks.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">
                  {oppMsg.states.emptyTasks}
                </p>
              ) : (
                <div className="space-y-3">
                  {tasks.map((task) => {
                    const isOpen = task.status === "OPEN";
                    const isCompleted = task.status === "COMPLETED";

                    return (
                      <div
                        key={task.id}
                        className="rounded-md border p-3 text-xs flex flex-col gap-2"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm">{task.title}</span>
                            {task.is_overdue && isOpen && (
                              <Badge variant="destructive" className="text-[10px] py-0">
                                {oppMsg.states.overdue}
                              </Badge>
                            )}
                            <Badge
                              variant={isCompleted ? "default" : isOpen ? "outline" : "secondary"}
                              className="text-[10px] py-0"
                            >
                              {oppMsg.taskStatus[task.status] || task.status}
                            </Badge>
                          </div>
                          <span className="text-muted-foreground text-[11px]">
                            سررسید: {new Date(task.due_at).toLocaleString("fa-IR")}
                          </span>
                        </div>

                        {task.description && (
                          <p className="text-muted-foreground whitespace-pre-wrap">
                            {task.description}
                          </p>
                        )}

                        <div className="flex items-center justify-between border-t pt-2 mt-1">
                          <span className="text-[10px] text-muted-foreground">
                            مسئول: {task.assigned_to_email ? <bdi dir="ltr">{task.assigned_to_email}</bdi> : "بدون انتساب"}
                          </span>
                          {isOpen && (
                            <div className="flex items-center gap-2">
                              <Button
                                variant="outline"
                                onClick={() => void executeTaskAction(task.id, "complete")}
                                className="min-h-6 px-2 py-0.5 text-[11px] gap-1 text-emerald-600 hover:bg-emerald-50"
                              >
                                <Check className="h-3 w-3" />
                                <span>{oppMsg.actions.completeTask}</span>
                              </Button>
                              <Button
                                variant="outline"
                                onClick={() => void executeTaskAction(task.id, "cancel")}
                                className="min-h-6 px-2 py-0.5 text-[11px] gap-1 text-destructive hover:bg-destructive/10"
                              >
                                <X className="h-3 w-3" />
                                <span>{oppMsg.actions.cancelTask}</span>
                              </Button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right 1 Col: Counterparty & Attribution Cards */}
        <div className="space-y-6">
          {/* Counterparty Card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                {isExternal ? (
                  <User className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <Building2 className="h-4 w-4 text-primary" />
                )}
                <span>{oppMsg.sections.counterparty}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm pt-0">
              <div>
                <span className="text-xs text-muted-foreground">نام طرف تجاری:</span>
                <p className="font-bold text-base">{counterpartyName}</p>
              </div>

              <div>
                <span className="text-xs text-muted-foreground">نوع هویت:</span>
                <p className="text-xs font-medium">
                  {isExternal
                    ? oppMsg.counterpartyType.external_counterparty
                    : oppMsg.counterpartyType.organization}
                </p>
              </div>

              {opp.organization && (
                <div className="space-y-1 border-t pt-2 text-xs">
                  <p><strong>کشور:</strong> {opp.organization.country || "—"}</p>
                </div>
              )}

              {opp.external_counterparty && (
                <div className="space-y-1.5 border-t pt-2 text-xs">
                  <p><strong>مسئول تماس:</strong> {opp.external_counterparty.contact_name || "—"}</p>
                  <p><strong>موقعیت:</strong> {opp.external_counterparty.geography || "—"}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Source & Attribution Card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2">
                <Handshake className="h-4 w-4 text-primary" />
                <span>{oppMsg.sections.sourceAttribution}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm pt-0">
              <div>
                <span className="text-xs text-muted-foreground">{oppMsg.fields.source}:</span>
                <p className="font-semibold text-sm">
                  {oppMsg.source[opp.source as keyof typeof oppMsg.source] || opp.source}
                </p>
              </div>

              {opp.broker && (
                <div className="border-t pt-2 space-y-1">
                  <span className="text-xs text-muted-foreground">{oppMsg.fields.broker}:</span>
                  <p className="font-bold text-sm text-primary">{opp.broker.name}</p>
                  <p className="text-[11px] text-muted-foreground">{opp.broker.country}</p>
                </div>
              )}

              <div className="border-t pt-2 text-xs space-y-1 text-muted-foreground">
                <p>
                  <strong>{oppMsg.fields.createdAt}:</strong>{" "}
                  {new Date(opp.created_at).toLocaleString("fa-IR")}
                </p>
                <p>
                  <strong>{oppMsg.fields.updatedAt}:</strong>{" "}
                  {new Date(opp.updated_at).toLocaleString("fa-IR")}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* Modals & Dialogs                                                          */}
      {/* ========================================================================= */}

      {/* 1. Reason Action Modal (Hold / Reject / Lost) */}
      {activeModal === "reason_action" && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md bg-background shadow-xl">
            <CardHeader>
              <CardTitle className="text-base font-bold">
                {reasonActionType === "hold"
                  ? oppMsg.actions.hold
                  : reasonActionType === "reject"
                  ? oppMsg.actions.reject
                  : oppMsg.actions.markLost}
              </CardTitle>
              <CardDescription className="text-xs">
                {oppMsg.modals.reasonLabel}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                placeholder={oppMsg.modals.reasonPlaceholder}
                value={actionReason}
                onChange={(e) => setActionReason(e.target.value)}
                className="text-xs min-h-[100px]"
              />
              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    setActiveModal("none");
                    setActionReason("");
                  }}
                  className="min-h-8 px-3 text-xs"
                >
                  {oppMsg.modals.cancel}
                </Button>
                <Button
                  variant="default"
                  onClick={() => void submitReasonAction()}
                  disabled={isSubmitting || !actionReason.trim()}
                  className="min-h-8 px-3 text-xs bg-primary"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    oppMsg.modals.submit
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 2. Contact Attempt Modal */}
      {activeModal === "contact_attempt" && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md bg-background shadow-xl">
            <CardHeader>
              <CardTitle className="text-base font-bold">{oppMsg.modals.contactTitle}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.contactTypeLabel}</Label>
                <Select
                  value={contactType}
                  onValueChange={(val) => setContactType(val as ContactAttemptType)}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="CALL">{oppMsg.contactType.CALL}</SelectItem>
                    <SelectItem value="MESSAGE">{oppMsg.contactType.MESSAGE}</SelectItem>
                    <SelectItem value="EMAIL">{oppMsg.contactType.EMAIL}</SelectItem>
                    <SelectItem value="MEETING">{oppMsg.contactType.MEETING}</SelectItem>
                    <SelectItem value="NOTE">{oppMsg.contactType.NOTE}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.contactNotesLabel}</Label>
                <Textarea
                  placeholder="خلاصه مذاکره یا یادداشت تعامل را وارد کنید…"
                  value={contactNotes}
                  onChange={(e) => setContactNotes(e.target.value)}
                  className="text-xs min-h-[100px]"
                />
              </div>

              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    setActiveModal("none");
                    setContactNotes("");
                  }}
                  className="min-h-8 px-3 text-xs"
                >
                  {oppMsg.modals.cancel}
                </Button>
                <Button
                  variant="default"
                  onClick={() => void submitContactAttempt()}
                  disabled={isSubmitting || !contactNotes.trim()}
                  className="min-h-8 px-3 text-xs bg-primary"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    oppMsg.modals.submit
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 3. Follow-up Task Modal */}
      {activeModal === "create_task" && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md bg-background shadow-xl">
            <CardHeader>
              <CardTitle className="text-base font-bold">{oppMsg.modals.taskTitle}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.taskTitleLabel}</Label>
                <Input
                  placeholder="پیگیری اسناد، تماس با نماینده و..."
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.taskDueLabel}</Label>
                <Input
                  type="datetime-local"
                  value={taskDueAt}
                  onChange={(e) => setTaskDueAt(e.target.value)}
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.taskDescLabel}</Label>
                <Textarea
                  placeholder="جزئیات و دستورالعمل پیگیری..."
                  value={taskDescription}
                  onChange={(e) => setTaskDescription(e.target.value)}
                  className="text-xs min-h-[70px]"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="taskAssignMe"
                  checked={taskAssignToMe}
                  onChange={(e) => setTaskAssignToMe(e.target.checked)}
                  className="rounded border-border"
                />
                <Label htmlFor="taskAssignMe" className="text-xs cursor-pointer">
                  {oppMsg.modals.taskAssignMe}
                </Label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    setActiveModal("none");
                    setTaskTitle("");
                    setTaskDueAt("");
                    setTaskDescription("");
                  }}
                  className="min-h-8 px-3 text-xs"
                >
                  {oppMsg.modals.cancel}
                </Button>
                <Button
                  variant="default"
                  onClick={() => void submitTask()}
                  disabled={isSubmitting || !taskTitle.trim() || !taskDueAt}
                  className="min-h-8 px-3 text-xs bg-primary"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    oppMsg.modals.submit
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 4. Convert to RFQ Modal (T0609) */}
      {activeModal === "convert_rfq" && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-lg bg-background shadow-xl">
            <CardHeader>
              <CardTitle className="text-base font-bold">{oppMsg.modals.convertRfqTitle}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isExternal && (
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold text-amber-700 dark:text-amber-300">
                    {oppMsg.modals.buyerOrgLabel} *
                  </Label>
                  <Input
                    placeholder={oppMsg.modals.buyerUuidPlaceholder}
                    value={convertBuyerOrgId}
                    onChange={(e) => setConvertBuyerOrgId(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">{oppMsg.modals.destinationLabel}</Label>
                  <Input
                    value={convertDestination}
                    onChange={(e) => setConvertDestination(e.target.value)}
                    className="h-8 text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs">{oppMsg.modals.incotermLabel}</Label>
                  <Input
                    value={convertIncoterm}
                    onChange={(e) => setConvertIncoterm(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.visibilityLabel}</Label>
                <Select
                  value={convertVisibility}
                  onValueChange={(val) => setConvertVisibility(val as "private" | "network" | "public")}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="private">خصوصی (دعوتی)</SelectItem>
                    <SelectItem value="network">شبکه سازمان‌ها</SelectItem>
                    <SelectItem value="public">عمومی</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.fields.notes}</Label>
                <Textarea
                  placeholder="یادداشت‌های تکمیلی خرید..."
                  value={convertNotes}
                  onChange={(e) => setConvertNotes(e.target.value)}
                  className="text-xs min-h-[60px]"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => setActiveModal("none")}
                  className="min-h-8 px-3 text-xs"
                >
                  {oppMsg.modals.cancel}
                </Button>
                <Button
                  variant="default"
                  onClick={() => void submitConvertToRfq()}
                  disabled={isSubmitting || (isExternal && !convertBuyerOrgId.trim())}
                  className="min-h-8 px-3 text-xs bg-blue-600 hover:bg-blue-700 text-white"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    oppMsg.modals.submit
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* 5. Convert to Supply Listing Modal (T0610) */}
      {activeModal === "convert_supply" && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-lg bg-background shadow-xl">
            <CardHeader>
              <CardTitle className="text-base font-bold">{oppMsg.modals.convertSupplyTitle}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isExternal && (
                <div className="space-y-1.5">
                  <Label className="text-xs font-semibold text-amber-700 dark:text-amber-300">
                    {oppMsg.modals.supplierOrgLabel} *
                  </Label>
                  <Input
                    placeholder={oppMsg.modals.supplierUuidPlaceholder}
                    value={convertSupplierOrgId}
                    onChange={(e) => setConvertSupplierOrgId(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">{oppMsg.modals.originLabel}</Label>
                  <Input
                    value={convertOrigin}
                    onChange={(e) => setConvertOrigin(e.target.value)}
                    className="h-8 text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs">{oppMsg.modals.incotermLabel}</Label>
                  <Input
                    value={convertIncoterm}
                    onChange={(e) => setConvertIncoterm(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.modals.visibilityLabel}</Label>
                <Select
                  value={convertVisibility}
                  onValueChange={(val) => setConvertVisibility(val as "private" | "network" | "public")}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="public">عمومی</SelectItem>
                    <SelectItem value="network">شبکه سازمان‌ها</SelectItem>
                    <SelectItem value="private">خصوصی</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">{oppMsg.fields.notes}</Label>
                <Textarea
                  placeholder="یادداشت‌های تکمیلی آگهی عرضه..."
                  value={convertNotes}
                  onChange={(e) => setConvertNotes(e.target.value)}
                  className="text-xs min-h-[60px]"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => setActiveModal("none")}
                  className="min-h-8 px-3 text-xs"
                >
                  {oppMsg.modals.cancel}
                </Button>
                <Button
                  variant="default"
                  onClick={() => void submitConvertToSupply()}
                  disabled={isSubmitting || (isExternal && !convertSupplierOrgId.trim())}
                  className="min-h-8 px-3 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    oppMsg.modals.submit
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

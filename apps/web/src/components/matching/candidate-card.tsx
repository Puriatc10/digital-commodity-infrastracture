"use client";

import React from "react";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Info,
  ExternalLink,
  UserPlus,
  Check,
  ShieldCheck,
  MapPin,
  Calendar,
  Package,
  AlertCircle,
  Loader2,
} from "lucide-react";

type MatchingCandidate = components["schemas"]["MatchingCandidateResponse"];
type RFQInvitationResponse = components["schemas"]["RFQInvitationResponse"];

interface CandidateCardProps {
  candidate: MatchingCandidate;
  locale?: EnabledLocale;
  canManage?: boolean;
  isOperatorOrAdmin?: boolean;
  invitations?: RFQInvitationResponse[];
  onInvite?: (organizationId: string) => Promise<void>;
  isInviting?: boolean;
  onExplain: (candidate: MatchingCandidate) => void;
}

export function CandidateCard({
  candidate,
  locale = "fa",
  canManage = false,
  isOperatorOrAdmin = false,
  invitations = [],
  onInvite,
  isInviting = false,
  onExplain,
}: CandidateCardProps) {
  const router = useRouter();
  const messages = getMessages(locale);
  const t = messages.matching;

  const source = (candidate.source || {}) as Record<string, unknown>;
  const orgName = (source.organization_name as string) || (source.counterparty_name as string) || "";
  const orgId = source.organization_id as string | undefined;
  const listingId = source.listing_id as string | undefined;
  const oppId = source.opportunity_id as string | undefined;
  const verStatus = (source.verification_status as string) || "unverified";
  const quantity = source.quantity as string | number | undefined;
  const unit = source.unit as string | undefined;
  const originArea = (source.origin_area_code as string) || "";
  const operatingAreas = (source.operating_areas as string[]) || [];
  const windowStart = source.availability_window_start as string | undefined;
  const windowEnd = source.availability_window_end as string | undefined;

  // Check if organization is already invited
  const isAlreadyInvited = Boolean(
    orgId && invitations.some((inv) => inv.organization?.id === orgId)
  );

  const getVerificationBadge = (status: string) => {
    switch (status) {
      case "verified":
        return (
          <Badge className="bg-green-100 text-green-800 border-green-200 dark:bg-green-950/40 dark:text-green-300 gap-1 text-[11px]">
            <ShieldCheck className="h-3 w-3 text-green-600 dark:text-green-400" />
            {t.verification.verified}
          </Badge>
        );
      case "basic_verified":
        return (
          <Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 gap-1 text-[11px]">
            <ShieldCheck className="h-3 w-3 text-emerald-600" />
            {t.verification.basic_verified}
          </Badge>
        );
      case "under_review":
        return (
          <Badge variant="outline" className="border-amber-300 text-amber-700 bg-amber-50 gap-1 text-[11px]">
            {t.verification.under_review}
          </Badge>
        );
      case "documents_submitted":
        return (
          <Badge variant="outline" className="text-[11px]">
            {t.verification.documents_submitted}
          </Badge>
        );
      case "suspended":
        return (
          <Badge variant="destructive" className="text-[11px]">
            {t.verification.suspended}
          </Badge>
        );
      case "unverified":
      default:
        return (
          <Badge variant="secondary" className="text-muted-foreground text-[11px]">
            {t.verification.unverified}
          </Badge>
        );
    }
  };

  const getCandidateKindBadge = (kind: string) => {
    switch (kind) {
      case "SUPPLY_LISTING":
        return (
          <Badge variant="outline" className="text-[11px] font-normal">
            {t.candidateKinds.SUPPLY_LISTING}
          </Badge>
        );
      case "SUPPLY_OPPORTUNITY":
        return (
          <Badge variant="secondary" className="text-[11px] font-normal bg-purple-100 text-purple-800 dark:bg-purple-950/40 dark:text-purple-300">
            {t.candidateKinds.SUPPLY_OPPORTUNITY}
          </Badge>
        );
      case "SUPPLIER_ORGANIZATION":
        return (
          <Badge variant="outline" className="text-[11px] font-normal">
            {t.candidateKinds.SUPPLIER_ORGANIZATION}
          </Badge>
        );
      case "BROKER_ORGANIZATION":
        return (
          <Badge variant="outline" className="text-[11px] font-normal">
            {t.candidateKinds.BROKER_ORGANIZATION}
          </Badge>
        );
      default:
        return null;
    }
  };

  const isLimitedCoverage =
    candidate.lane === "DIRECT_SUPPLY" &&
    candidate.evidence_coverage !== null &&
    candidate.evidence_coverage !== undefined &&
    Number(candidate.evidence_coverage) < 50;

  return (
    <Card className="flex flex-col justify-between overflow-hidden border hover:shadow-md transition-shadow">
      <div>
        {/* Card Header: Rank & Source Identity */}
        <CardHeader className="p-4 pb-3 border-b bg-muted/20 flex flex-row items-start justify-between gap-2">
          <div className="flex items-start gap-2.5">
            {candidate.rank !== null && candidate.rank !== undefined && (
              <div className="flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary font-bold text-xs shrink-0">
                #{candidate.rank}
              </div>
            )}
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <h4 className="font-bold text-sm leading-snug">
                  {orgName || t.geography.notSpecified}
                </h4>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {getCandidateKindBadge(candidate.candidate_kind)}
                {getVerificationBadge(verStatus)}
              </div>
            </div>
          </div>

          {candidate.eligible === false && (
            <Badge variant="destructive" className="text-[10px] shrink-0">
              {t.candidateCard.ineligibleBadge}
            </Badge>
          )}
        </CardHeader>

        {/* Lane-Specific Warnings & Disclaimers */}
        {candidate.lane === "POTENTIAL_SUPPLIER" && (
          <div className="bg-amber-50 dark:bg-amber-950/20 border-b border-amber-200 px-4 py-2 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600" />
            <p className="leading-relaxed">{t.lanes.POTENTIAL_SUPPLIER.disclaimer}</p>
          </div>
        )}

        {candidate.lane === "BROKER_PATH" && (
          <div className="bg-blue-50 dark:bg-blue-950/20 border-b border-blue-200 px-4 py-2 flex items-start gap-2 text-xs text-blue-800 dark:text-blue-300">
            <Info className="h-4 w-4 shrink-0 mt-0.5 text-blue-600" />
            <p className="leading-relaxed">{t.lanes.BROKER_PATH.disclaimer}</p>
          </div>
        )}

        {/* Card Body: Scores & Facts */}
        <CardContent className="p-4 space-y-4 text-xs">
          {/* Scores Section */}
          <div className="rounded-lg bg-muted/30 p-3 border grid grid-cols-2 gap-2 sm:grid-cols-3">
            {candidate.lane === "BROKER_PATH" ? (
              <div className="col-span-full">
                <span className="text-[11px] text-muted-foreground block mb-0.5">
                  {t.scores.brokerRelevance}
                </span>
                <span className="text-base font-bold text-foreground">
                  {candidate.ranking_score ? `${Number(candidate.ranking_score).toFixed(2)}${t.scores.percent}` : "-"}
                </span>
              </div>
            ) : (
              <>
                <div>
                  <span className="text-[11px] text-muted-foreground block mb-0.5">
                    {t.scores.fitScore}
                  </span>
                  <span className="text-sm font-bold text-foreground">
                    {candidate.fit_score ? `${Number(candidate.fit_score).toFixed(2)}${t.scores.percent}` : "-"}
                  </span>
                </div>

                <div>
                  <div className="flex items-center gap-1 mb-0.5">
                    <span className="text-[11px] text-muted-foreground">
                      {t.scores.coverage}
                    </span>
                    {isLimitedCoverage && (
                      <Badge variant="outline" className="text-[9px] px-1 py-0 border-amber-400 text-amber-700 bg-amber-50">
                        {t.scores.limitedEvidence}
                      </Badge>
                    )}
                  </div>
                  <span className={`text-sm font-bold ${isLimitedCoverage ? "text-amber-700 dark:text-amber-400" : "text-foreground"}`}>
                    {candidate.evidence_coverage ? `${Number(candidate.evidence_coverage).toFixed(2)}${t.scores.percent}` : "-"}
                  </span>
                </div>

                <div>
                  <span className="text-[11px] text-muted-foreground block mb-0.5">
                    {t.scores.rankingScore}
                  </span>
                  <span className="text-sm font-bold text-primary">
                    {candidate.ranking_score ? `${Number(candidate.ranking_score).toFixed(2)}${t.scores.percent}` : "-"}
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Operational Facts */}
          <div className="space-y-2">
            {/* Quantity (Direct Supply only if available) */}
            {candidate.lane === "DIRECT_SUPPLY" && quantity !== undefined && quantity !== null && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Package className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                <span>{t.candidateCard.quantity}</span>
                <span className="font-semibold text-foreground">
                  {quantity} {unit || ""}
                </span>
              </div>
            )}

            {/* Availability Window (Direct Supply only if available) */}
            {candidate.lane === "DIRECT_SUPPLY" && (windowStart || windowEnd) && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                <span>{t.candidateCard.availabilityWindow}</span>
                <span className="font-semibold text-foreground font-mono text-[11px]">
                  {windowStart || "?"} تا {windowEnd || "?"}
                </span>
              </div>
            )}

            {/* Geography / Origin Location */}
            {originArea && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                <span>{t.geography.origin}</span>
                <span className="font-medium text-foreground font-mono text-[11px]">
                  {originArea}
                </span>
              </div>
            )}

            {/* Operating Coverage (Potential Supplier / Broker) */}
            {operatingAreas.length > 0 && (
              <div className="flex items-start gap-2 text-muted-foreground">
                <MapPin className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground/70" />
                <div className="flex flex-col gap-1">
                  <span>{t.geography.operatingCoverage}</span>
                  <div className="flex flex-wrap gap-1">
                    {operatingAreas.map((area, idx) => (
                      <Badge key={idx} variant="secondary" className="font-mono text-[10px] px-1.5 py-0">
                        {area}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </div>

      {/* Card Actions Footer */}
      <div className="border-t p-3 bg-muted/10 flex flex-wrap items-center justify-between gap-2">
        {/* Why this match? */}
        <Button
          variant="outline"
          onClick={() => onExplain(candidate)}
          className="text-xs min-h-8 px-2.5 py-1 gap-1.5"
        >
          <Info className="h-3.5 w-3.5 text-primary" />
          {t.actions.whyMatch}
        </Button>

        <div className="flex items-center gap-1.5">
          {/* Domain Action: View Listing */}
          {candidate.candidate_kind === "SUPPLY_LISTING" && listingId && (
            <Button
              variant="outline"
              onClick={() => router.push(`/${locale}/trade-hub/supply-listings/${listingId}`)}
              className="text-xs min-h-8 px-2.5 py-1 gap-1"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t.actions.viewListing}
            </Button>
          )}

          {/* Domain Action: View Organization Profile */}
          {(candidate.candidate_kind === "SUPPLIER_ORGANIZATION" ||
            candidate.candidate_kind === "BROKER_ORGANIZATION") &&
            orgId && (
              <Button
                variant="outline"
                onClick={() => router.push(`/${locale}/directory/${orgId}`)}
                className="text-xs min-h-8 px-2.5 py-1 gap-1"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {t.actions.viewOrg}
              </Button>
            )}

          {/* Domain Action: Open Supply Opportunity (Operator only) */}
          {candidate.candidate_kind === "SUPPLY_OPPORTUNITY" && oppId && isOperatorOrAdmin && (
            <Button
              variant="outline"
              onClick={() => router.push(`/${locale}/opportunities/${oppId}`)}
              className="text-xs min-h-8 px-2.5 py-1 gap-1 text-purple-700 hover:text-purple-800"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t.actions.openOpportunity}
            </Button>
          )}

          {/* Domain Action: Invite to RFQ */}
          {canManage && orgId && (
            isAlreadyInvited ? (
              <Button
                variant="outline"
                disabled
                className="text-xs min-h-8 px-2.5 py-1 gap-1 text-green-700 bg-green-50 border-green-200"
              >
                <Check className="h-3.5 w-3.5" />
                {t.actions.alreadyInvited}
              </Button>
            ) : (
              <Button
                variant="default"
                disabled={isInviting}
                onClick={() => onInvite && void onInvite(orgId)}
                className="text-xs min-h-8 px-2.5 py-1 gap-1"
              >
                {isInviting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <UserPlus className="h-3.5 w-3.5" />
                )}
                {candidate.lane === "BROKER_PATH" ? t.actions.inviteBroker : t.actions.inviteSupplier}
              </Button>
            )
          )}
        </div>
      </div>
    </Card>
  );
}

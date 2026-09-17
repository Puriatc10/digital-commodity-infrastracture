"use client";

import React from "react";
import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { CandidateCard } from "./candidate-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Truck, Users, Network } from "lucide-react";

type MatchingCandidate = components["schemas"]["MatchingCandidateResponse"];
type CandidateLane = components["schemas"]["LaneEnum"];
type RFQInvitationResponse = components["schemas"]["RFQInvitationResponse"];

interface MatchingLaneViewProps {
  candidates: MatchingCandidate[];
  locale?: EnabledLocale;
  canManage?: boolean;
  isOperatorOrAdmin?: boolean;
  invitations?: RFQInvitationResponse[];
  onInvite?: (organizationId: string) => Promise<void>;
  isInvitingId?: string | null;
  onExplain: (candidate: MatchingCandidate) => void;
}

export function MatchingLaneView({
  candidates,
  locale = "fa",
  canManage = false,
  isOperatorOrAdmin = false,
  invitations = [],
  onInvite,
  isInvitingId = null,
  onExplain,
}: MatchingLaneViewProps) {
  const messages = getMessages(locale);
  const t = messages.matching;

  // Separate candidates strictly into 3 lanes preserving authoritative backend rank order
  const directSupplyCandidates = candidates.filter((c) => c.lane === "DIRECT_SUPPLY");
  const potentialSupplierCandidates = candidates.filter((c) => c.lane === "POTENTIAL_SUPPLIER");
  const brokerPathCandidates = candidates.filter((c) => c.lane === "BROKER_PATH");

  const lanes: {
    key: CandidateLane;
    title: string;
    subtitle: string;
    icon: React.ReactNode;
    items: MatchingCandidate[];
    badgeClass: string;
  }[] = [
    {
      key: "DIRECT_SUPPLY",
      title: t.lanes.DIRECT_SUPPLY.title,
      subtitle: t.lanes.DIRECT_SUPPLY.subtitle,
      icon: <Truck className="h-4 w-4 text-emerald-600" />,
      items: directSupplyCandidates,
      badgeClass: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
    },
    {
      key: "POTENTIAL_SUPPLIER",
      title: t.lanes.POTENTIAL_SUPPLIER.title,
      subtitle: t.lanes.POTENTIAL_SUPPLIER.subtitle,
      icon: <Users className="h-4 w-4 text-amber-600" />,
      items: potentialSupplierCandidates,
      badgeClass: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
    },
    {
      key: "BROKER_PATH",
      title: t.lanes.BROKER_PATH.title,
      subtitle: t.lanes.BROKER_PATH.subtitle,
      icon: <Network className="h-4 w-4 text-blue-600" />,
      items: brokerPathCandidates,
      badgeClass: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-300",
    },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
      {lanes.map((lane) => (
        <div key={lane.key} className="flex flex-col gap-4">
          {/* Lane Header */}
          <Card className="border-t-4 border-t-primary/70 shadow-sm">
            <CardHeader className="p-4 pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {lane.icon}
                  <CardTitle className="text-base font-bold">
                    {lane.title}
                  </CardTitle>
                </div>
                <Badge variant="secondary" className={`font-mono text-xs px-2 py-0.5 ${lane.badgeClass}`}>
                  {lane.items.length}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mt-1">
                {lane.subtitle}
              </p>
            </CardHeader>
          </Card>

          {/* Lane Candidates List */}
          <div className="flex flex-col gap-3">
            {lane.items.length === 0 ? (
              <Card className="border-dashed bg-muted/20">
                <CardContent className="p-6 text-center text-xs text-muted-foreground">
                  {t.states.noCandidatesInLane}
                </CardContent>
              </Card>
            ) : (
              lane.items.map((candidate) => {
                const orgId = (candidate.source as Record<string, unknown>)?.organization_id as string | undefined;
                const isInviting = Boolean(orgId && isInvitingId === orgId);

                return (
                  <CandidateCard
                    key={candidate.id}
                    candidate={candidate}
                    locale={locale}
                    canManage={canManage}
                    isOperatorOrAdmin={isOperatorOrAdmin}
                    invitations={invitations}
                    onInvite={onInvite}
                    isInviting={isInviting}
                    onExplain={onExplain}
                  />
                );
              })
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

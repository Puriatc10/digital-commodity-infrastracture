import type { components } from "@/lib/api/generated/schema";
import {
  diffOfferVersions,
  type CommoditySchemaVersion,
  type OfferVersionDiffResult,
  type OfferVersionHistory,
} from "./diff-utility";

export type RevisionRequestHistory = components["schemas"]["RevisionRequestHistory"];

export type TimelineItem =
  | {
      type: "version";
      id: string;
      version: OfferVersionHistory;
      isInitial: boolean;
      isLatestSubmitted: boolean;
      diffAgainstBase: OfferVersionDiffResult | null;
    }
  | {
      type: "revision_request";
      id: string;
      request: RevisionRequestHistory;
      baseVersionNumber: number;
      resolvedVersionNumber: number | null;
      isTerminal: boolean;
      isOpen: boolean;
    }
  | {
      type: "draft";
      id: string;
      draftVersion: OfferVersionHistory;
      diffAgainstBase: OfferVersionDiffResult | null;
    };

/**
 * Builds an explicit, canonical negotiation timeline from structured backend responses.
 *
 * Invariants:
 * - Relies on explicit base_offer_version_id and resolved_by_version_id foreign keys,
 *   never solely on timestamp ordering.
 * - Handles arbitrary N-cycle negotiations (V1 -> R1 -> V2 -> R2 -> V3...).
 * - Accurately models terminal requests (DECLINED, CANCELLED) and pending OPEN requests.
 * - Isolates in-progress DRAFT versions from immutable submitted history.
 */
export function buildNegotiationTimeline(
  versions: OfferVersionHistory[],
  revisionRequests: RevisionRequestHistory[],
  schema: CommoditySchemaVersion | null,
  locale: "fa" | "en" = "fa"
): TimelineItem[] {
  const items: TimelineItem[] = [];

  // 1. Separate submitted versions and draft
  const submittedVersions = versions
    .filter((v) => v.status?.toUpperCase() === "SUBMITTED")
    .sort((a, b) => a.version_number - b.version_number);

  const draftVersion = versions.find((v) => v.status?.toUpperCase() === "DRAFT") || null;

  const versionById = new Map<string, OfferVersionHistory>();
  for (const v of submittedVersions) {
    versionById.set(v.id, v);
  }

  // 2. Index revision requests by base_offer_version_id
  const requestsByBaseId = new Map<string, RevisionRequestHistory[]>();
  // Also index resolving requests by resolved_by_version_id
  const requestByResolvedId = new Map<string, RevisionRequestHistory>();

  const sortedRequests = [...revisionRequests].sort(
    (a, b) => new Date(a.requested_at).getTime() - new Date(b.requested_at).getTime()
  );

  for (const req of sortedRequests) {
    const list = requestsByBaseId.get(req.base_offer_version_id) || [];
    list.push(req);
    requestsByBaseId.set(req.base_offer_version_id, list);

    if (req.resolved_by_version_id) {
      requestByResolvedId.set(req.resolved_by_version_id, req);
    }
  }

  // 3. Emit timeline items sequentially
  const latestSubmittedId =
    submittedVersions.length > 0
      ? submittedVersions[submittedVersions.length - 1].id
      : null;

  for (let i = 0; i < submittedVersions.length; i++) {
    const v = submittedVersions[i];
    const isInitial = i === 0;
    const isLatestSubmitted = v.id === latestSubmittedId;

    let diffAgainstBase: OfferVersionDiffResult | null = null;
    if (!isInitial) {
      // Find the explicit resolving request for this version
      const resolvingReq = requestByResolvedId.get(v.id);
      const baseVersion = resolvingReq
        ? versionById.get(resolvingReq.base_offer_version_id) || submittedVersions[i - 1]
        : submittedVersions[i - 1];

      diffAgainstBase = diffOfferVersions(
        baseVersion,
        v,
        schema,
        Array.isArray(resolvingReq?.requested_fields)
          ? (resolvingReq.requested_fields as string[])
          : [],
        locale
      );
    }

    items.push({
      type: "version",
      id: v.id,
      version: v,
      isInitial,
      isLatestSubmitted,
      diffAgainstBase,
    });

    // Add all revision requests issued against this version
    const reqsOnThisVersion = requestsByBaseId.get(v.id) || [];
    for (const req of reqsOnThisVersion) {
      items.push({
        type: "revision_request",
        id: req.id,
        request: req,
        baseVersionNumber: req.base_version_number,
        resolvedVersionNumber: req.resolved_version_number ?? null,
        isTerminal: req.status === "DECLINED" || req.status === "CANCELLED",
        isOpen: req.status === "OPEN",
      });
    }
  }

  // 4. If an active unsubmitted DRAFT exists, attach it at the end
  if (draftVersion && submittedVersions.length > 0) {
    const baseVersion = submittedVersions[submittedVersions.length - 1];
    const openReq = sortedRequests.find((r) => r.status === "OPEN");

    const diffAgainstBase = diffOfferVersions(
      baseVersion,
      draftVersion,
      schema,
      Array.isArray(openReq?.requested_fields)
        ? (openReq.requested_fields as string[])
        : [],
      locale
    );

    items.push({
      type: "draft",
      id: draftVersion.id,
      draftVersion,
      diffAgainstBase,
    });
  }

  return items;
}

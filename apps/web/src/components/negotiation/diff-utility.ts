import type { components } from "@/lib/api/generated/schema";
import { getMessages } from "@/i18n/messages";
import { isEnabledLocale } from "@/i18n/config";
import { commodityMessages } from "@/i18n/commodity-messages";

export type OfferVersionHistory = components["schemas"]["OfferVersionHistory"];
export type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
export type CommodityAttributeDefinition = components["schemas"]["CommodityAttributeDefinition"];
export type OfferCostComponentResponse = components["schemas"]["OfferCostComponentResponse"];

export type DiffType = "added" | "removed" | "changed" | "unchanged";
export type DiffGroup =
  | "commercial"
  | "delivery"
  | "logistics"
  | "specification"
  | "cost_components";

export interface FieldDiff {
  fieldKey: string;
  label: string;
  group: DiffGroup;
  diffType: DiffType;
  oldValue: unknown;
  newValue: unknown;
  oldDisplay: string;
  newDisplay: string;
  isRequested?: boolean;
  sortOrder?: number;
}

export interface CostComponentDiff {
  key: string;
  kind: string;
  description: string;
  diffType: DiffType;
  oldAmount: string | null;
  newAmount: string | null;
  currency: string;
}

export interface OfferVersionDiffResult {
  baseVersionNumber: number;
  revisedVersionNumber: number;
  fields: FieldDiff[];
  hasChanges: boolean;
  changedCount: number;
  costComponents: CostComponentDiff[];
}

/**
 * Deep, order-independent JSON-safe equality checker.
 * Avoids naive JSON.stringify comparisons where key ordering or whitespace can drift.
 */
export function isCanonicalEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || a === undefined || b === undefined) {
    return a === b;
  }

  // Treat empty string and null/undefined as equivalent for commercial optional scalars
  if ((a === "" && b === null) || (a === null && b === "")) return true;

  if (typeof a !== typeof b) return false;

  if (typeof a === "object") {
    if (Array.isArray(a) !== Array.isArray(b)) return false;

    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) {
        if (!isCanonicalEqual(a[i], b[i])) return false;
      }
      return true;
    }

    const objA = a as Record<string, unknown>;
    const objB = b as Record<string, unknown>;
    const keysA = Object.keys(objA);
    const keysB = Object.keys(objB);

    if (keysA.length !== keysB.length) return false;
    for (const k of keysA) {
      if (!Object.prototype.hasOwnProperty.call(objB, k)) return false;
      if (!isCanonicalEqual(objA[k], objB[k])) return false;
    }
    return true;
  }

  return false;
}

function formatScalarDisplay(val: unknown, fallback = "—"): string {
  if (val === null || val === undefined || val === "") return fallback;
  return String(val);
}

function formatSpecDisplay(
  attr: CommodityAttributeDefinition,
  val: unknown,
  locale: "fa" | "en" = "fa"
): string {
  if (val === null || val === undefined || val === "") return "—";

  if (attr.data_type === "boolean") {
    const b = Boolean(val);
    const cm = commodityMessages[locale] || commodityMessages.fa;
    return b ? cm.yes : cm.no;
  }

  if (attr.data_type === "enum") {
    const enumMeta = attr.enum_metadata as
      | { options?: Array<{ value: string; label_fa?: string; label_en?: string }> }
      | Array<{ value: string; label_fa?: string; label_en?: string }>
      | undefined;
    const options = Array.isArray(enumMeta) ? enumMeta : enumMeta?.options;
    if (Array.isArray(options)) {
      const match = options.find((o) => o.value === val);
      if (match) {
        return locale === "fa" ? match.label_fa || match.value : match.label_en || match.value;
      }
    }
  }

  const unitMeta = attr.unit_metadata as { canonical_unit?: string } | undefined;
  const unit = unitMeta?.canonical_unit;
  if (unit) {
    return `${val} ${unit}`;
  }

  return String(val);
}

/**
 * Pure typed structured comparison between two OfferVersion snapshots.
 *
 * Invariants:
 * - Operates on exact stored scalar values and historical schema attributes.
 * - Zero commodity-specific branching.
 * - Does NOT conclude qualitative judgments (no "better price" or "worse terms").
 */
export function diffOfferVersions(
  base: OfferVersionHistory,
  revised: OfferVersionHistory,
  schema: CommoditySchemaVersion | null,
  requestedFields: string[] = [],
  locale: "fa" | "en" = "fa"
): OfferVersionDiffResult {
  const fields: FieldDiff[] = [];
  const requestedSet = new Set(requestedFields);
  const messages = isEnabledLocale(locale) ? getMessages(locale) : null;
  const diffFields = messages?.rfqWorkspace.negotiationHistory.diff.fields;

  const checkScalar = (
    key: string,
    labelFa: string,
    labelEn: string,
    group: DiffGroup,
    oldVal: unknown,
    newVal: unknown,
    formatVal?: (v: unknown) => string
  ) => {
    const equal = isCanonicalEqual(oldVal, newVal);
    const oldEmpty = oldVal === null || oldVal === undefined || oldVal === "";
    const newEmpty = newVal === null || newVal === undefined || newVal === "";

    let diffType: DiffType = "unchanged";
    if (!equal) {
      if (oldEmpty && !newEmpty) diffType = "added";
      else if (!oldEmpty && newEmpty) diffType = "removed";
      else diffType = "changed";
    }

    const formatter = formatVal || ((v: unknown) => formatScalarDisplay(v));
    const localizedLabel =
      (diffFields && key in diffFields ? (diffFields as Record<string, string>)[key] : null) ||
      (locale === "fa" ? labelFa : labelEn);

    fields.push({
      fieldKey: key,
      label: localizedLabel,
      group,
      diffType,
      oldValue: oldVal,
      newValue: newVal,
      oldDisplay: formatter(oldVal),
      newDisplay: formatter(newVal),
      isRequested: requestedSet.has(key),
    });
  };

  // 1. Commercial Scalars
  checkScalar(
    "unit_price",
    "قیمت واحد",
    "Unit Price",
    "commercial",
    base.unit_price,
    revised.unit_price,
    (v) => (v !== null && v !== undefined ? `${v} ${revised.currency || base.currency}` : "—")
  );

  checkScalar(
    "offered_quantity",
    "مقدار پیشنهادی",
    "Offered Quantity",
    "commercial",
    base.offered_quantity,
    revised.offered_quantity,
    (v) => (v !== null && v !== undefined ? `${v} ${revised.quantity_unit || base.quantity_unit}` : "—")
  );

  checkScalar(
    "currency",
    "ارز",
    "Currency",
    "commercial",
    base.currency,
    revised.currency
  );

  checkScalar(
    "quantity_unit",
    "واحد سنجش",
    "Quantity Unit",
    "commercial",
    base.quantity_unit,
    revised.quantity_unit
  );

  checkScalar(
    "payment_terms",
    "شرایط پرداخت",
    "Payment Terms",
    "commercial",
    base.payment_terms,
    revised.payment_terms
  );

  checkScalar(
    "valid_until",
    "مهلت اعتبار پیشنهاد",
    "Offer Validity",
    "commercial",
    base.valid_until,
    revised.valid_until
  );

  checkScalar(
    "notes",
    "یادداشت‌های تجاری",
    "Commercial Notes",
    "commercial",
    base.notes,
    revised.notes
  );

  // 2. Delivery & Incoterm
  checkScalar(
    "incoterm",
    "قاعده اینکوترمز",
    "Incoterm",
    "delivery",
    base.incoterm,
    revised.incoterm
  );

  checkScalar(
    "delivery_terms",
    "شرایط تحویل",
    "Delivery Terms",
    "delivery",
    base.delivery_terms,
    revised.delivery_terms
  );

  checkScalar(
    "delivery_start",
    "آغاز بازه تحویل",
    "Delivery Start",
    "delivery",
    base.delivery_start,
    revised.delivery_start
  );

  checkScalar(
    "delivery_end",
    "پایان بازه تحویل",
    "Delivery End",
    "delivery",
    base.delivery_end,
    revised.delivery_end
  );

  // 3. Logistics Costs
  checkScalar(
    "logistics_cost_status",
    "وضعیت هزینه لجستیک",
    "Logistics Cost Status",
    "logistics",
    base.logistics_cost_status,
    revised.logistics_cost_status
  );

  checkScalar(
    "logistics_cost_amount",
    "مبلغ هزینه لجستیک",
    "Logistics Cost Amount",
    "logistics",
    base.logistics_cost_amount,
    revised.logistics_cost_amount,
    (v) => (v !== null && v !== undefined ? `${v} ${revised.currency || base.currency}` : "—")
  );

  // 4. Dynamic Specifications (under Historical Schema)
  if (schema?.attributes && Array.isArray(schema.attributes)) {
    const sortedAttrs = [...schema.attributes].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.key.localeCompare(b.key)
    );

    const baseSpecs = (base.specifications || {}) as Record<string, unknown>;
    const revSpecs = (revised.specifications || {}) as Record<string, unknown>;

    for (const attr of sortedAttrs) {
      const oldVal = baseSpecs[attr.key];
      const newVal = revSpecs[attr.key];
      const equal = isCanonicalEqual(oldVal, newVal);

      const oldEmpty = oldVal === null || oldVal === undefined || oldVal === "";
      const newEmpty = newVal === null || newVal === undefined || newVal === "";

      let diffType: DiffType = "unchanged";
      if (!equal) {
        if (oldEmpty && !newEmpty) diffType = "added";
        else if (!oldEmpty && newEmpty) diffType = "removed";
        else diffType = "changed";
      }

      fields.push({
        fieldKey: `spec:${attr.key}`,
        label: locale === "fa" ? attr.label_fa : attr.label_en,
        group: "specification",
        diffType,
        oldValue: oldVal,
        newValue: newVal,
        oldDisplay: formatSpecDisplay(attr, oldVal, locale),
        newDisplay: formatSpecDisplay(attr, newVal, locale),
        isRequested:
          requestedSet.has(attr.key) ||
          requestedSet.has(`spec:${attr.key}`) ||
          requestedSet.has(`specifications.${attr.key}`) ||
          requestedSet.has("specifications"),
        sortOrder: attr.sort_order ?? 0,
      });
    }
  }

  // 5. Cost Components Comparison
  const costComponents: CostComponentDiff[] = [];
  const baseComponents = base.cost_components || [];
  const revComponents = revised.cost_components || [];

  const baseMap = new Map<string, OfferCostComponentResponse>();
  for (const c of baseComponents) {
    const key = `${c.kind}:${(c.description || "").trim()}`;
    baseMap.set(key, c);
  }

  const processedKeys = new Set<string>();

  for (const rc of revComponents) {
    const key = `${rc.kind}:${(rc.description || "").trim()}`;
    processedKeys.add(key);
    const bc = baseMap.get(key);

    if (!bc) {
      costComponents.push({
        key,
        kind: rc.kind,
        description: rc.description || "",
        diffType: "added",
        oldAmount: null,
        newAmount: rc.amount,
        currency: rc.currency,
      });
    } else {
      const equal = isCanonicalEqual(bc.amount, rc.amount) && isCanonicalEqual(bc.currency, rc.currency);
      costComponents.push({
        key,
        kind: rc.kind,
        description: rc.description || "",
        diffType: equal ? "unchanged" : "changed",
        oldAmount: bc.amount,
        newAmount: rc.amount,
        currency: rc.currency,
      });
    }
  }

  for (const [key, bc] of baseMap.entries()) {
    if (!processedKeys.has(key)) {
      costComponents.push({
        key,
        kind: bc.kind,
        description: bc.description || "",
        diffType: "removed",
        oldAmount: bc.amount,
        newAmount: null,
        currency: bc.currency,
      });
    }
  }

  const changedFields = fields.filter((f) => f.diffType !== "unchanged");
  const changedCostComponents = costComponents.filter((c) => c.diffType !== "unchanged");
  const changedCount = changedFields.length + changedCostComponents.length;

  return {
    baseVersionNumber: base.version_number,
    revisedVersionNumber: revised.version_number,
    fields,
    hasChanges: changedCount > 0,
    changedCount,
    costComponents,
  };
}

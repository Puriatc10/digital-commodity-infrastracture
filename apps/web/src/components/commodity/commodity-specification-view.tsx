import * as React from "react";
import { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utils";
import { commodityMessages } from "@/i18n/commodity-messages";

export type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
export type CommodityAttributeDefinition = components["schemas"]["CommodityAttributeDefinition"];

export interface CommoditySpecificationViewProps {
  schema: CommoditySchemaVersion;
  value: Record<string, unknown>;
  locale?: "fa" | "en";
  className?: string;
}

export function CommoditySpecificationView({
  schema,
  value,
  locale = "fa",
  className,
}: CommoditySpecificationViewProps) {
  const isRtl = locale === "fa";
  const messages = commodityMessages[locale];

  // Sort attributes based on sort_order safely
  const attributes = [...(schema.attributes || [])].sort((a, b) => {
    return (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.key.localeCompare(b.key);
  });

  const groupedAttributes = new Map<string, CommodityAttributeDefinition[]>();
  for (const attr of attributes) {
    const groupName = attr.display_group || "";
    const group = groupedAttributes.get(groupName) ?? [];
    group.push(attr);
    groupedAttributes.set(groupName, group);
  }
  const getLabel = (attr: CommodityAttributeDefinition) => {
    return locale === "fa" ? attr.label_fa : attr.label_en;
  };

  const getDisplayValue = (attr: CommodityAttributeDefinition, val: unknown) => {
    if (val === undefined || val === null || val === "") {
      return "—"; // EM dash for empty values
    }

    if (attr.data_type === "boolean") {
      const boolVal = val as boolean;
      if (locale === "fa") {
        return boolVal ? messages.yes : messages.no;
      }
      return boolVal ? messages.yes : messages.no;
    }

    if (attr.data_type === "enum") {
      const enumMeta = attr.enum_metadata;
      const options = Array.isArray(enumMeta) ? enumMeta : enumMeta?.options;
      if (Array.isArray(options)) {
        const option = options.find((o) => o.value === val);
        if (option) {
          return locale === "fa" ? option.label_fa : option.label_en;
        }
      }
      return String(val); // Fallback to canonical value if label not found
    }

    // For string, number, integer
    if (["string", "number", "integer"].includes(attr.data_type)) {
       return String(val);
    }

    // Unsupported type
    return String(val);
  };

  return (
    <div className={cn("space-y-8", className)} dir={isRtl ? "rtl" : "ltr"}>
      {[...groupedAttributes].map(([groupName, groupAttrs]) => (
        <div key={groupName} className="space-y-4">
          {groupName !== "" && (
            <h3 className="text-lg font-semibold border-b pb-2">{Object.hasOwn(messages.groups, groupName) ? messages.groups[groupName] : groupName}</h3>
          )}
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-4">
            {groupAttrs.map((attr) => {
              const labelText = getLabel(attr);
              const unitMeta = attr.unit_metadata;
              const unit = unitMeta?.canonical_unit ?? "";
              const val = value[attr.key];
              const displayValue = getDisplayValue(attr, val);

              return (
                <div key={attr.key} className="flex flex-col space-y-1">
                  <dt className="text-sm font-medium text-muted-foreground flex items-center space-x-1 rtl:space-x-reverse">
                    <span>{labelText}</span>
                    {unit && (
                      <span className="text-xs ml-1 rtl:mr-1 rtl:ml-0">
                        ({unit})
                      </span>
                    )}
                  </dt>
                  <dd className="text-sm font-medium">
                    {displayValue}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      ))}
    </div>
  );
}

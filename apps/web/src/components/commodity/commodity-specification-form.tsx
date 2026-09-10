import * as React from "react";
import { components } from "@/lib/api/generated/schema";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
export type CommodityAttributeDefinition = components["schemas"]["CommodityAttributeDefinition"];

export interface CommoditySpecificationFormProps {
  schema: CommoditySchemaVersion;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  locale?: "fa" | "en";
  className?: string;
}

interface UnitMetadata {
  canonical_unit?: string;
}

interface EnumOption {
  canonical_value: string;
  label_fa: string;
  label_en: string;
  sort_order?: number;
}

interface EnumMetadata {
  options?: EnumOption[];
}

interface ValidationMetadata {
  min?: number;
  max?: number;
  min_length?: number;
  max_length?: number;
  pattern?: string;
}

export function CommoditySpecificationForm({
  schema,
  value,
  onChange,
  locale = "fa",
  className,
}: CommoditySpecificationFormProps) {
  const isRtl = locale === "fa";

  // Sort attributes based on sort_order safely
  const attributes = [...(schema.attributes || [])].sort((a, b) => {
    return (a.sort_order ?? 0) - (b.sort_order ?? 0);
  });

  const groupedAttributes = attributes.reduce((acc, attr) => {
    const groupName = attr.display_group || "default";
    if (!acc[groupName]) acc[groupName] = [];
    acc[groupName].push(attr);
    return acc;
  }, {} as Record<string, CommodityAttributeDefinition[]>);

  const handleChange = (key: string, newValue: unknown) => {
    onChange({
      ...value,
      [key]: newValue,
    });
  };

  const getLabel = (attr: CommodityAttributeDefinition) => {
    return locale === "fa" ? attr.label_fa : attr.label_en;
  };

  return (
    <div className={cn("space-y-8", className)} dir={isRtl ? "rtl" : "ltr"}>
      {Object.entries(groupedAttributes).map(([groupName, groupAttrs]) => (
        <div key={groupName} className="space-y-6">
          {groupName !== "default" && (
            <h3 className="text-lg font-semibold">{groupName}</h3>
          )}
          <div className="space-y-6">
            {groupAttrs.map((attr) => {
              const fieldId = `field-${attr.key}`;
              const labelText = getLabel(attr);
              const isRequired = attr.is_required;
              const unitMeta = attr.unit_metadata as unknown as UnitMetadata | undefined;
              const unit = unitMeta?.canonical_unit ?? "";
              const validationMeta = attr.validation_metadata as unknown as ValidationMetadata | undefined;

              return (
                <div key={attr.key} className="space-y-2">
                  <Label htmlFor={fieldId} className="flex items-center space-x-1 rtl:space-x-reverse">
                    <span>{labelText}</span>
                    {isRequired && <span className="text-destructive">*</span>}
                    {unit && <span className="text-muted-foreground text-xs ml-1 rtl:mr-1 rtl:ml-0">({unit})</span>}
                  </Label>

                  <div className="mt-1">
                    {attr.data_type === "string" && (
                      <Input
                        id={fieldId}
                        type="text"
                        value={(value[attr.key] as string) ?? ""}
                        onChange={(e) => handleChange(attr.key, e.target.value || undefined)}
                        minLength={validationMeta?.min_length}
                        maxLength={validationMeta?.max_length}
                        pattern={validationMeta?.pattern}
                      />
                    )}

                    {attr.data_type === "number" && (
                      <Input
                        id={fieldId}
                        type="number"
                        step="any"
                        min={validationMeta?.min}
                        max={validationMeta?.max}
                        value={value[attr.key] !== undefined ? (value[attr.key] as string | number) : ""}
                        onChange={(e) => {
                          const rawValue = e.target.value;
                          if (rawValue === "") {
                            handleChange(attr.key, undefined);
                          } else {
                            const num = Number(rawValue);
                            handleChange(attr.key, isNaN(num) ? rawValue : num);
                          }
                        }}
                      />
                    )}

                    {attr.data_type === "integer" && (
                      <Input
                        id={fieldId}
                        type="number"
                        step="1"
                        min={validationMeta?.min}
                        max={validationMeta?.max}
                        value={value[attr.key] !== undefined ? (value[attr.key] as string | number) : ""}
                        onChange={(e) => {
                          const rawValue = e.target.value;
                          if (rawValue === "") {
                            handleChange(attr.key, undefined);
                          } else {
                            // Enforce integer by rejecting decimals natively
                            const num = parseInt(rawValue, 10);
                            handleChange(attr.key, isNaN(num) ? rawValue : num);
                          }
                        }}
                      />
                    )}

                    {attr.data_type === "boolean" && (
                      <Switch
                        id={fieldId}
                        checked={(value[attr.key] as boolean) ?? false}
                        onCheckedChange={(checked) => handleChange(attr.key, checked)}
                      />
                    )}

                    {attr.data_type === "enum" && (
                      <Select
                        value={(value[attr.key] as string) ?? ""}
                        onValueChange={(val) => handleChange(attr.key, val || undefined)}
                      >
                        <SelectTrigger id={fieldId} className={isRtl ? "flex-row-reverse" : ""}>
                          <SelectValue placeholder="---" />
                        </SelectTrigger>
                        <SelectContent>
                          {(() => {
                            const enumMeta = attr.enum_metadata as unknown as EnumMetadata | EnumOption[] | undefined;
                            const options = Array.isArray(enumMeta)
                              ? enumMeta
                              : enumMeta?.options;

                            if (!Array.isArray(options)) return null;

                            const sortedOptions = [...options].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

                            return sortedOptions.map((opt: EnumOption) => (
                              <SelectItem key={opt.canonical_value} value={opt.canonical_value}>
                                {locale === "fa" ? opt.label_fa : opt.label_en}
                              </SelectItem>
                            ));
                          })()}
                        </SelectContent>
                      </Select>
                    )}

                    {!["string", "number", "integer", "boolean", "enum"].includes(attr.data_type) && (
                      <div className="text-sm text-destructive">
                        Unsupported field type: {attr.data_type}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

"use client";

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
import { commodityMessages } from "@/i18n/commodity-messages";

export type CommoditySchemaVersion = components["schemas"]["CommoditySchemaVersion"];
export type CommodityAttributeDefinition = components["schemas"]["CommodityAttributeDefinition"];

export interface CommoditySpecificationFormProps {
  schema: CommoditySchemaVersion;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  locale?: "fa" | "en";
  className?: string;
  errors?: Record<string, string>;
}

export function CommoditySpecificationForm({
  schema,
  value,
  onChange,
  locale = "fa",
  className,
  errors = {},
}: CommoditySpecificationFormProps) {
  const isRtl = locale === "fa";
  const messages = commodityMessages[locale];
  const formId = React.useId();

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
      {[...groupedAttributes].map(([groupName, groupAttrs]) => (
        <div key={groupName} className="space-y-6">
          {groupName !== "" && (
            <h3 className="text-lg font-semibold">{Object.hasOwn(messages.groups, groupName) ? messages.groups[groupName] : groupName}</h3>
          )}
          <div className="space-y-6">
            {groupAttrs.map((attr) => {
              const fieldId = `${formId}-${attr.key}`;
              const fieldError = errors[attr.key];
              const accessibility = {
                "aria-required": attr.is_required,
                "aria-invalid": !!fieldError,
                "aria-describedby": fieldError ? `${fieldId}-error` : undefined,
              };
              const labelText = getLabel(attr);
              const isRequired = attr.is_required;
              const unitMeta = attr.unit_metadata;
              const unit = unitMeta?.canonical_unit ?? "";
              const validationMeta = attr.validation_metadata;

              return (
                <div key={attr.key} className="space-y-2">
                  <Label htmlFor={fieldId} className="flex items-center space-x-1 rtl:space-x-reverse">
                    <span>{labelText}</span>
                    {isRequired && <span className="text-destructive" title={messages.required}>*</span>}
                    {unit && <span className="text-muted-foreground text-xs ml-1 rtl:mr-1 rtl:ml-0">({unit})</span>}
                  </Label>

                  <div className="mt-1">
                    {attr.data_type === "string" && (
                      <Input
                        {...accessibility}
                        id={fieldId}
                        type="text"
                        value={(value[attr.key] as string) ?? ""}
                        onChange={(e) => handleChange(attr.key, e.target.value || undefined)}
                        minLength={validationMeta?.minLength}
                        maxLength={validationMeta?.maxLength}
                      />
                    )}

                    {attr.data_type === "number" && (
                      <Input
                        {...accessibility}
                        id={fieldId}
                        type="number"
                        step="any"
                        min={validationMeta?.minimum}
                        max={validationMeta?.maximum}
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
                        {...accessibility}
                        id={fieldId}
                        type="number"
                        step="1"
                        min={validationMeta?.minimum}
                        max={validationMeta?.maximum}
                        value={value[attr.key] !== undefined ? (value[attr.key] as string | number) : ""}
                        onChange={(e) => {
                          const rawValue = e.target.value;
                          if (rawValue === "") {
                            handleChange(attr.key, undefined);
                          } else {
                            // Preserve decimals so backend integer validation can reject them.
                            const num = Number(rawValue);
                            handleChange(attr.key, isNaN(num) ? rawValue : num);
                          }
                        }}
                      />
                    )}

                    {attr.data_type === "boolean" && (
                      <Switch
                        {...accessibility}
                        id={fieldId}
                        checked={(value[attr.key] as boolean) ?? false}
                        onCheckedChange={(checked) => handleChange(attr.key, checked)}
                      />
                    )}

                    {attr.data_type === "enum" && (
                      <Select
                        dir={isRtl ? "rtl" : "ltr"}
                        value={(value[attr.key] as string) ?? ""}
                        onValueChange={(val) => handleChange(attr.key, val || undefined)}
                      >
                        <SelectTrigger {...accessibility} id={fieldId}>
                          <SelectValue placeholder="---" />
                        </SelectTrigger>
                        <SelectContent>
                          {(() => {
                            const enumMeta = attr.enum_metadata;
                            const options = Array.isArray(enumMeta)
                              ? enumMeta
                              : enumMeta?.options;

                            if (!Array.isArray(options)) return null;

                            const sortedOptions = [...options].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

                            return sortedOptions.map((opt) => (
                              <SelectItem key={opt.value} value={opt.value}>
                                {locale === "fa" ? opt.label_fa : opt.label_en}
                              </SelectItem>
                            ));
                          })()}
                        </SelectContent>
                      </Select>
                    )}

                    {!["string", "number", "integer", "boolean", "enum"].includes(attr.data_type) && (
                      <div className="text-sm text-destructive">
                        {messages.unsupportedType}: {attr.data_type}
                      </div>
                    )}
                    {fieldError && <p id={`${fieldId}-error`} role="alert" className="text-sm text-destructive">{fieldError}</p>}
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

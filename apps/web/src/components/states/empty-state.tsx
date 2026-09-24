"use client";

import React from "react";
import Link from "next/link";
import { Inbox, Loader2, SearchX, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  href?: string;
  variant?: "default" | "outline";
  icon?: React.ComponentType<{ className?: string }>;
  disabled?: boolean;
  loading?: boolean;
}

export interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }> | React.ReactNode;
  isFilterEmpty?: boolean;
  onResetFilters?: () => void;
  resetFilterLabel?: string;
  action?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  variant?: "card" | "dashed" | "plain";
  className?: string;
  locale?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  isFilterEmpty = false,
  onResetFilters,
  resetFilterLabel = "پاکسازی فیلترها",
  action,
  secondaryAction,
  variant = "card",
  className,
}: EmptyStateProps) {
  const isElement = React.isValidElement(icon);
  const FallbackIcon = isFilterEmpty ? SearchX : Inbox;
  const IconComponent = !isElement && icon ? (icon as React.ComponentType<{ className?: string }>) : FallbackIcon;

  const defaultTitle = isFilterEmpty
    ? "نتیجه‌ای برای این فیلتر یافت نشد"
    : "اطلاعاتی یافت نشد";

  const defaultDescription = isFilterEmpty
    ? "تغییر یا بازنشانی فیلترها ممکن است نتایج بیشتری نشان دهد."
    : "در حال حاضر هیچ رکوردی برای نمایش وجود ندارد.";

  const content = (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center justify-center p-8 sm:p-12 text-center",
        className
      )}
    >
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground/80 mb-4">
        {isElement ? icon : <IconComponent className="size-6 shrink-0" />}
      </div>

      <h3 className="text-base font-semibold text-foreground tracking-tight">
        {title || defaultTitle}
      </h3>

      <p className="mt-2 text-xs sm:text-sm text-muted-foreground max-w-md mx-auto leading-relaxed">
        {description || defaultDescription}
      </p>

      {/* Filter Reset Button */}
      {isFilterEmpty && onResetFilters && (
        <div className="mt-5">
          <Button
            type="button"
            variant="outline"
            onClick={onResetFilters}
            className="text-xs min-h-8 h-8 px-3 gap-1.5"
          >
            <X className="size-3.5" />
            <span>{resetFilterLabel}</span>
          </Button>
        </div>
      )}

      {/* Primary and Secondary Actions */}
      {(action || secondaryAction) && (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          {action && (
            action.href ? (
              <Button
                asChild
                variant={action.variant || "default"}
                disabled={action.disabled || action.loading}
                className="text-xs min-h-8 h-8 px-3 gap-1.5"
              >
                <Link href={action.href}>
                  {action.loading ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    action.icon && <action.icon className="size-3.5" />
                  )}
                  <span>{action.label}</span>
                </Link>
              </Button>
            ) : (
              <Button
                type="button"
                variant={action.variant || "default"}
                onClick={action.onClick}
                disabled={action.disabled || action.loading}
                className="text-xs min-h-8 h-8 px-3 gap-1.5"
              >
                {action.loading ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  action.icon && <action.icon className="size-3.5" />
                )}
                <span>{action.label}</span>
              </Button>
            )
          )}

          {secondaryAction && (
            secondaryAction.href ? (
              <Button
                asChild
                variant={secondaryAction.variant || "outline"}
                className="text-xs min-h-8 h-8 px-3"
              >
                <Link href={secondaryAction.href}>
                  <span>{secondaryAction.label}</span>
                </Link>
              </Button>
            ) : (
              <Button
                type="button"
                variant={secondaryAction.variant || "outline"}
                onClick={secondaryAction.onClick}
                className="text-xs min-h-8 h-8 px-3"
              >
                <span>{secondaryAction.label}</span>
              </Button>
            )
          )}
        </div>
      )}
    </div>
  );

  if (variant === "card") {
    return <Card className="shadow-none border-border">{content}</Card>;
  }

  if (variant === "dashed") {
    return <Card className="shadow-none border-dashed border-border bg-card/50">{content}</Card>;
  }

  return content;
}

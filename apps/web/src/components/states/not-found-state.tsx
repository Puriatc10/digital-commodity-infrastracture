"use client";

import React from "react";
import Link from "next/link";
import { FileQuestion, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface NotFoundStateProps {
  title?: string;
  description?: string;
  resourceName?: string;
  resourceType?: string;
  backHref?: string;
  backLabel?: string;
  onBack?: () => void;
  className?: string;
  locale?: string;
}

export function NotFoundState({
  title,
  description,
  resourceName,
  resourceType,
  backHref,
  backLabel = "بازگشت به فهرست",
  onBack,
  className,
}: NotFoundStateProps) {
  const res = resourceName || resourceType;
  const defaultTitle = res
    ? `${res} یافت نشد`
    : "مورد درخواستی یافت نشد";

  const defaultDescription = res
    ? `${res} مورد نظر با این شناسه در سامانه ثبت نشده یا در دسترس نیست.`
    : "اطلاعات یا منبع مورد نظر ممکن است حذف شده یا نشانی آن نامعتبر باشد.";

  return (
    <Card
      role="status"
      className={cn(
        "shadow-none border-border p-8 sm:p-12 text-center min-h-[360px] flex flex-col items-center justify-center",
        className
      )}
    >
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
        <FileQuestion className="size-6 shrink-0" />
      </div>

      <div className="space-y-1.5 max-w-md mx-auto">
        <h2 className="text-lg font-bold text-foreground tracking-tight">
          {title || defaultTitle}
        </h2>
        <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
          {description || defaultDescription}
        </p>
      </div>

      {(backHref || onBack) && (
        <div className="mt-6">
          {onBack ? (
            <Button
              type="button"
              variant="outline"
              onClick={onBack}
              className="text-xs min-h-8 h-8 px-3 gap-1.5"
            >
              <ArrowLeft className="size-3.5 rtl:rotate-180" />
              <span>{backLabel}</span>
            </Button>
          ) : backHref ? (
            <Button
              asChild
              variant="outline"
              className="text-xs min-h-8 h-8 px-3 gap-1.5"
            >
              <Link href={backHref} role="button">
                <ArrowLeft className="size-3.5 rtl:rotate-180" />
                <span>{backLabel}</span>
              </Link>
            </Button>
          ) : null}
        </div>
      )}
    </Card>
  );
}

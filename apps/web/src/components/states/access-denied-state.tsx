"use client";

import React from "react";
import Link from "next/link";
import { ShieldAlert, LogIn, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface AccessDeniedStateProps {
  title?: string;
  description?: string;
  status?: 401 | 403;
  statusCode?: 401 | 403;
  loginHref?: string;
  loginLabel?: string;
  backHref?: string;
  backLabel?: string;
  className?: string;
  locale?: string;
}

export function AccessDeniedState({
  title,
  description,
  status,
  statusCode,
  loginHref,
  loginLabel = "ورود به حساب کاربری",
  backHref,
  backLabel = "بازگشت",
  className,
  locale = "fa",
}: AccessDeniedStateProps) {
  const resolvedStatus = statusCode ?? status ?? 403;
  const is401 = resolvedStatus === 401;

  const defaultTitle = is401
    ? "نیاز به ورود و احراز هویت (۴۰۱)"
    : "عدم دسترسی و مجوز لازم (۴۰۳)";

  const defaultDescription = is401
    ? "نشست کاربری شما معتبر نیست یا منقضی شده است. لطفاً از طریق بخش بالای صفحه یا ورود به حساب کاربری اقدام نمایید."
    : "شما یا سازمان فعال فعلی مجوز دسترسی به این بخش یا منبع را ندارید. در صورت لزوم می‌توانید از نوار بالای صفحه، سازمان یا شخصیت نمایشی متناسب را انتخاب کنید.";

  return (
    <Card
      role="alert"
      className={cn(
        "shadow-none border-amber-500/20 bg-amber-500/5 p-8 sm:p-12 text-center min-h-[320px] flex flex-col items-center justify-center",
        className
      )}
    >
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400 mb-4">
        {is401 ? (
          <LogIn className="size-6 shrink-0" />
        ) : (
          <ShieldAlert className="size-6 shrink-0" />
        )}
      </div>

      <div className="space-y-1.5 max-w-md mx-auto">
        <h2 className="text-base sm:text-lg font-bold text-amber-900 dark:text-amber-200 tracking-tight">
          {title || defaultTitle}
        </h2>
        <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
          {description || defaultDescription}
        </p>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        {is401 && (
          <Button asChild className="text-xs min-h-8 h-8 px-3 gap-1.5">
            <Link href={loginHref || `/${locale}/login`}>
              <LogIn className="size-3.5" />
              <span>{loginLabel}</span>
            </Link>
          </Button>
        )}
        {backHref && (
          <Button asChild variant="outline" className="text-xs min-h-8 h-8 px-3 gap-1.5">
            <Link href={backHref}>
              <ArrowLeft className="size-3.5 rtl:rotate-180" />
              <span>{backLabel}</span>
            </Link>
          </Button>
        )}
      </div>
    </Card>
  );
}

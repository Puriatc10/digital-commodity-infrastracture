"use client";

import React from "react";
import Link from "next/link";
import { AlertCircle, RefreshCw, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface ErrorStateProps {
  title?: string;
  message?: string;
  errorMessage?: string;
  description?: string;
  srError?: string;
  statusCode?: number;
  onRetry?: () => void;
  retryLabel?: string;
  backHref?: string;
  backLabel?: string;
  variant?: "page" | "section" | "banner";
  className?: string;
  locale?: string;
}

/**
 * Sanitizes technical error messages to prevent exposing stack traces,
 * database errors, SQL fragments, or raw JSON payloads to the user.
 */
function sanitizeErrorMessage(raw?: string): string {
  if (!raw || typeof raw !== "string") {
    return "ارتباط با سرور با خطا مواجه شد. لطفاً دوباره تلاش کنید.";
  }

  const trimmed = raw.trim();

  // Check for technical/internal implementation keywords
  const isTechnical =
    trimmed.startsWith("{") ||
    trimmed.startsWith("[") ||
    trimmed.includes("Traceback (most recent call last)") ||
    trimmed.includes("OperationalError") ||
    trimmed.includes("ProgrammingError") ||
    trimmed.includes("IntegrityError") ||
    trimmed.includes("PostgreSQL") ||
    trimmed.includes("psycopg") ||
    trimmed.includes("django.db") ||
    trimmed.includes("SELECT ") ||
    trimmed.includes("INSERT INTO") ||
    trimmed.includes("at Object.") ||
    trimmed.includes("at Module.") ||
    trimmed.includes("at process.") ||
    trimmed.includes("TypeError:") ||
    trimmed.includes("ReferenceError:") ||
    trimmed.includes("SyntaxError:") ||
    trimmed.includes("ECONNREFUSED") ||
    trimmed.includes("ETIMEDOUT");

  if (isTechnical) {
    return "سامانه با خطای موقت در پردازش اطلاعات مواجه شد. لطفاً دوباره تلاش کنید.";
  }

  return trimmed;
}

export function ErrorState({
  title = "خطا در برقراری ارتباط",
  message,
  errorMessage,
  description,
  srError,
  statusCode,
  onRetry,
  retryLabel = "تلاش مجدد",
  backHref,
  backLabel = "بازگشت",
  variant = "section",
  className,
}: ErrorStateProps) {
  const safeMessage = sanitizeErrorMessage(errorMessage ?? message ?? description);

  if (variant === "banner") {
    return (
      <div
        role="alert"
        className={cn(
          "rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-xs text-destructive flex items-start justify-between gap-3",
          className
        )}
      >
        <div className="flex items-start gap-2.5">
          <AlertCircle className="size-4 shrink-0 mt-0.5 text-destructive" />
          <div className="space-y-0.5">
            <p className="font-semibold">{title}</p>
            <p className="text-destructive/90">{safeMessage}</p>
            {srError && <span className="sr-only">{srError}</span>}
          </div>
        </div>
        {onRetry && (
          <Button
            type="button"
            variant="outline"
            onClick={onRetry}
            className="text-xs min-h-7 h-7 px-2.5 shrink-0 gap-1 border-destructive/30 hover:bg-destructive/10 text-destructive"
          >
            <RefreshCw className="size-3" />
            <span>{retryLabel}</span>
          </Button>
        )}
      </div>
    );
  }

  const isPage = variant === "page";

  const content = (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center p-8 sm:p-12 text-center",
        className
      )}
    >
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive mb-4">
        <AlertCircle className="size-6 shrink-0" />
      </div>

      <div className="space-y-1 max-w-md mx-auto">
        <h3 className="text-base font-semibold text-destructive tracking-tight">
          {title}
          {statusCode ? ` (${statusCode})` : ""}
        </h3>
        <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
          {safeMessage}
        </p>
        {srError && <span className="sr-only">{srError}</span>}
      </div>

      {(onRetry || backHref) && (
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          {onRetry && (
            <Button
              type="button"
              variant="default"
              onClick={onRetry}
              className="text-xs min-h-8 h-8 px-3 gap-1.5"
            >
              <RefreshCw className="size-3.5" />
              <span>{retryLabel}</span>
            </Button>
          )}

          {backHref && (
            <Button
              asChild
              variant="outline"
              className="text-xs min-h-8 h-8 px-3 gap-1.5"
            >
              <Link href={backHref}>
                <ArrowLeft className="size-3.5 rtl:rotate-180" />
                <span>{backLabel}</span>
              </Link>
            </Button>
          )}
        </div>
      )}
    </div>
  );

  return (
    <Card
      className={cn(
        "shadow-none border-destructive/20 bg-destructive/5",
        isPage ? "min-h-[400px]" : "min-h-[200px]"
      )}
    >
      {content}
    </Card>
  );
}

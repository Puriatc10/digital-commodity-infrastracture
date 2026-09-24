"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface LoadingStateProps {
  message?: string;
  description?: string;
  variant?: "page" | "section" | "inline";
  className?: string;
  locale?: string;
}

export function LoadingState({
  message = "در حال بارگذاری اطلاعات…",
  description,
  variant = "section",
  className,
}: LoadingStateProps) {
  if (variant === "inline") {
    return (
      <div
        role="status"
        aria-live="polite"
        className={cn("flex items-center justify-center gap-2 py-3 text-xs text-muted-foreground", className)}
      >
        <Loader2 className="size-4 animate-spin text-primary shrink-0" />
        <span>{message}</span>
      </div>
    );
  }

  const isPage = variant === "page";

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center text-center text-muted-foreground",
        isPage ? "min-h-[400px] p-12" : "min-h-[180px] p-8",
        className
      )}
    >
      <Loader2 className={cn("animate-spin text-primary shrink-0", isPage ? "size-9" : "size-6")} />
      <p className={cn("font-medium text-foreground mt-3", isPage ? "text-base" : "text-sm")}>
        {message}
      </p>
      {description && (
        <p className="mt-1 text-xs text-muted-foreground max-w-sm leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
}

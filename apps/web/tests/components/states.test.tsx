import React from "react";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  LoadingState,
  EmptyState,
  ErrorState,
  NotFoundState,
  AccessDeniedState,
} from "@/components/states";
import { FileText } from "lucide-react";

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/fa/trade-hub",
  useSearchParams: () => new URLSearchParams(),
}));

describe("State Primitives Component Suite (T1305)", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe("LoadingState", () => {
    it("renders polite aria-live container with default Persian message", () => {
      render(<LoadingState locale="fa" />);
      const statusElement = screen.getByRole("status");
      expect(statusElement).toBeInTheDocument();
      expect(statusElement).toHaveAttribute("aria-live", "polite");
      expect(screen.getByText("در حال بارگذاری اطلاعات…")).toBeInTheDocument();
    });

    it("renders custom message and description", () => {
      render(
        <LoadingState
          message="در حال بارگذاری معاملات..."
          description="لطفاً شکیبا باشید"
          locale="fa"
        />
      );
      expect(screen.getByText("در حال بارگذاری معاملات...")).toBeInTheDocument();
      expect(screen.getByText("لطفاً شکیبا باشید")).toBeInTheDocument();
    });

    it("renders section and inline variants properly", () => {
      const { rerender } = render(<LoadingState variant="section" locale="fa" />);
      expect(screen.getByRole("status")).toBeInTheDocument();

      rerender(<LoadingState variant="inline" message="در حال بارگذاری..." locale="fa" />);
      expect(screen.getByText("در حال بارگذاری...")).toBeInTheDocument();
    });
  });

  describe("EmptyState", () => {
    it("renders zero-record title and description", () => {
      render(
        <EmptyState
          title="هیچ معامله‌ای یافت نشد"
          description="هنوز معامله‌ای در سامانه ثبت نگردیده است."
          locale="fa"
        />
      );
      expect(screen.getByText("هیچ معامله‌ای یافت نشد")).toBeInTheDocument();
      expect(
        screen.getByText("هنوز معامله‌ای در سامانه ثبت نگردیده است.")
      ).toBeInTheDocument();
    });

    it("renders custom icon and action button", () => {
      const handleAction = vi.fn();
      render(
        <EmptyState
          icon={FileText}
          title="اسناد خالی است"
          action={{
            label: "بارگذاری سند جدید",
            onClick: handleAction,
          }}
          locale="fa"
        />
      );

      expect(screen.getByText("اسناد خالی است")).toBeInTheDocument();
      const actionButton = screen.getByRole("button", { name: "بارگذاری سند جدید" });
      expect(actionButton).toBeInTheDocument();

      fireEvent.click(actionButton);
      expect(handleAction).toHaveBeenCalledTimes(1);
    });

    it("renders filter reset CTA and triggers reset callback", () => {
      const handleReset = vi.fn();
      render(
        <EmptyState
          title="نتیجه‌ای یافت نشد"
          isFilterEmpty={true}
          onResetFilters={handleReset}
          locale="fa"
        />
      );

      expect(screen.getByText("نتیجه‌ای یافت نشد")).toBeInTheDocument();
      expect(
        screen.getByText("تغییر یا بازنشانی فیلترها ممکن است نتایج بیشتری نشان دهد.")
      ).toBeInTheDocument();
      const resetBtn = screen.getByRole("button", { name: "پاکسازی فیلترها" });
      expect(resetBtn).toBeInTheDocument();

      fireEvent.click(resetBtn);
      expect(handleReset).toHaveBeenCalledTimes(1);
    });

    it("renders different container variants (card, dashed, plain)", () => {
      const { rerender } = render(
        <EmptyState title="تست کارت" variant="card" locale="fa" />
      );
      expect(screen.getByText("تست کارت")).toBeInTheDocument();

      rerender(<EmptyState title="تست خط‌چین" variant="dashed" locale="fa" />);
      expect(screen.getByText("تست خط‌چین")).toBeInTheDocument();

      rerender(<EmptyState title="تست ساده" variant="plain" locale="fa" />);
      expect(screen.getByText("تست ساده")).toBeInTheDocument();
    });
  });

  describe("ErrorState", () => {
    it("sanitizes raw SQL strings and never exposes database internals", () => {
      const rawSqlError =
        'OperationalError: relation "deals_deal" does not exist at character 15, SELECT * FROM deals_deal WHERE status = \'active\'';
      render(<ErrorState errorMessage={rawSqlError} locale="fa" />);

      // Must NOT contain raw SQL or table names
      expect(screen.queryByText(/SELECT \* FROM/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/deals_deal/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/OperationalError/i)).not.toBeInTheDocument();

      // Must display safe Persian fallback
      expect(
        screen.getByText("سامانه با خطای موقت در پردازش اطلاعات مواجه شد. لطفاً دوباره تلاش کنید.")
      ).toBeInTheDocument();
    });

    it("sanitizes Python / Django stack traces and raw JSON blobs", () => {
      const rawStackTrace = `Traceback (most recent call last):
  File "/srv/app/views.py", line 42, in get
    raise KeyError("invalid_secret_key")
KeyError: 'invalid_secret_key'`;
      render(<ErrorState errorMessage={rawStackTrace} locale="fa" />);

      // Must NOT show traceback or source file paths
      expect(screen.queryByText(/Traceback/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/views\.py/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/invalid_secret_key/i)).not.toBeInTheDocument();

      // Must display safe Persian fallback
      expect(
        screen.getByText("سامانه با خطای موقت در پردازش اطلاعات مواجه شد. لطفاً دوباره تلاش کنید.")
      ).toBeInTheDocument();
    });

    it("renders safe user message when clean string is provided", () => {
      const safeMessage = "اتصال به اینترنت برقرار نیست. لطفاً شبکه خود را بررسی کنید.";
      render(<ErrorState errorMessage={safeMessage} locale="fa" />);

      expect(screen.getByText(safeMessage)).toBeInTheDocument();
    });

    it("renders retry button and triggers callback", () => {
      const handleRetry = vi.fn();
      render(<ErrorState onRetry={handleRetry} locale="fa" />);

      const retryBtn = screen.getByRole("button", { name: "تلاش مجدد" });
      expect(retryBtn).toBeInTheDocument();

      fireEvent.click(retryBtn);
      expect(handleRetry).toHaveBeenCalledTimes(1);
    });

    it("renders back button when backHref is provided", () => {
      render(<ErrorState backHref="/fa/trade-hub" locale="fa" />);

      const backLink = screen.getByRole("link", { name: "بازگشت" });
      expect(backLink).toBeInTheDocument();
      expect(backLink).toHaveAttribute("href", "/fa/trade-hub");
    });
  });

  describe("NotFoundState", () => {
    it("distinguishes absent resource (404) from empty list", () => {
      render(<NotFoundState locale="fa" />);

      expect(screen.getByText("مورد درخواستی یافت نشد")).toBeInTheDocument();
      expect(
        screen.getByText("اطلاعات یا منبع مورد نظر ممکن است حذف شده یا نشانی آن نامعتبر باشد.")
      ).toBeInTheDocument();
    });

    it("renders custom title, description and back navigation", () => {
      render(
        <NotFoundState
          title="معامله یافت نشد"
          description="شناسه معامله معتبر نمی‌باشد."
          backHref="/fa/deals"
          backLabel="بازگشت به فهرست معاملات"
          locale="fa"
        />
      );

      expect(screen.getByText("معامله یافت نشد")).toBeInTheDocument();
      expect(screen.getByText("شناسه معامله معتبر نمی‌باشد.")).toBeInTheDocument();

      const backBtn = screen.getByRole("button", { name: "بازگشت به فهرست معاملات" });
      expect(backBtn).toBeInTheDocument();
      expect(backBtn).toHaveAttribute("href", "/fa/deals");
    });

    it("calls onBack callback when provided", () => {
      const handleBack = vi.fn();
      render(
        <NotFoundState
          onBack={handleBack}
          backLabel="بازگشت"
          locale="fa"
        />
      );

      const backBtn = screen.getByRole("button", { name: "بازگشت" });
      fireEvent.click(backBtn);
      expect(handleBack).toHaveBeenCalledTimes(1);
    });
  });

  describe("AccessDeniedState", () => {
    it("distinguishes 401 unauthenticated condition and provides login CTA", () => {
      render(<AccessDeniedState statusCode={401} locale="fa" />);

      expect(
        screen.getByText("نیاز به ورود و احراز هویت (۴۰۱)")
      ).toBeInTheDocument();
      expect(
        screen.getByText("نشست کاربری شما معتبر نیست یا منقضی شده است. لطفاً از طریق بخش بالای صفحه یا ورود به حساب کاربری اقدام نمایید.")
      ).toBeInTheDocument();

      const loginLink = screen.getByRole("link", { name: "ورود به حساب کاربری" });
      expect(loginLink).toBeInTheDocument();
      expect(loginLink).toHaveAttribute("href", "/fa/login");
    });

    it("distinguishes 403 forbidden condition and explains permission denial", () => {
      render(<AccessDeniedState statusCode={403} locale="fa" />);

      expect(
        screen.getByText("عدم دسترسی و مجوز لازم (۴۰۳)")
      ).toBeInTheDocument();
      expect(
        screen.getByText("شما یا سازمان فعال فعلی مجوز دسترسی به این بخش یا منبع را ندارید. در صورت لزوم می‌توانید از نوار بالای صفحه، سازمان یا شخصیت نمایشی متناسب را انتخاب کنید.")
      ).toBeInTheDocument();

      // Does NOT show login link for 403
      expect(screen.queryByRole("link", { name: "ورود به حساب کاربری" })).not.toBeInTheDocument();
    });

    it("never collapses access denial into 'no data found'", () => {
      render(<AccessDeniedState statusCode={403} locale="fa" />);

      expect(screen.queryByText(/هیچ داده‌ای یافت نشد/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/داده‌ای وجود ندارد/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/اطلاعاتی یافت نشد/i)).not.toBeInTheDocument();
    });

    it("renders custom title, description, and back link", () => {
      render(
        <AccessDeniedState
          statusCode={403}
          title="دسترسی به استعلام مسدود است"
          description="تنها طرفین مجاز یا اپراتور می‌توانند این استعلام را بررسی کنند."
          backHref="/fa/trade-hub"
          locale="fa"
        />
      );

      expect(screen.getByText("دسترسی به استعلام مسدود است")).toBeInTheDocument();
      expect(
        screen.getByText("تنها طرفین مجاز یا اپراتور می‌توانند این استعلام را بررسی کنند.")
      ).toBeInTheDocument();

      const backLink = screen.getByRole("link", { name: "بازگشت" });
      expect(backLink).toBeInTheDocument();
      expect(backLink).toHaveAttribute("href", "/fa/trade-hub");
    });
  });
});

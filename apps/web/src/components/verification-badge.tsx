import { Badge } from "@/components/ui/badge";

export function getVerificationStatusInfo(status: string) {
  switch (status) {
    case "verified":
      return {
        label: "تایید شده",
        variant: "default" as const,
        className: "bg-green-600 hover:bg-green-700 text-white",
      };
    case "basic_verified":
      return {
        label: "تایید اولیه",
        variant: "default" as const,
        className: "bg-teal-600 hover:bg-teal-700 text-white",
      };
    case "under_review":
      return {
        label: "در حال بررسی",
        variant: "secondary" as const,
        className: "bg-blue-100 text-blue-800 border-blue-300",
      };
    case "documents_submitted":
      return {
        label: "مدارک ارسال شده",
        variant: "secondary" as const,
        className: "bg-amber-100 text-amber-800 border-amber-300",
      };
    case "suspended":
      return {
        label: "تعلیق شده",
        variant: "destructive" as const,
        className: "",
      };
    case "unverified":
    default:
      return {
        label: "تایید نشده",
        variant: "outline" as const,
        className: "",
      };
  }
}

export function VerificationBadge({ status }: { status: string }) {
  const info = getVerificationStatusInfo(status);
  return (
    <Badge variant={info.variant} className={info.className}>
      {info.label}
    </Badge>
  );
}

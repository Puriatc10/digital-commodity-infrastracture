// Shared renderer text and translations of definition presentation groups.
// English is an architectural target; this does not enable /en routing.
type CommodityMessages = {
  yes: string;
  no: string;
  required: string;
  unsupportedType: string;
  groups: Record<string, string>;
};

export const commodityMessages: Record<"fa" | "en", CommodityMessages> = {
  fa: {
    yes: "بله", no: "خیر", required: "الزامی", unsupportedType: "نوع فیلد پشتیبانی نمی‌شود",
    groups: {
      Classification: "طبقه‌بندی",
      "Physical Properties": "ویژگی‌های فیزیکی",
      "Safety Properties": "ویژگی‌های ایمنی",
      "Chemical Properties": "ویژگی‌های شیمیایی",
    },
  },
  en: {
    yes: "Yes", no: "No", required: "Required", unsupportedType: "Unsupported field type",
    groups: {},
  },
};

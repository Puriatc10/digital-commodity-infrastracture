import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixtures from "../fixtures/commodity-schemas.json";
import { CommoditySpecificationForm, type CommoditySchemaVersion } from "@/components/commodity/commodity-specification-form";
import { CommoditySpecificationView } from "@/components/commodity/commodity-specification-view";

afterEach(cleanup);
HTMLElement.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
HTMLElement.prototype.releasePointerCapture = vi.fn();
HTMLElement.prototype.setPointerCapture = vi.fn();

// JSON import widens enum strings; backend CI verifies these are actual API responses.
const schemas = fixtures as Record<keyof typeof fixtures, CommoditySchemaVersion>;

describe("Seed → PostgreSQL validator → API → generated types → Form/View", () => {
  it.each([
    ["bitumen", "درجه نفوذ", "۶۰/۷۰", "penetration_grade", "60/70", "نقطه نرمی", "softening_point", 49],
    ["base_oil", "گروه روغن پایه", "گروه ۱", "base_oil_group", "Group I", "گرانروی در ۴۰ درجه", "viscosity_at_40c", 96.5],
  ] as const)("uses real %s metadata end to end", async (name, label, option, key, canonical, numericLabel, numericKey, numericValue) => {
    const user = userEvent.setup();
    let output: Record<string, unknown> = {};
    function Harness() {
      const [value, setValue] = React.useState<Record<string, unknown>>({});
      output = value;
      return <><CommoditySpecificationForm schema={schemas[name]} value={value} onChange={setValue} />
        <CommoditySpecificationView schema={schemas[name]} value={value} /></>;
    }
    const { container } = render(<Harness />);
    expect(container.firstChild).toHaveAttribute("dir", "rtl");
    await user.click(screen.getByRole("combobox", { name: new RegExp(label) }));
    await user.click(await screen.findByRole("option", { name: option }));
    fireEvent.change(screen.getByRole("spinbutton", { name: new RegExp(numericLabel) }), { target: { value: String(numericValue) } });
    expect(output).toEqual({ [key]: canonical, [numericKey]: numericValue });
    expect([...container.querySelectorAll("dd")].map(el => el.textContent)).toContain(option);
    expect(screen.getAllByText("طبقه‌بندی")).toHaveLength(2);
    expect(screen.getByRole("spinbutton", { name: new RegExp(numericLabel) })).toHaveAttribute("min", "0");
  });

  it("keeps retired v1 labels while a different supplied v2 is current", () => {
    const value = { penetration_grade: "60/70" };
    const { rerender } = render(<CommoditySpecificationView schema={schemas.bitumen_historical} value={value} />);
    expect(screen.getByText("۶۰/۷۰")).toBeInTheDocument();
    expect(screen.queryByText("عنوان جدید ۶۰/۷۰")).not.toBeInTheDocument();
    rerender(<CommoditySpecificationView schema={schemas.bitumen_v2} value={value} />);
    expect(screen.getByText("عنوان جدید ۶۰/۷۰")).toBeInTheDocument();
    rerender(<CommoditySpecificationView schema={schemas.bitumen_historical} value={value} />);
    expect(screen.getByText("۶۰/۷۰")).toBeInTheDocument();
  });

  it("attaches backend field errors and uses unique IDs across forms", () => {
    const schema = schemas.bitumen;
    render(<><CommoditySpecificationForm schema={schema} value={{}} onChange={() => {}} errors={{ penetration_grade: "مقدار نامعتبر" }} />
      <CommoditySpecificationForm schema={schema} value={{}} onChange={() => {}} /></>);
    const selects = screen.getAllByRole("combobox");
    expect(selects[0].id).not.toEqual(selects[1].id);
    expect(selects[0]).toHaveAttribute("aria-invalid", "true");
    expect(selects[0]).toHaveAccessibleDescription("مقدار نامعتبر");
    expect(selects[0]).toHaveAttribute("aria-required", "true");
  });

  it("treats arbitrary group names as data and respects key ordering ties", () => {
    const schema = { ...schemas.bitumen, attributes: [...schemas.bitumen.attributes].reverse().map(attr => ({
      ...attr, sort_order: 0, display_group: "constructor",
    })) };
    const { container } = render(<><CommoditySpecificationForm schema={schema} value={{}} onChange={() => {}} />
      <CommoditySpecificationView schema={schema} value={{}} /></>);
    expect(screen.getAllByText("constructor")).toHaveLength(2);
    expect(container.querySelector("label")?.textContent).toContain("انگمی");
  });
});

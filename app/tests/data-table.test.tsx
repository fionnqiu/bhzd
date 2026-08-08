import { readFileSync } from "node:fs";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DataTable, { type Column } from "../src/components/DataTable";

interface ResultRow {
  id: string;
  name: string;
  status: string;
}

const columns: Column<ResultRow>[] = [
  { key: "name", title: "Name", width: "12rem" },
  { key: "status", title: "Status", width: "8rem" },
];

describe("DataTable", () => {
  it("focuses only an overflowing scroll viewport and applies column widths through colgroup", () => {
    render(
      <DataTable
        ariaLabel="Result rows"
        columns={columns}
        rows={[{ id: "row-1", name: "A long unbroken result name", status: "Ready" }]}
      />,
    );

    const viewport = screen.getByRole("region", { name: "Result rows" });
    const table = within(viewport).getByRole("table");
    const [nameColumn, statusColumn] = table.querySelectorAll("col");

    expect(viewport).toHaveClass("table-wrap");
    expect(viewport).not.toHaveAttribute("tabindex");

    Object.defineProperties(viewport, {
      clientWidth: { configurable: true, value: 200 },
      scrollWidth: { configurable: true, value: 320 },
    });
    fireEvent(window, new Event("resize"));

    expect(viewport).toHaveAttribute("tabindex", "0");
    expect(nameColumn).toHaveStyle({ width: "12rem" });
    expect(statusColumn).toHaveStyle({ width: "8rem" });
    expect(within(table).getByRole("columnheader", { name: "Name" })).toHaveAttribute(
      "scope",
      "col",
    );
    expect(
      within(table).getByRole("cell", { name: "A long unbroken result name" }),
    ).toBeInTheDocument();
  });

  it("keeps empty content inside the same table surface", () => {
    render(
      <DataTable ariaLabel="Empty results" columns={columns} rows={[]} empty="No result rows" />,
    );

    const viewport = screen.getByRole("region", { name: "Empty results" });
    expect(within(viewport).getByText("No result rows")).toHaveClass("table-empty");
  });

  it("keeps loading feedback inside the shared table surface", () => {
    render(<DataTable ariaLabel="Loading results" columns={columns} rows={[]} loading />);

    const viewport = screen.getByRole("region", { name: "Loading results" });
    const loadingCell = within(viewport)
      .getByText(/加载中/)
      .closest("td");
    expect(loadingCell).not.toBeNull();
    expect(loadingCell!).toHaveClass("table-empty");
  });

  it("declares horizontal scrolling and no-wrap as global table contracts", () => {
    const css = readFileSync("src/index.css", "utf8");

    expect(css).toMatch(/\.table-wrap\s*\{[^}]*overflow-x:\s*auto;/s);
    expect(css).toMatch(/\.table th,\s*\.table td\s*\{[^}]*white-space:\s*nowrap;/s);
    expect(css).toMatch(/\.table td\.table-empty\s*\{[^}]*white-space:\s*normal;/s);
  });

  it("does not reserve a vertical scrollbar gutter for the horizontally scrolling provider table", () => {
    const css = readFileSync("src/index.css", "utf8");

    expect(css).toMatch(/\.provider-table\s*>\s*\.table-wrap\s*\{[^}]*scrollbar-gutter:\s*auto;/s);
  });
});

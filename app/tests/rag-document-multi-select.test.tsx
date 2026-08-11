import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RagDocumentMultiSelect from "../src/pages/rag/RagDocumentMultiSelect";

const documents = [
  { id: "doc-1", title: "客服规范" },
  { id: "doc-2", title: "车载指南" },
] as never[];

describe("RagDocumentMultiSelect", () => {
  it("exposes a keyboard-safe multi-select listbox and clear action", () => {
    const onChange = vi.fn();
    render(
      <RagDocumentMultiSelect
        label="召回资料集"
        documents={documents}
        value={[]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "召回资料集" }));
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    fireEvent.click(screen.getByRole("option", { name: "客服规范" }));
    expect(onChange).toHaveBeenCalledWith(["doc-1"]);
  });

  it("renders the selected summary and clears the controlled selection", () => {
    const onChange = vi.fn();
    render(
      <RagDocumentMultiSelect
        label="必须命中文档"
        documents={documents}
        value={["doc-1", "doc-2"]}
        onChange={onChange}
      />,
    );

    expect(screen.getByText("已选 2 份资料")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除必须命中文档" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Pagination from "../src/components/Pagination";

describe("Pagination", () => {
  it("reports the selected page size and jumps to a valid page", () => {
    const onChange = vi.fn();
    const onLimitChange = vi.fn();

    render(
      <Pagination
        offset={20}
        limit={20}
        total={101}
        onChange={onChange}
        onLimitChange={onLimitChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "每页显示条数" }));
    fireEvent.click(screen.getByRole("option", { name: "50 条/页" }));
    expect(onLimitChange).toHaveBeenCalledWith(50);

    fireEvent.change(screen.getByLabelText("跳转到第几页"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "跳转" }));
    expect(onChange).toHaveBeenCalledWith(60);
  });

  it("does not navigate to an invalid page number", () => {
    const onChange = vi.fn();

    render(<Pagination offset={0} limit={20} total={41} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("跳转到第几页"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "跳转" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("跳转到第几页")).toHaveValue(1);
  });
});

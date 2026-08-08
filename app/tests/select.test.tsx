import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Field from "../src/components/Field";
import Select from "../src/components/Select";
import { MOTION_EXIT_MS } from "../src/components/usePresence";

const OPTIONS = [
  { value: "alpha", label: "Alpha" },
  { value: "bravo", label: "Bravo" },
  { value: "charlie", label: "Charlie" },
];

function ControlledSelect({ onChange = vi.fn() }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState("alpha");
  return (
    <Select
      aria-label="Example selection"
      options={OPTIONS}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
        setValue(event.target.value);
      }}
    />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Select", () => {
  it("renders a project listbox in document.body and preserves the existing onChange value", () => {
    const onChange = vi.fn();
    render(<ControlledSelect onChange={onChange} />);

    const trigger = screen.getByRole("combobox", { name: "Example selection" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    const listbox = screen.getByRole("listbox", { name: "Example selection" });
    expect(listbox.parentElement).toBe(document.body);
    expect(screen.getByRole("option", { name: "Alpha" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("option", { name: "Bravo" }));
    expect(onChange).toHaveBeenCalledWith("bravo");
    expect(trigger).toHaveTextContent("Bravo");
    expect(trigger).toHaveFocus();
  });

  it("keeps a form-compatible native value bridge while the visible control is custom", () => {
    render(
      <form aria-label="Selection form">
        <Select
          aria-label="Form selection"
          defaultValue="alpha"
          name="selection"
          options={OPTIONS}
        />
      </form>,
    );

    const form = screen.getByRole("form", { name: "Selection form" }) as HTMLFormElement;
    expect(new FormData(form).get("selection")).toBe("alpha");

    fireEvent.click(screen.getByRole("combobox", { name: "Form selection" }));
    fireEvent.click(screen.getByRole("option", { name: "Charlie" }));
    expect(new FormData(form).get("selection")).toBe("charlie");
  });

  it("links a single Field control to its visual label without per-page aria wiring", () => {
    render(
      <Field label="Learning role" hint="Choose one role">
        <Select defaultValue="alpha" options={OPTIONS} />
      </Field>,
    );

    const trigger = screen.getByRole("combobox", { name: "Learning role" });
    expect(trigger).toHaveAccessibleDescription("Choose one role");
  });

  it("uses Home and End as the active boundary when opening from a closed trigger", () => {
    render(<Select aria-label="Keyboard selection" defaultValue="bravo" options={OPTIONS} />);
    const trigger = screen.getByRole("combobox", { name: "Keyboard selection" });

    fireEvent.keyDown(trigger, { key: "End" });
    expect(screen.getByRole("option", { name: "Charlie" })).toHaveAttribute("data-active", "true");

    fireEvent.keyDown(trigger, { key: "Escape" });
    fireEvent.keyDown(trigger, { key: "Home" });
    expect(screen.getByRole("option", { name: "Alpha" })).toHaveAttribute("data-active", "true");
  });

  it("moves the active option with arrows and commits it with Enter", () => {
    const onChange = vi.fn();
    render(<ControlledSelect onChange={onChange} />);
    const trigger = screen.getByRole("combobox", { name: "Example selection" });

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "Bravo" })).toHaveAttribute("data-active", "true");

    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("bravo");
    expect(trigger).toHaveTextContent("Bravo");
  });

  it("retains the closing listbox for its exit motion and closes on an external pointer press", () => {
    vi.useFakeTimers();
    render(<Select aria-label="Dismissable selection" defaultValue="alpha" options={OPTIONS} />);
    const trigger = screen.getByRole("combobox", { name: "Dismissable selection" });

    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    const listbox = screen.getByRole("listbox", { name: "Dismissable selection" });
    expect(listbox).toHaveAttribute("data-motion-state", "closing");

    act(() => vi.advanceTimersByTime(MOTION_EXIT_MS));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("positions a constrained trigger above when the lower viewport space is insufficient", () => {
    const originalInnerHeight = window.innerHeight;
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 300 });
    render(<Select aria-label="Positioned selection" defaultValue="alpha" options={OPTIONS} />);
    const trigger = screen.getByRole("combobox", { name: "Positioned selection" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 278,
      height: 36,
      left: 24,
      right: 184,
      top: 242,
      width: 160,
      x: 24,
      y: 242,
      toJSON: () => ({}),
    });

    fireEvent.click(trigger);
    const listbox = screen.getByRole("listbox", { name: "Positioned selection" });
    expect(listbox).toHaveAttribute("data-placement", "above");
    expect(listbox).toHaveStyle({ bottom: "62px", width: "160px" });

    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: originalInnerHeight,
    });
  });

  it("exposes disabled and invalid states on the visible trigger", () => {
    render(<Select aria-label="Unavailable selection" disabled invalid options={OPTIONS} />);
    const trigger = screen.getByRole("combobox", { name: "Unavailable selection" });

    expect(trigger).toBeDisabled();
    expect(trigger).toHaveAttribute("aria-invalid", "true");
    fireEvent.click(trigger);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

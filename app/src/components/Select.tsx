import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type ForwardedRef,
  type KeyboardEvent,
  type MouseEvent,
  type SelectHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { usePresence } from "./usePresence";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "children" | "multiple" | "size"
> {
  options: readonly SelectOption[];
  /** Placeholder is represented as the same empty-value option as the former native select. */
  placeholder?: string;
  invalid?: boolean;
}

interface PopoverPosition {
  placement: "above" | "below";
  style: CSSProperties;
}

const VIEWPORT_GUTTER = 8;
const POPUP_GAP = 4;
const IDEAL_LIST_HEIGHT = 240;
const MIN_LIST_HEIGHT = 48;

function normalizeValue(value: SelectHTMLAttributes<HTMLSelectElement>["value"]): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value == null ? "" : String(value);
}

function assignRef(ref: ForwardedRef<HTMLSelectElement>, node: HTMLSelectElement | null) {
  if (typeof ref === "function") {
    ref(node);
  } else if (ref) {
    ref.current = node;
  }
}

function selectedIndexFor(options: readonly SelectOption[], value: string): number {
  const selectedIndex = options.findIndex((option) => option.value === value);
  return selectedIndex >= 0 ? selectedIndex : options.length > 0 ? 0 : -1;
}

function setNativeSelectValue(select: HTMLSelectElement, value: string) {
  // Calling the prototype setter keeps React's value tracker on the previous
  // value, allowing the dispatched change event to retain the old onChange API.
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  if (valueSetter) {
    valueSetter.call(select, value);
  } else {
    select.value = value;
  }
}

/**
 * A single-select combobox with a project-styled listbox. The hidden native
 * select remains the form and event bridge, so existing callers can continue
 * to receive a real ChangeEvent<HTMLSelectElement> without page-by-page API migrations.
 */
const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(props, forwardedRef) {
  const {
    options,
    placeholder,
    invalid = false,
    className,
    value,
    defaultValue,
    onChange,
    onFocus,
    onBlur,
    onKeyDown,
    onClick,
    disabled = false,
    id,
    name,
    form,
    required,
    autoFocus,
    tabIndex,
    style,
    title,
    "aria-label": ariaLabel,
    "aria-labelledby": ariaLabelledBy,
    "aria-describedby": ariaDescribedBy,
    "aria-invalid": ariaInvalid,
    "aria-required": ariaRequired,
    ...nativeSelectProps
  } = props;
  const selectOptions = useMemo(
    () => (placeholder === undefined ? options : [{ value: "", label: placeholder }, ...options]),
    [options, placeholder],
  );
  const isControlled = value !== undefined;
  const initialValue = normalizeValue(
    defaultValue ?? (placeholder === undefined ? options[0]?.value : ""),
  );
  const [uncontrolledValue, setUncontrolledValue] = useState(initialValue);
  const selectedValue = isControlled ? normalizeValue(value) : uncontrolledValue;
  const selectedIndex = selectedIndexFor(selectOptions, selectedValue);
  const selectedOption = selectOptions[selectedIndex];
  const visibleLabel = selectedOption?.label ?? placeholder ?? "请选择";
  const [open, setOpen] = useState(false);
  const presence = usePresence(open);
  const [activeIndex, setActiveIndex] = useState(selectedIndex);
  const [popoverPosition, setPopoverPosition] = useState<PopoverPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const nativeSelectRef = useRef<HTMLSelectElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  // The listbox is portalled to body, so carry the nearest workbench variant
  // across the portal boundary for the shared light/dark token skin.
  const workbenchVariant = rootRef.current?.closest<HTMLElement>("[data-shell-variant]")?.dataset
    .shellVariant;

  const assignNativeSelectRef = useCallback(
    (node: HTMLSelectElement | null) => {
      nativeSelectRef.current = node;
      assignRef(forwardedRef, node);
    },
    [forwardedRef],
  );

  const updatePopoverPosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();
    const availableAbove = rect.top - VIEWPORT_GUTTER - POPUP_GAP;
    const availableBelow = window.innerHeight - rect.bottom - VIEWPORT_GUTTER - POPUP_GAP;
    const placement =
      availableBelow < IDEAL_LIST_HEIGHT && availableAbove > availableBelow ? "above" : "below";
    const availableHeight = placement === "above" ? availableAbove : availableBelow;
    const width = Math.min(rect.width, Math.max(0, window.innerWidth - 2 * VIEWPORT_GUTTER));
    const left = Math.max(
      VIEWPORT_GUTTER,
      Math.min(rect.left, window.innerWidth - width - VIEWPORT_GUTTER),
    );
    const maxHeight = Math.max(MIN_LIST_HEIGHT, Math.min(IDEAL_LIST_HEIGHT, availableHeight));

    setPopoverPosition({
      placement,
      style:
        placement === "above"
          ? {
              position: "fixed",
              left,
              bottom: window.innerHeight - rect.top + POPUP_GAP,
              width,
              maxHeight,
            }
          : {
              position: "fixed",
              left,
              top: rect.bottom + POPUP_GAP,
              width,
              maxHeight,
            },
    });
  }, []);

  const openListbox = useCallback(
    (nextActiveIndex?: number) => {
      if (disabled) return;
      setActiveIndex(nextActiveIndex ?? selectedIndexFor(selectOptions, selectedValue));
      setOpen(true);
    },
    [disabled, selectOptions, selectedValue],
  );

  const closeListbox = useCallback((returnFocus = false) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus({ preventScroll: true });
  }, []);

  const selectOption = useCallback(
    (nextValue: string) => {
      if (nextValue !== selectedValue) {
        if (!isControlled) setUncontrolledValue(nextValue);
        const nativeSelect = nativeSelectRef.current;
        if (nativeSelect) {
          setNativeSelectValue(nativeSelect, nextValue);
          nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      closeListbox(true);
    },
    [closeListbox, isControlled, selectedValue],
  );

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || listboxRef.current?.contains(target)) return;
      closeListbox();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [closeListbox, open]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePopoverPosition();
    window.addEventListener("resize", updatePopoverPosition);
    window.addEventListener("scroll", updatePopoverPosition, true);
    const resizeObserver =
      typeof ResizeObserver === "undefined" || !triggerRef.current
        ? null
        : new ResizeObserver(updatePopoverPosition);
    if (triggerRef.current) resizeObserver?.observe(triggerRef.current);
    return () => {
      window.removeEventListener("resize", updatePopoverPosition);
      window.removeEventListener("scroll", updatePopoverPosition, true);
      resizeObserver?.disconnect();
    };
  }, [open, updatePopoverPosition]);

  useEffect(() => {
    if (!presence.isPresent) setPopoverPosition(null);
  }, [presence.isPresent]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    const activeOption = listboxRef.current?.querySelector<HTMLElement>(
      `[data-select-option-index="${activeIndex}"]`,
    );
    activeOption?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, open]);

  const moveActiveOption = useCallback(
    (direction: -1 | 1) => {
      if (selectOptions.length === 0) return;
      setActiveIndex((currentIndex) => {
        const baseIndex =
          currentIndex >= 0 ? currentIndex : selectedIndexFor(selectOptions, selectedValue);
        return Math.max(0, Math.min(selectOptions.length - 1, baseIndex + direction));
      });
    },
    [selectOptions, selectedValue],
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    onKeyDown?.(event as unknown as KeyboardEvent<HTMLSelectElement>);
    if (event.defaultPrevented || disabled) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) openListbox();
      else moveActiveOption(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) openListbox();
      else moveActiveOption(-1);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const boundaryIndex = event.key === "Home" ? 0 : Math.max(0, selectOptions.length - 1);
      // Preserve the requested boundary when Home/End opens a closed listbox;
      // the usual open path intentionally begins at the selected value instead.
      if (!open) openListbox(boundaryIndex);
      else setActiveIndex(boundaryIndex);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        openListbox();
      } else if (activeIndex >= 0) {
        selectOption(selectOptions[activeIndex]?.value ?? selectedValue);
      }
      return;
    }
    if (event.key === "Escape" && open) {
      event.preventDefault();
      closeListbox(true);
      return;
    }
    if (event.key === "Tab" && open) closeListbox();
  };

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    onClick?.(event as unknown as MouseEvent<HTMLSelectElement>);
    if (event.defaultPrevented || disabled) return;
    if (open) closeListbox();
    else openListbox();
  };

  const rootClassName = [
    "select",
    invalid ? "select-error" : "",
    disabled ? "select-disabled" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  const activeOptionId = activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined;
  const portal =
    typeof document === "undefined" || !presence.isPresent || !popoverPosition
      ? null
      : createPortal(
          <div
            ref={listboxRef}
            id={listboxId}
            className="select-listbox"
            data-workbench-variant={
              workbenchVariant === "student-workbench" || workbenchVariant === "operations-workbench"
                ? workbenchVariant
                : undefined
            }
            data-motion-state={presence.motionState}
            data-placement={popoverPosition.placement}
            role="listbox"
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            style={popoverPosition.style}
          >
            {selectOptions.length === 0 ? (
              <div className="select-empty" role="status">
                暂无可选项
              </div>
            ) : (
              selectOptions.map((option, optionIndex) => {
                const selected = option.value === selectedValue;
                const active = optionIndex === activeIndex;
                return (
                  <button
                    key={option.value}
                    id={`${listboxId}-option-${optionIndex}`}
                    type="button"
                    role="option"
                    tabIndex={-1}
                    className="select-option"
                    data-active={active || undefined}
                    data-select-option-index={optionIndex}
                    aria-selected={selected}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => selectOption(option.value)}
                  >
                    <span className="select-option-label">{option.label}</span>
                    {selected ? (
                      <Check className="select-option-check" size={16} aria-hidden="true" />
                    ) : null}
                  </button>
                );
              })
            )}
          </div>,
          document.body,
        );

  return (
    <div className={rootClassName} ref={rootRef} style={style} title={title}>
      <select
        {...nativeSelectProps}
        ref={assignNativeSelectRef}
        className="select-native-proxy"
        aria-hidden="true"
        tabIndex={-1}
        value={isControlled ? selectedValue : undefined}
        defaultValue={isControlled ? undefined : initialValue}
        name={name}
        form={form}
        required={required}
        disabled={disabled}
        onChange={onChange}
      >
        {selectOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        id={id}
        ref={triggerRef}
        type="button"
        className="select-trigger"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open ? activeOptionId : undefined}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy}
        aria-invalid={invalid || ariaInvalid || undefined}
        aria-required={required || ariaRequired || undefined}
        disabled={disabled}
        autoFocus={autoFocus}
        tabIndex={tabIndex}
        onFocus={(event) => onFocus?.(event as unknown as FocusEvent<HTMLSelectElement>)}
        onBlur={(event) => onBlur?.(event as unknown as FocusEvent<HTMLSelectElement>)}
        onKeyDown={handleKeyDown}
        onClick={handleClick}
        title={visibleLabel}
      >
        <span className="select-value">{visibleLabel}</span>
        <ChevronDown className="select-chevron" size={16} aria-hidden="true" />
      </button>
      {portal}
    </div>
  );
});

export default Select;

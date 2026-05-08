"use client";

import {
  Children,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";

type CustomSelectProps = Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "children"
> & {
  children: ReactNode;
};

type OptionItem = {
  value: string;
  label: string;
  disabled: boolean;
};

function readNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map(readNodeText).join("");
  }

  if (isValidElement(node)) {
    const element = node as ReactElement<{ children?: ReactNode }>;
    return readNodeText(element.props.children);
  }

  return "";
}

function toStringValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? String(value[0]) : "";
  }

  if (value === undefined || value === null) {
    return "";
  }

  return String(value);
}

export default function CustomSelect({
  className = "",
  children,
  value,
  defaultValue,
  onChange,
  disabled,
  name,
  ...rest
}: CustomSelectProps) {
  const generatedId = useId();
  const fieldName = name ?? `custom_select_${generatedId}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
  }>({
    top: 0,
    left: 0,
    width: 0,
    maxHeight: 240,
  });

  const options = useMemo<OptionItem[]>(() => {
    return Children.toArray(children).flatMap((child) => {
      if (!isValidElement(child) || child.type !== "option") {
        return [];
      }

      const optionElement = child as ReactElement<{
        children?: ReactNode;
        value?: string | number;
        disabled?: boolean;
      }>;

      const optionLabel = readNodeText(optionElement.props.children);
      const optionValue =
        optionElement.props.value !== undefined
          ? String(optionElement.props.value)
          : optionLabel;

      return [
        {
          value: optionValue,
          label: optionLabel,
          disabled: Boolean(optionElement.props.disabled),
        },
      ];
    });
  }, [children]);

  const isControlled = value !== undefined;
  const firstEnabledValue = options.find((item) => !item.disabled)?.value ?? "";
  const initialValue =
    toStringValue(defaultValue) || toStringValue(value) || firstEnabledValue;
  const [internalValue, setInternalValue] = useState(initialValue);

  const rawSelectedValue = isControlled ? toStringValue(value) : internalValue;
  const hasSelectedValue = options.some(
    (item) => item.value === rawSelectedValue,
  );
  const selectedValue = hasSelectedValue ? rawSelectedValue : firstEnabledValue;

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      const targetNode = event.target as Node;
      const clickedTrigger = rootRef.current?.contains(targetNode);
      const clickedMenu = menuRef.current?.contains(targetNode);

      if (!clickedTrigger && !clickedMenu) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const selectedOption =
    options.find((item) => item.value === selectedValue) ?? options[0] ?? null;
  const isPlaceholderSelection =
    selectedOption !== null &&
    (selectedOption.disabled ||
      selectedOption.value.trim() === "" ||
      /^select\b/i.test(selectedOption.label.trim()) ||
      /^e\.g\./i.test(selectedOption.label.trim()));

  const updateDropdownDirection = useCallback(() => {
    const triggerRect = rootRef.current?.getBoundingClientRect();
    if (!triggerRect) {
      return;
    }

    const gap = 4;
    const edgePadding = 8;
    const optionRowHeight = 40;
    const menuVerticalPadding = 2;
    const estimatedMenuHeight = Math.min(
      260,
      options.length * optionRowHeight + menuVerticalPadding,
    );
    const spaceBelow = window.innerHeight - triggerRect.bottom;
    const spaceAbove = triggerRect.top;

    const shouldOpenUpward =
      spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow;

    if (shouldOpenUpward) {
      const maxHeight = Math.max(120, spaceAbove - gap - edgePadding);
      const menuHeight = Math.min(estimatedMenuHeight, maxHeight);

      setMenuStyle({
        top: Math.max(edgePadding, triggerRect.top - menuHeight - gap),
        left: triggerRect.left,
        width: triggerRect.width,
        maxHeight,
      });

      return;
    }

    const maxHeight = Math.max(120, spaceBelow - gap - edgePadding);

    setMenuStyle({
      top: triggerRect.bottom + gap,
      left: triggerRect.left,
      width: triggerRect.width,
      maxHeight,
    });
  }, [options.length]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handleViewportChange() {
      updateDropdownDirection();
    }

    window.addEventListener("resize", handleViewportChange);
    window.addEventListener("scroll", handleViewportChange, true);

    return () => {
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [isOpen, updateDropdownDirection]);

  function selectOption(nextValue: string) {
    if (!isControlled) {
      setInternalValue(nextValue);
    }

    setIsOpen(false);

    if (onChange) {
      const syntheticEvent = {
        target: {
          value: nextValue,
          name: fieldName,
        } as EventTarget & HTMLSelectElement,
        currentTarget: {
          value: nextValue,
          name: fieldName,
        } as EventTarget & HTMLSelectElement,
      } as ChangeEvent<HTMLSelectElement>;

      onChange(syntheticEvent);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <select
        {...rest}
        name={fieldName}
        value={selectedValue}
        disabled={disabled}
        onChange={(event) => {
          selectOption(event.target.value);
        }}
        className="sr-only"
        aria-hidden
        tabIndex={-1}
      >
        {options.map((option) => (
          <option
            key={`${option.value}-${option.label}`}
            value={option.value}
            disabled={option.disabled}
          >
            {option.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          if (!isOpen) {
            updateDropdownDirection();
          }

          setIsOpen((prev) => !prev);
        }}
        className={`${className} flex items-center justify-between gap-3 text-left transition-colors ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
      >
        <span
          className={`truncate ${isPlaceholderSelection ? "text-text-secondary" : ""}`}
        >
          {selectedOption?.label ?? "Select option"}
        </span>

        <span
          aria-hidden
          className={`shrink-0 text-text-secondary transition-transform ${isOpen ? "rotate-180" : "rotate-0"}`}
        >
          <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4">
            <path
              d="M5 7.5L10 12.5L15 7.5"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>

      {isOpen && !disabled
        ? typeof document !== "undefined"
          ? createPortal(
              <div
                ref={menuRef}
                className="fixed z-1000 overflow-hidden rounded-xs border border-border-10 bg-surface shadow-[0_12px_24px_rgba(4,2,115,0.14)]"
                style={{
                  top: menuStyle.top,
                  left: menuStyle.left,
                  width: menuStyle.width,
                }}
              >
                <ul
                  style={{ maxHeight: menuStyle.maxHeight }}
                  className="overflow-y-auto"
                >
                  {options.map((option) => {
                    const isSelected = option.value === selectedValue;

                    return (
                      <li key={`${option.value}-${option.label}`}>
                        <button
                          type="button"
                          disabled={option.disabled}
                          onClick={() => selectOption(option.value)}
                          className={`w-full px-4 py-2 text-left text-base transition-colors ${isSelected ? "bg-background-blue text-white" : "text-text-primary hover:bg-background-5"} ${option.disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
                        >
                          {option.label}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>,
              document.body,
            )
          : null
        : null}
    </div>
  );
}

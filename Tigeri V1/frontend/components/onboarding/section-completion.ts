export function isSectionComplete(container: HTMLElement | null): boolean {
  if (!container) {
    return false;
  }

  const fields = Array.from(
    container.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
      "input, select, textarea",
    ),
  ).filter((field) => {
    if (field.dataset.optional === "true") {
      return false;
    }

    if (field.disabled) {
      return false;
    }

    if (
      field instanceof HTMLInputElement &&
      ["hidden", "button", "submit", "reset"].includes(field.type)
    ) {
      return false;
    }

    return true;
  });

  if (!fields.length) {
    return true;
  }

  const textLikeComplete = fields
    .filter(
      (field) =>
        !(field instanceof HTMLInputElement) ||
        !["checkbox", "radio"].includes(field.type),
    )
    .every((field) => {
      if (field instanceof HTMLSelectElement) {
        const selectedText =
          field.options[field.selectedIndex]?.textContent?.trim().toLowerCase() ?? "";
        if (!field.value.trim()) {
          return false;
        }
        if (selectedText.startsWith("select")) {
          return false;
        }
        return true;
      }

      return field.value.trim().length > 0;
    });

  const radios = fields.filter(
    (field): field is HTMLInputElement =>
      field instanceof HTMLInputElement && field.type === "radio" && field.required,
  );

  const radioGroups = new Map<string, HTMLInputElement[]>();
  radios.forEach((radio, index) => {
    const key = radio.name || `__radio_group_${index}`;
    const current = radioGroups.get(key) ?? [];
    current.push(radio);
    radioGroups.set(key, current);
  });

  const radiosComplete = Array.from(radioGroups.values()).every((group) =>
    group.some((radio) => radio.checked),
  );

  const checkboxes = fields.filter(
    (field): field is HTMLInputElement =>
      field instanceof HTMLInputElement && field.type === "checkbox" && field.required,
  );

  const checkboxesComplete =
    checkboxes.length === 0 || checkboxes.some((checkbox) => checkbox.checked);

  return textLikeComplete && radiosComplete && checkboxesComplete;
}

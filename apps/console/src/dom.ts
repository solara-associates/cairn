/** Minimal templating helper: build a container's contents from an HTML
 * string, then let the caller hang behaviour off `data-action` attributes
 * via a single delegated listener -- no framework, per R0-15's existing
 * console conventions (plain Vite + TypeScript, no UI framework). */
export function setHtml(container: HTMLElement, html: string): void {
  container.innerHTML = html;
}

export function onClick(
  container: HTMLElement,
  action: string,
  handler: (event: MouseEvent, target: HTMLElement) => void,
): void {
  container.addEventListener("click", (event) => {
    const target = (event.target as HTMLElement).closest<HTMLElement>(
      `[data-action="${action}"]`,
    );
    if (target && container.contains(target)) {
      handler(event, target);
    }
  });
}

export function onSubmit(
  container: HTMLElement,
  formAction: string,
  handler: (event: SubmitEvent, form: HTMLFormElement) => void,
): void {
  container.addEventListener("submit", (event) => {
    const form = event.target as HTMLFormElement;
    if (form.dataset.action === formAction) {
      event.preventDefault();
      handler(event, form);
    }
  });
}

export function formValue(form: HTMLFormElement, name: string): string {
  return (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | null)
    ?.value ?? "";
}

export function showError(container: HTMLElement, message: string): void {
  const slot = container.querySelector<HTMLElement>("[data-slot='error']");
  if (slot) {
    slot.textContent = message;
    slot.hidden = false;
  }
}

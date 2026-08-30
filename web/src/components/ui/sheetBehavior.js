export const FOCUSABLE_SELECTOR = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

export function getFocusableElements(root, selector = FOCUSABLE_SELECTOR) {
  return [...(root?.querySelectorAll(selector) || [])].filter(element =>
    element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true',
  )
}

/** Return the element that should receive focus for a Tab key event. */
export function focusTarget(focusable, current, container, shiftKey) {
  if (!focusable.length) return null
  const first = focusable[0]
  const last = focusable.at(-1)
  const outside = current === container || !container?.contains(current)
  if (shiftKey && (outside || current === first)) return last
  if (!shiftKey && (outside || current === last)) return first
  return null
}

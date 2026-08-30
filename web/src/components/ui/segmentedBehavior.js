export function selectedIndex(options, modelValue) { const index = options.findIndex(option => option.value === modelValue); return index >= 0 ? index : 0 }
export function keyboardIndex(options, current, key) { if (!options.length) return null; const last = options.length - 1; if (key === 'Home') return 0; if (key === 'End') return last; if (key === 'ArrowDown' || key === 'ArrowRight') return current >= last ? 0 : current + 1; if (key === 'ArrowUp' || key === 'ArrowLeft') return current <= 0 ? last : current - 1; return null }
export function rovingTabindex(options, modelValue) { const index = selectedIndex(options, modelValue); return options.map((_, optionIndex) => optionIndex === index ? 0 : -1) }
export function selectionIntent(options, index) { return options[index]?.value ?? null }

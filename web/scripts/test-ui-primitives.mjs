import assert from 'node:assert/strict'
import { keyboardIndex, rovingTabindex, selectedIndex, selectionIntent } from '../src/components/ui/segmentedBehavior.js'
import { applyInert, chooseInitialFocus, closeLifecycle, focusTarget, inertSnapshot, isFocusableCandidate, restoreInert } from '../src/components/ui/sheetBehavior.js'
const options = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }, { value: 'c', label: 'C' }]
assert.equal(selectedIndex(options, 'b'), 1); assert.equal(selectedIndex(options, 'x'), 0)
assert.deepEqual(rovingTabindex(options, 'b'), [-1, 0, -1]); assert.equal(selectionIntent(options, 2), 'c')
assert.equal(keyboardIndex(options, 1, 'ArrowDown'), 2); assert.equal(keyboardIndex(options, 2, 'ArrowRight'), 0); assert.equal(keyboardIndex(options, 0, 'ArrowUp'), 2); assert.equal(keyboardIndex(options, 2, 'ArrowLeft'), 1); assert.equal(keyboardIndex(options, 1, 'Home'), 0); assert.equal(keyboardIndex(options, 0, 'End'), 2); assert.equal(keyboardIndex(options, 1, 'PageDown'), null)
const mk = ({ hidden = false, disabled = false } = {}) => ({ disabled, hidden, inert: false, isConnected: true, getAttribute: key => key === 'aria-hidden' && hidden ? 'true' : null, getClientRects: () => hidden ? [] : [{}], focus() { this.focused = true } })
const sheet = { contains: node => node?.inside === true }; const first = mk(); first.inside = true; const last = mk(); last.inside = true; const outside = mk();
assert.equal(isFocusableCandidate(mk({ hidden: true })), false); assert.equal(chooseInitialFocus(mk({ disabled: true }), [first], sheet), first); assert.equal(focusTarget([first, last], outside, sheet, false), first); assert.equal(focusTarget([first, last], first, sheet, true), last)
const body = { style: { overflow: 'scroll' } }; const bg = { inert: false, contains: () => false }; const layer = {}; const snap = inertSnapshot([bg, layer], layer, body.style.overflow); applyInert(snap); assert.equal(bg.inert, true); restoreInert(snap, body); assert.equal(bg.inert, false); assert.equal(body.style.overflow, 'scroll')
assert.equal(closeLifecycle(false, false), false); assert.equal(closeLifecycle(false, true), true); assert.equal(closeLifecycle(true, false), true); assert.equal(closeLifecycle(true, false, 'after-leave'), true); assert.equal(closeLifecycle(false, false, 'after-leave'), false)
console.log('ui primitive focus, keyboard, lifecycle behavior passed')

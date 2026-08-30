import assert from 'node:assert/strict'
import { focusTarget } from '../src/components/ui/sheetBehavior.js'

const make = name => ({ name, contains: node => node?.container === name, focus() { this.focused = true } })
const container = { contains: node => node?.container === true }
const first = make('first'); first.container = true
const last = make('last'); last.container = true
const outside = make('outside')
assert.equal(focusTarget([first, last], outside, container, false), first)
assert.equal(focusTarget([first, last], first, container, true), last)
assert.equal(focusTarget([first, last], last, container, false), first)
assert.equal(focusTarget([first, last], first, container, false), null)
assert.equal(focusTarget([], outside, container, false), null)
console.log('ui primitive focus behavior passed')

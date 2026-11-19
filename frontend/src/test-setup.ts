import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { clearPreviewSession } from './lib/previewSession'

afterEach(() => {
  cleanup()
  clearPreviewSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

// jsdom does not implement the native dialog API; real focus/inert behavior is covered by Playwright.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute('open')
}

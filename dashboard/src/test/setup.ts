import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library only cleans up by itself when vitest globals are on.
afterEach(cleanup)
// What the viewer chose (collapsed sections, the timeline's size) starts fresh each test.
afterEach(() => localStorage.clear())

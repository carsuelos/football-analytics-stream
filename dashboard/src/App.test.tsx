import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import App from './App'

it('renders the layout', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Live Football Analytics' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Charts' })).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: 'Alerts' })).toBeInTheDocument()
})

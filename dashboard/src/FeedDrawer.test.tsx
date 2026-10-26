import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { FeedDrawer } from './FeedDrawer'

it('opens the feed over everything, and closes with ×, Escape or a click outside', async () => {
  render(
    <FeedDrawer count={3}>
      <p>the feed</p>
    </FeedDrawer>,
  )
  const button = screen.getByRole('button', { name: 'Match feed 3' })
  expect(screen.queryByText('the feed')).toBeNull()
  await userEvent.click(button)
  expect(screen.getByRole('dialog', { name: 'Match feed panel' })).toHaveTextContent('the feed')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  await userEvent.click(button)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
})

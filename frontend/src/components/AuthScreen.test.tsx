import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../lib/api'
import { AuthScreen } from './AuthScreen'

describe('blocked sign-in recovery', () => {
  it('stays on the form and offers a new-tab action instead of looping through the dashboard', async () => {
    const user = userEvent.setup()
    const authenticated = vi.fn()
    vi.spyOn(api, 'authenticate').mockRejectedValue(
      new ApiError('This browser blocked the sign-in session.', 401, 'SESSION_NOT_ESTABLISHED'),
    )
    render(<AuthScreen onAuthenticated={authenticated} />)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await user.type(screen.getByLabelText('Work email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Password'), 'a-long-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('browser blocked')
    expect(screen.getByRole('link', { name: /Open preview in a new tab/ })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(authenticated).not.toHaveBeenCalled()
  })
})

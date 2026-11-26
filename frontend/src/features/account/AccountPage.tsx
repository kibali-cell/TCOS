import { useState } from 'react'

import { useAuth, useCurrentUser } from '../auth/useAuth'
import { formatDateTime } from '../../lib/format'
import { ChangePasswordForm } from './ChangePasswordForm'
import { SessionsPanel } from './SessionsPanel'
import { TwoFactorPanel } from './TwoFactorPanel'

export function AccountPage() {
  const user = useCurrentUser()
  const { state, refresh } = useAuth()
  const [reloadKey, setReloadKey] = useState(0)
  const session = state.status === 'signed-in' ? state.session : null
  const roles = state.status === 'signed-in' ? state.roles : []

  return (
    <>
      <h1>My account</h1>

      <section className="card" aria-labelledby="profile-heading">
        <h2 id="profile-heading">Profile</h2>
        <dl className="details">
          <dt>Name</dt>
          <dd>{user.full_name}</dd>
          <dt>Username</dt>
          <dd>{user.username}</dd>
          <dt>Email</dt>
          <dd>{user.email}</dd>
          {user.phone && (
            <>
              <dt>Phone</dt>
              <dd>{user.phone}</dd>
            </>
          )}
          <dt>Roles</dt>
          <dd>
            {roles.length === 0
              ? 'None yet. Ask an administrator.'
              : roles
                  .map((role) =>
                    role.department ? `${role.name} (${role.department})` : role.name,
                  )
                  .join(', ')}
          </dd>
          <dt>Last sign-in</dt>
          <dd>{formatDateTime(user.last_login)}</dd>
          <dt>Session ends no later than</dt>
          <dd>{formatDateTime(session?.absolute_expires_at)}</dd>
        </dl>
        <p className="muted small">To change your name or email, ask an administrator.</p>
      </section>

      <ChangePasswordForm
        forced={user.must_change_password}
        onChanged={() => {
          void refresh()
          setReloadKey((value) => value + 1)
        }}
      />
      <TwoFactorPanel />
      <SessionsPanel reloadKey={reloadKey} />
    </>
  )
}

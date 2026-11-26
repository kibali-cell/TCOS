import { Route, Routes } from 'react-router-dom'

import { AccountPage } from '../features/account/AccountPage'
import { AuditLogPage } from '../features/audit/AuditLogPage'
import { LoginPage } from '../features/auth/LoginPage'
import { RequireAuth } from '../features/auth/RequireAuth'
import { RequirePermission } from '../features/auth/RequirePermission'
import { RolesPage } from '../features/roles/RolesPage'
import { Layout } from './Layout'
import { DashboardPage, ModulePlaceholderPage, NotFoundPage } from './pages'

export function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route element={<RequirePermission module="users" action="VIEW" />}>
            <Route path="administration/roles" element={<RolesPage />} />
          </Route>
          <Route element={<RequirePermission module="audit" action="VIEW" />}>
            <Route path="administration/audit" element={<AuditLogPage />} />
          </Route>
          <Route path="modules/:slug" element={<ModulePlaceholderPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}

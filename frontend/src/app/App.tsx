import { Route, Routes } from 'react-router-dom'

import { AccountPage } from '../features/account/AccountPage'
import { OrganisationPage } from '../features/organisation/OrganisationPage'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { DepartmentDashboardPage } from '../features/dashboard/DepartmentDashboardPage'
import { UserDetailPage } from '../features/users/UserDetailPage'
import { UsersPage } from '../features/users/UsersPage'
import { AccessReviewPage } from '../features/approvals/AccessReviewPage'
import { ApprovalsPage } from '../features/approvals/ApprovalsPage'
import { LimitsPage } from '../features/approvals/LimitsPage'
import { NewRequestPage } from '../features/approvals/NewRequestPage'
import { RequestDetailPage } from '../features/approvals/RequestDetailPage'
import { RoleGrantPage } from '../features/approvals/RoleGrantPage'
import { AuditLogPage } from '../features/audit/AuditLogPage'
import { LoginPage } from '../features/auth/LoginPage'
import { RequireAuth } from '../features/auth/RequireAuth'
import { RequirePermission } from '../features/auth/RequirePermission'
import { RolesPage } from '../features/roles/RolesPage'
import { Layout } from './Layout'
import { ModulePlaceholderPage, NotFoundPage } from './pages'

export function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="account" element={<AccountPage />} />
          <Route path="departments/:id/dashboard" element={<DepartmentDashboardPage />} />
          <Route element={<RequirePermission module="users" action="VIEW" />}>
            <Route path="administration/roles" element={<RolesPage />} />
            <Route path="administration/users" element={<UsersPage />} />
            <Route path="administration/users/:id" element={<UserDetailPage />} />
          </Route>
          <Route element={<RequirePermission module="administration" action="VIEW" />}>
            <Route path="administration/organisation" element={<OrganisationPage />} />
          </Route>
          <Route element={<RequirePermission module="audit" action="VIEW" />}>
            <Route path="administration/audit" element={<AuditLogPage />} />
            <Route path="administration/access-review" element={<AccessReviewPage />} />
          </Route>
          <Route element={<RequirePermission module="approvals" action="VIEW" />}>
            <Route path="approvals" element={<ApprovalsPage />} />
            <Route path="approvals/limits" element={<LimitsPage />} />
            <Route path="approvals/:id" element={<RequestDetailPage />} />
          </Route>
          <Route element={<RequirePermission module="approvals" action="CREATE" />}>
            <Route path="approvals/new" element={<NewRequestPage />} />
          </Route>
          <Route element={<RequirePermission module="users" action="MANAGE_USERS" />}>
            <Route path="approvals/role-grant" element={<RoleGrantPage />} />
          </Route>
          <Route path="modules/:slug" element={<ModulePlaceholderPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}

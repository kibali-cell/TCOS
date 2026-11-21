import { Route, Routes } from 'react-router-dom'

import { Layout } from './Layout'
import { DashboardPage, ModulePlaceholderPage, NotFoundPage } from './pages'

// Login and protected routes arrive in Slice 1.
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="modules/:slug" element={<ModulePlaceholderPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

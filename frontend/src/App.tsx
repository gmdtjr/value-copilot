import { Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ThesisPage from './pages/Thesis'
import ReportsPage from './pages/Reports'
import JournalPage from './pages/Journal'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/tickers/:id/thesis" element={<ThesisPage />} />
      <Route path="/reports" element={<ReportsPage />} />
      <Route path="/journal" element={<JournalPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

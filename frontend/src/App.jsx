import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { isAuthenticated, getUser, pb } from './lib/pocketbase'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Project from './pages/Project'
import './App.css'

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (isAuthenticated()) {
      const u = getUser()
      if (u) {
        setUser(u)
        pb.authStore.save(pb.authStore.token, u)
      }
    }
    setChecking(false)
  }, [])

  const handleLogin = (record, token) => {
    pb.authStore.save(token, record)
    setUser(record)
  }

  const handleLogout = () => {
    pb.authStore.clear()
    setUser(null)
  }

  if (checking) return null

  return (
    <BrowserRouter>
      <Routes>
        {/* Home / Dashboard — público */}
        <Route
          path="/"
          element={<Dashboard user={user} onLogout={handleLogout} onLogin={handleLogin} />}
        />
        {/* Login */}
        <Route
          path="/login"
          element={user ? <Navigate to="/" /> : <Login onLogin={handleLogin} />}
        />
        {/* Legacy redirect */}
        <Route
          path="/dashboard"
          element={<Navigate to="/" />}
        />
        {/* Project slug — público */}
        <Route
          path="/p/:slug"
          element={<Project user={user} />}
        />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { isAuthenticated, getUser, pb, saveToken } from './lib/pocketbase'
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
        // PocketBase SDK auto-manages token refresh, just set it
        pb.authStore.save(pb.authStore.token, u)
      }
    }
    setChecking(false)
  }, [])

  const handleLogin = (record, token) => {
    saveToken(token)
    pb.authStore.save(token, record)
    setUser(record)
  }

  const handleLogout = () => {
    pb.authStore.clear()
    localStorage.removeItem('pb_token')
    setUser(null)
  }

  if (checking) return null

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={user ? <Navigate to="/dashboard" /> : <Login onLogin={handleLogin} />}
        />
        <Route
          path="/login"
          element={<Navigate to="/" />}
        />
        <Route
          path="/dashboard"
          element={user ? <Dashboard user={user} onLogout={handleLogout} /> : <Navigate to="/" />}
        />
        <Route
          path="/p/:slug"
          element={user ? <Project user={user} /> : <Navigate to="/" />}
        />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}
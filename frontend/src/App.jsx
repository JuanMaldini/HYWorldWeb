import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { isAuthenticated, getUser, pb } from './lib/pocketbase'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Viewer from './pages/Viewer'
import './App.css'

export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    if (isAuthenticated()) {
      setUser(getUser())
    }
    setChecking(false)
  }, [])

  const handleLogin = (record, token) => {
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
        <Route
          path="/login"
          element={user ? <Navigate to="/dashboard" /> : <Login onLogin={handleLogin} />}
        />
        <Route
          path="/dashboard"
          element={user ? <Dashboard user={user} onLogout={handleLogout} /> : <Navigate to="/login" />}
        />
        <Route
          path="/project/:pid"
          element={user ? <Viewer /> : <Navigate to="/login" />}
        />
        <Route path="/" element={<Navigate to={user ? '/dashboard' : '/login'} />} />
      </Routes>
    </BrowserRouter>
  )
}
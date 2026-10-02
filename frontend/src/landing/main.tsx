import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './Landing.css'
import App from './App'

createRoot(document.getElementById('landing-root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

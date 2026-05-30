import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { initApiBase } from '@/lib/api'
import { App } from './App'
import './index.css'

initApiBase().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
})

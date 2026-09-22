import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { setupAxiosInterceptors } from './utils/axiosInterceptor'
import './index.css'
import App from './App.jsx'
import { I18nProvider } from './i18n/index.jsx'

// Guarantee interceptors are configured before any React component mounts
setupAxiosInterceptors();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
)

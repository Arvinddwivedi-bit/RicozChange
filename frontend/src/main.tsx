/**
 * Optional Clerk authentication layer.
 *
 * Demo mode (default, VITE_CLERK_PUBLISHABLE_KEY empty):
 *   The app renders exactly as before — no Clerk, no sign-in screen, no
 *   network change. The public demo and CI stay independent of any Clerk app.
 *
 * Clerk mode (key set):
 *   The SPA is wrapped in ClerkProvider; without a session the visitor sees
 *   Clerk's prebuilt <SignIn />, and once signed in every /api call carries a
 *   Bearer session token (AuthBridge below → api.ts → backend JWKS check).
 */
import { ClerkProvider, SignIn, useAuth } from '@clerk/react'
import { StrictMode, useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@xyflow/react/dist/style.css'
import './index.css'
import App from './App'

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined
const CLERK_ENABLED = Boolean(CLERK_KEY && CLERK_KEY.startsWith('pk_'))

declare global {
  interface Window {
    __RC_AUTH__?: { getToken: (() => Promise<string | null>) | null }
  }
}
window.__RC_AUTH__ = { getToken: null }

/** Lives inside ClerkProvider; publishes a token getter for api.ts. */
function AuthBridge() {
  const { getToken, isSignedIn, isLoaded } = useAuth()
  useEffect(() => {
    if (isLoaded) {
      window.__RC_AUTH__ = { getToken: isSignedIn ? getToken : () => Promise.resolve(null) }
    }
  }, [getToken, isSignedIn, isLoaded])
  return null
}

/** What a signed-out visitor sees instead of the app. */
function AppGate({ children }: { children: ReactNode }) {
  const { isSignedIn, isLoaded } = useAuth()
  if (!isLoaded) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">Loading…</div>
  }
  if (!isSignedIn) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8 bg-slate-50">
        <div className="w-full max-w-md">
          <div className="text-center mb-6">
            <div className="font-extrabold tracking-tight text-2xl mb-1">RicozChange</div>
            <div className="text-sm text-slate-500">AI-native change management</div>
          </div>
          <SignIn />
        </div>
      </div>
    )
  }
  return <>{children}</>
}

function Root() {
  const children = (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  )
  if (!CLERK_ENABLED) {
    return <StrictMode>{children}</StrictMode>
  }
  return (
    <StrictMode>
      <ClerkProvider publishableKey={CLERK_KEY!}>
        <AuthBridge />
        <AppGate>{children}</AppGate>
      </ClerkProvider>
    </StrictMode>
  )
}

createRoot(document.getElementById('root')!).render(<Root />)

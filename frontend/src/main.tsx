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
import { ClerkProvider, SignIn, SignUp, useAuth } from '@clerk/react'
import { StrictMode, useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@xyflow/react/dist/style.css'
import './index.css'
import App, { BrandMark } from './App'

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
  const [isSignUp, setIsSignUp] = useState(false)

  if (!isLoaded) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50">
        <BrandMark />
        <div className="mt-8 flex items-center gap-2 text-slate-500">
          <span className="spinner w-5 h-5" style={{ color: 'var(--color-navy)' }} />
          <span className="text-sm font-medium">Loading workspace...</span>
        </div>
      </div>
    )
  }

  if (!isSignedIn) {
    return (
      <div className="min-h-screen flex bg-white">
        {/* Left Panel */}
        <div className="hidden lg:flex w-1/2 flex-col justify-between p-12 bg-gradient-to-br from-[#0f1d33] to-[#070e1a] text-white">
          <div>
            <div className="flex items-center gap-3 text-white mb-16">
              <span className="flex items-center justify-center w-8 h-8 rounded bg-[#d4222c] font-bold text-white text-sm">rZ</span>
              <span className="font-extrabold tracking-tight text-xl">RicozChange</span>
            </div>
            <h1 className="text-4xl font-bold tracking-tight mb-6 leading-tight">
              AI-native change<br />management for modern teams
            </h1>
            <p className="text-slate-300 text-lg mb-12 max-w-md">
              Streamline deployments, understand blast radius, and govern changes with confidence.
            </p>
            
            <ul className="space-y-6 text-slate-300">
              <li className="flex items-start gap-3">
                <div className="mt-1 w-5 h-5 rounded-full bg-[#d4222c]/20 flex items-center justify-center text-[#d4222c] shrink-0">✓</div>
                <span>Automated blast radius detection and risk scoring</span>
              </li>
              <li className="flex items-start gap-3">
                <div className="mt-1 w-5 h-5 rounded-full bg-[#d4222c]/20 flex items-center justify-center text-[#d4222c] shrink-0">✓</div>
                <span>Intelligent simulation of configuration changes</span>
              </li>
              <li className="flex items-start gap-3">
                <div className="mt-1 w-5 h-5 rounded-full bg-[#d4222c]/20 flex items-center justify-center text-[#d4222c] shrink-0">✓</div>
                <span>Automated CAB meetings and deep integration with Jira/GitHub</span>
              </li>
            </ul>
          </div>
          <div className="text-slate-400 text-sm">
            © {new Date().getFullYear()} RicozChange. All rights reserved.
          </div>
        </div>
        
        {/* Right Panel */}
        <div className="w-full lg:w-1/2 flex flex-col items-center justify-center p-8 bg-slate-50 lg:bg-white">
          <div className="w-full max-w-[440px]">
            <div className="lg:hidden flex justify-center mb-8">
              <BrandMark />
            </div>
            
            <div className="bg-white lg:bg-transparent rounded-2xl shadow-sm lg:shadow-none p-6 lg:p-0 border border-slate-200 lg:border-none">
              {isSignUp ? (
                <SignUp />
              ) : (
                <SignIn />
              )}
              
              <div className="mt-6 text-center text-sm text-slate-500">
                {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
                <button 
                  onClick={() => setIsSignUp(!isSignUp)}
                  className="text-brand-600 hover:text-brand-700 font-semibold"
                >
                  {isSignUp ? 'Sign in' : 'Sign up'}
                </button>
              </div>
            </div>
          </div>
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

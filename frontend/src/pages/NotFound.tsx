import { Link } from 'react-router-dom'
import { Home, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center p-8 text-center">
      <div className="text-[6rem] font-bold text-slate-200 leading-none">404</div>
      <h1 className="mt-6 text-2xl font-bold text-slate-900">Page not found</h1>
      <p className="mt-2 text-slate-500 max-w-sm mx-auto">
        Sorry, we couldn't find the page you're looking for. It might have been moved or doesn't exist.
      </p>
      <div className="mt-8 flex items-center justify-center gap-3 flex-wrap">
        <button onClick={() => window.history.back()} className="btn btn-ghost">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Go Back
        </button>
        <Link to="/" className="btn btn-primary">
          <Home className="w-4 h-4 mr-2" />
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}

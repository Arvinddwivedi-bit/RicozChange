import { useEffect, useState } from 'react'
import { api } from '../api'
import { Loader2 } from 'lucide-react'
import clsx from 'clsx'

interface Lead {
  id: string
  name: string
  email: string
  company: string
  city: string
  message: string
  status: 'new' | 'contacted' | 'closed'
  created_at: string
}

interface LeadsPageState {
  items: Lead[]
  statusFilter: 'new' | 'contacted' | 'closed' | 'all'
  loading: boolean
  error: string | null
  deleting: boolean
}

export default function Leads() {
  const [state, setState] = useState<LeadsPageState>({
    items: [],
    statusFilter: 'all',
    loading: true,
    error: null,
    deleting: false,
  })

  const { items, statusFilter, loading, error } = state

  useEffect(() => {
    async function loadLeads() {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const r = await api<{ items: Lead[] }>('/api/leads')
        setState((s) => ({
          ...s,
          items: r.items,
          loading: false,
        }))
      } catch (e: any) {
        setState((s) => ({ ...s, error: e.message, loading: false }))
      }
    }

    loadLeads()
  }, [])

  const handleChangeStatus = async (leadId: string, newStatus: 'new' | 'contacted' | 'closed') => {
    setState((s) => ({ ...s, deleting: true }))
    try {
      await api<{ ok: boolean }>(`/api/leads/${leadId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      setState((s) => ({
        ...s,
        items: s.items.map((i) =>
          i.id === leadId ? { ...i, status: newStatus } : i
        ),
        deleting: false,
      }))
    } catch (e: any) {
      setState((s) => ({ ...s, error: e.message, deleting: false }))
    }
  }

  if (loading) {
    return (
      <div className="p-8">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
          <span className="ml-2 text-slate-500">Loading leads...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-md">
          <p className="font-medium text-red-600">{error}</p>
        </div>
      </div>
    )
  }

  // Filter items by status
  const filteredItems = statusFilter === 'all'
    ? items
    : items.filter((i) => i.status === statusFilter)

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Leads Inbox</h1>
          <p className="text-slate-500 mt-1">Franchise partner inquiries</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={state.statusFilter}
            onChange={(e) => setState((s) => ({ ...s, statusFilter: e.target.value as any }))}
            className="rounded-md border border-slate-300 p-2 text-sm"
          >
            <option value="all">All</option>
            <option value="new">New</option>
            <option value="contacted">Contacted</option>
            <option value="closed">Closed</option>
          </select>
        </div>
      </div>

      {filteredItems.length === 0 && (
        <div className="p-6 text-slate-500 text-center">
          No leads found.
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full">
          <thead>
            <tr className="bg-slate-50 border-b">
              <th className="p-3 text-left text-xs font-medium text-slate-500">Name</th>
              <th className="p-3 text-left text-xs font-medium text-slate-500">Email</th>
              <th className="p-3 text-left text-xs font-medium text-slate-500">Company</th>
              <th className="p-3 text-left text-xs font-medium text-slate-500">City</th>
              <th className="p-3 text-left text-xs font-medium text-slate-500">Status</th>
              <th className="p-3 text-left text-xs font-medium text-slate-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredItems.length === 0 && (
              <tr>
                <td className="p-6 text-center text-slate-500" colSpan={6}>
                  No leads found
                </td>
              </tr>
            )}
            {filteredItems.map((lead) => (
              <tr key={lead.id} className="hover:bg-slate-50 border-b border-slate-100">
                <td className="p-3 font-medium text-slate-800">{lead.name}</td>
                <td className="p-3 text-slate-600">{lead.email}</td>
                <td className="p-3 text-slate-600">{lead.company}</td>
                <td className="p-3 text-slate-600">{lead.city || '-'}</td>
                <td className="p-3">
                  <span className={clsx(
                    'px-2 py-0.5 text-[10px] font-medium rounded',
                    lead.status === 'new' ? 'bg-emerald-100 text-emerald-700' :
                    lead.status === 'contacted' ? 'bg-amber-100 text-amber-700' :
                    'bg-rose-100 text-rose-700'
                  )}>{lead.status}</span>
                </td>
                <td className="p-3">
                  <select
                    value={lead.status}
                    onChange={(e) => handleChangeStatus(lead.id, e.target.value as any)}
                    className="w-24 rounded-md border border-slate-300 p-1 text-[10px]"
                  >
                    <option value="new">New</option>
                    <option value="contacted">Contacted</option>
                    <option value="closed">Closed</option>
                  </select>
                  <button
                    onClick={() => handleChangeStatus(lead.id, 'closed')}
                    className="ml-2 text-[11px] text-red-600 hover:underline"
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
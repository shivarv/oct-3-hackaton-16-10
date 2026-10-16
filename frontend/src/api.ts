// Empty base = same origin; Vite dev server proxies /api to the backend.
const BASE = import.meta.env.VITE_API_URL ?? ''

export interface Listing {
  id: number
  title: string
  description: string | null
  address: string
  city: string
  price: string
  bedrooms: number
  bathrooms: number
  created_at: string
}

export type ListingInput = Omit<Listing, 'id' | 'created_at'>

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  health: () => request<{ status: string; db: string }>('/api/health'),
  listListings: () => request<Listing[]>('/api/listings'),
  createListing: (data: ListingInput) =>
    request<Listing>('/api/listings', { method: 'POST', body: JSON.stringify(data) }),
  deleteListing: (id: number) => request<void>(`/api/listings/${id}`, { method: 'DELETE' }),
}

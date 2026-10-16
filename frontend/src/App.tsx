import { useEffect, useState, type FormEvent } from 'react'
import { api, type Listing, type ListingInput } from './api'
import './App.css'

const emptyForm: ListingInput = {
  title: '',
  description: '',
  address: '',
  city: '',
  price: '',
  bedrooms: 1,
  bathrooms: 1,
}

function App() {
  const [listings, setListings] = useState<Listing[]>([])
  const [form, setForm] = useState<ListingInput>(emptyForm)
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    api.listListings().then(setListings).catch((e: Error) => setError(e.message))

  useEffect(() => {
    load()
  }, [])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.createListing(form)
      setForm(emptyForm)
      setError(null)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const onDelete = async (id: number) => {
    await api.deleteListing(id)
    load()
  }

  const field = (key: keyof ListingInput, type = 'text') => (
    <input
      type={type}
      placeholder={key}
      value={form[key] ?? ''}
      required={key !== 'description'}
      onChange={(e) =>
        setForm({ ...form, [key]: type === 'number' ? Number(e.target.value) : e.target.value })
      }
    />
  )

  return (
    <main className="container">
      <h1>Housing Listings</h1>
      {error && <p className="error">Error: {error}</p>}

      <form onSubmit={onSubmit} className="form">
        {field('title')}
        {field('address')}
        {field('city')}
        {field('price')}
        {field('bedrooms', 'number')}
        {field('bathrooms', 'number')}
        {field('description')}
        <button type="submit">Add listing</button>
      </form>

      <ul className="listings">
        {listings.map((l) => (
          <li key={l.id}>
            <strong>{l.title}</strong> — {l.city} · ${l.price} · {l.bedrooms}bd/{l.bathrooms}ba
            <button onClick={() => onDelete(l.id)}>Delete</button>
          </li>
        ))}
        {listings.length === 0 && <li>No listings yet.</li>}
      </ul>
    </main>
  )
}

export default App

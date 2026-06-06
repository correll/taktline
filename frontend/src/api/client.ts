import axios from 'axios'

export const client = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Unwrap .data so callers get the payload directly; reject with the detail string.
client.interceptors.response.use(
  (res) => res.data,
  (err) => Promise.reject(err.response?.data?.detail ?? err.message)
)

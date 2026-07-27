/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base URL. Unset → '/api' (dev proxy). Cross-origin prod →
   *  e.g. 'https://api.example.com'. Same-origin prod → '' (empty). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

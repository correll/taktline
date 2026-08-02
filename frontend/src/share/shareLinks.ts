/**
 * Where a share goes, and what it says when it gets there.
 *
 * URLs are built from `window.location.origin` rather than from configuration:
 * the app is served same-origin with the API in production, and in dev this
 * points at the Vite server — which is the address a developer can actually
 * open. A configured base would be one more thing to get wrong in exactly the
 * place where being wrong is invisible until someone posts a dead link.
 */

export function shareUrl(id: string): string {
  return `${window.location.origin}/i/${id}`
}

export function cardUrl(id: string): string {
  return `${window.location.origin}/i/${id}/card.png`
}

/**
 * LinkedIn's share dialog takes a URL and nothing else — the `title`/`summary`
 * parameters were removed in 2021, and everything the post shows now comes from
 * the Open Graph tags on the page (which is why `/i/<id>` is server-rendered).
 * So the flow is: put the text on the clipboard, then open the composer.
 */
export function linkedInUrl(url: string): string {
  return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`
}

export function mailtoUrl(subject: string, body: string): string {
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Clipboard access is denied outside a secure context and in some locked
    // browsers. The textarea in the modal is selectable, so the user still has
    // a way through — but the button must not silently claim success.
    return false
  }
}

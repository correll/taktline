import React, { useCallback, useEffect, useRef, useState } from 'react'
import { color, font, size, shadow } from '../../theme/tokens'

/** Decoders, in order of preference.
 *
 *  `BarcodeDetector` is native, fast and free — but Safari does not implement
 *  it, and Safari is the whole iOS story. So ZXing is the fallback rather than
 *  the exception, and it is loaded lazily: ~300 KB has no business in the
 *  bundle of a board that mostly gets tapped, not scanned.
 */
type Decoder = { decode: (v: HTMLVideoElement) => Promise<string | null>; stop: () => void }

async function nativeDecoder(): Promise<Decoder | null> {
  const AnyWin = window as unknown as { BarcodeDetector?: new (o: unknown) => {
    detect: (s: CanvasImageSource) => Promise<Array<{ rawValue: string }>> } }
  if (!AnyWin.BarcodeDetector) return null
  const det = new AnyWin.BarcodeDetector({ formats: ['code_128', 'qr_code', 'code_39'] })
  return {
    async decode(v) {
      const hits = await det.detect(v)
      return hits[0]?.rawValue ?? null
    },
    stop() {},
  }
}

async function zxingDecoder(): Promise<Decoder> {
  const [{ BrowserMultiFormatReader }, { DecodeHintType, BarcodeFormat }] = await Promise.all([
    import('@zxing/browser'),
    import('@zxing/library'),
  ])
  // Restricting the formats is not premature optimisation here: the label this
  // scans is Code 128 (the ZPL `^BC` on /cards/{id}/label), and every extra
  // symbology is another full pass over each frame on a phone CPU.
  const hints = new Map()
  hints.set(DecodeHintType.POSSIBLE_FORMATS,
            [BarcodeFormat.CODE_128, BarcodeFormat.QR_CODE, BarcodeFormat.CODE_39])
  const reader = new BrowserMultiFormatReader(hints)
  const canvas = document.createElement('canvas')
  return {
    async decode(v) {
      if (!v.videoWidth) return null
      canvas.width = v.videoWidth
      canvas.height = v.videoHeight
      const ctx = canvas.getContext('2d')
      if (!ctx) return null
      ctx.drawImage(v, 0, 0)
      try {
        return reader.decodeFromCanvas(canvas).getText()
      } catch {
        return null                      // no symbol in this frame — normal
      }
    },
    stop() { /* reader holds no stream of its own here */ },
  }
}

export function ScanSheet({ onScan, onClose }: {
  onScan: (text: string) => void
  onClose: () => void
}) {
  const videoRef  = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const liveRef   = useRef(true)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  const stop = useCallback(() => {
    liveRef.current = false
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
  }, [])

  useEffect(() => {
    liveRef.current = true
    let decoder: Decoder | null = null

    ;(async () => {
      // Camera and decoder are separated on purpose. Lumping them together
      // reports "could not start the camera" when the camera is fine and the
      // decoder failed to load — which sends you looking in exactly the wrong
      // place, starting with iOS permission settings.
      let stream: MediaStream
      try {
        // `facingMode: environment` asks for the rear camera; on a tablet in a
        // stand that is the one pointed at the bench.
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } }, audio: false,
        })
      } catch (e) {
        const name = (e as { name?: string })?.name
        setError(
          name === 'NotAllowedError'
            ? 'Camera permission was denied. On iPhone, allow camera access for this site in Settings → Safari.'
            : name === 'NotFoundError'
            ? 'No camera on this device.'
            : 'Could not start the camera.')
        return
      }

      if (!liveRef.current) { stream.getTracks().forEach((t) => t.stop()); return }
      streamRef.current = stream
      const v = videoRef.current
      if (!v) return
      v.srcObject = stream
      v.setAttribute('playsinline', 'true')     // iOS: do not go fullscreen
      try { await v.play() } catch { /* autoplay guard; the stream still renders */ }
      setReady(true)

      try {
        decoder = (await nativeDecoder()) ?? (await zxingDecoder())
      } catch (e) {
        setError(`Could not load the barcode decoder: ${(e as Error)?.message ?? e}`)
        return
      }

      const tick = async () => {
        if (!liveRef.current || !videoRef.current) return
        try {
          const text = await decoder!.decode(videoRef.current)
          if (text && liveRef.current) {
            stop()
            onScan(text.trim())
            return
          }
        } catch { /* no symbol in this frame — keep scanning */ }
        setTimeout(tick, 120)                   // ~8 fps is plenty and cheap
      }
      tick()
    })()

    return () => { stop(); decoder?.stop() }
  }, [onScan, stop])

  return (
    <div style={{
      // Fully opaque: at 92% the app's own topbar ghosted through the
      // header strip, which reads as a rendering fault rather than a scrim.
      position: 'fixed', inset: 0, zIndex: 9500, background: '#000',
      display: 'flex', flexDirection: 'column',
    }}>
      <div className="tk-safe-top" style={{
        display: 'flex', alignItems: 'center', gap: size.sp3,
        padding: `${size.sp4} ${size.sp5}`, color: '#fff',
      }}>
        <span style={{ fontFamily: font.mono, fontSize: 12, letterSpacing: '0.1em' }}>
          SCAN A LOT LABEL
        </span>
        <button onClick={() => { stop(); onClose() }} style={{
          marginLeft: 'auto', background: 'none', border: '1px solid #ffffff44',
          borderRadius: size.radius, color: '#fff', padding: '4px 12px',
          fontSize: 13, cursor: 'pointer',
        }}>Close</button>
      </div>

      {/* minHeight:0 is load-bearing: a flex item defaults to min-height:auto,
          so the video's intrinsic 480p height wins over `flex: 1` and the
          preview grows past the screen instead of fitting it. */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }}>
        <video ref={videoRef} muted playsInline
               style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        {/* Aiming guide — a wide, short window, because Code 128 is a long
            horizontal symbol and people instinctively frame a square. */}
        {ready && !error && (
          <div style={{
            position: 'absolute', top: '50%', left: '8%', width: '84%', height: 130,
            transform: 'translateY(-50%)', border: `2px solid ${color.bluePrimary}`,
            borderRadius: size.radiusMd, boxShadow: shadow.lg, pointerEvents: 'none',
          }} />
        )}
        {error && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', padding: size.sp6, textAlign: 'center',
            color: '#fff', fontSize: 14, lineHeight: 1.6,
          }}>{error}</div>
        )}
      </div>

      <div className="tk-safe-bottom" style={{
        padding: `${size.sp4} ${size.sp5}`, color: '#ffffffaa', fontSize: 12.5,
        textAlign: 'center', lineHeight: 1.5,
      }}>
        Hold the printed label inside the frame. Labels come from
        Settings → the lot card’s Print action.
      </div>
    </div>
  )
}

export default ScanSheet

import DOMPurify from 'dompurify'
import { useMemo } from 'react'

// Production question HTML + inline MathML, sanitised. MathML renders natively.
const CONFIG = {
  USE_PROFILES: { html: true, mathMl: true },
  ADD_TAGS: ['ins', 'del'],
  FORBID_TAGS: ['style', 'script', 'iframe', 'form', 'input'],
  FORBID_ATTR: ['style', 'onerror', 'onclick', 'onload'],
}

export default function Html({ html, className = '' }) {
  const clean = useMemo(() => DOMPurify.sanitize(html || '', CONFIG), [html])
  if (!html) return <p className="text-sm italic text-muted">(empty)</p>
  return <div className={`qhtml ${className}`} dangerouslySetInnerHTML={{ __html: clean }} />
}

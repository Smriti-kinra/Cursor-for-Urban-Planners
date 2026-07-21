export const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']
export const PDF_RASTER_SCALE = 1.5
export const PDF_MAX_PIXELS = 2200

export const MIME_MAP: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
}

export async function rasterizePdfPage(
  absPath: string,
  pageNumber: number,
): Promise<{ base64: string; totalPages: number } | null> {
  const base64Pdf = await window.electronAPI.readFileBase64(absPath)
  if (!base64Pdf) return null
  const binary = atob(base64Pdf)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

  const pdfjs = await import('pdfjs-dist')
  type GlobalOptions = { disableWorker?: boolean }
  ;(pdfjs as unknown as { GlobalWorkerOptions: GlobalOptions }).GlobalWorkerOptions.disableWorker = true

  const doc = await pdfjs.getDocument({ data: bytes }).promise
  const total = doc.numPages
  const page = await doc.getPage(Math.max(1, Math.min(pageNumber, total)))
  let viewport = page.getViewport({ scale: PDF_RASTER_SCALE })
  const longer = Math.max(viewport.width, viewport.height)
  if (longer > PDF_MAX_PIXELS) {
    const adj = PDF_MAX_PIXELS / longer
    viewport = page.getViewport({ scale: PDF_RASTER_SCALE * adj })
  }

  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  await page.render({ canvasContext: ctx, viewport, canvas }).promise

  const dataUrl = canvas.toDataURL('image/png')
  const base64 = dataUrl.split(',')[1] || ''
  return { base64, totalPages: total }
}

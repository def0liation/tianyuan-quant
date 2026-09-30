const http = require('http')
const https = require('https')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, 'dist')
const port = Number(process.env.PORT || 4177)
const host = process.env.HOST || '127.0.0.1'
const apiProxyTarget = process.env.API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
}

function proxyApiRequest(request, response) {
  try {
    const target = new URL(request.url || '/', apiProxyTarget)
    const transport = target.protocol === 'https:' ? https : http
    const headers = { ...request.headers, host: target.host }
    const proxy = transport.request(target, { method: request.method, headers }, (upstream) => {
      upstream.on('error', () => failResponse(response, 502, 'API proxy unavailable'))
      response.writeHead(upstream.statusCode || 502, upstream.headers)
      upstream.pipe(response)
    })
    proxy.on('error', () => failResponse(response, 502, 'API proxy unavailable'))
    request.on('aborted', () => proxy.destroy())
    request.pipe(proxy)
  } catch {
    failResponse(response, 502, 'API proxy unavailable')
  }
}

function failResponse(response, status, message) {
  if (response.destroyed || response.writableEnded) return
  if (response.headersSent) {
    response.destroy()
    return
  }
  response.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8' })
  response.end(message)
}

function withinRoot(base, filePath) {
  const relative = path.relative(base, filePath)
  return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
}

http.createServer((request, response) => {
  let urlPath
  try {
    urlPath = decodeURIComponent((request.url || '/').split('?')[0]).replace(/\\/g, '/')
  } catch {
    failResponse(response, 400, 'Invalid request path')
    return
  }
  if (urlPath.includes('\0')) {
    failResponse(response, 400, 'Invalid request path')
    return
  }

  if (apiProxyTarget && (urlPath === '/api' || urlPath.startsWith('/api/'))) {
    proxyApiRequest(request, response)
    return
  }

  let filePath = path.resolve(root, `.${urlPath.startsWith('/') ? urlPath : `/${urlPath}`}`)
  if (!withinRoot(root, filePath)) {
    failResponse(response, 403, 'Forbidden')
    return
  }

  try {
    if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) filePath = path.join(root, 'index.html')
    const realRoot = fs.realpathSync(root)
    const realFile = fs.realpathSync(filePath)
    if (!withinRoot(realRoot, realFile)) {
      failResponse(response, 403, 'Forbidden')
      return
    }
    const stream = fs.createReadStream(realFile)
    stream.on('error', (error) => failResponse(response, error.code === 'ENOENT' ? 404 : 500, 'File unavailable'))
    stream.on('open', () => {
      if (response.destroyed) { stream.destroy(); return }
      response.writeHead(200, { 'Content-Type': mime[path.extname(filePath)] || 'application/octet-stream' })
      if (request.method === 'HEAD') { stream.destroy(); response.end(); return }
      stream.pipe(response)
    })
    response.on('close', () => stream.destroy())
  } catch (error) {
    failResponse(response, error.code === 'ENOENT' ? 404 : 500, 'File unavailable')
  }
}).listen(port, host, () => {
  console.log(`preview http://${host}:${port}`)
})

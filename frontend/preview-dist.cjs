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
  const target = new URL(request.url || '/', apiProxyTarget)
  const transport = target.protocol === 'https:' ? https : http
  const headers = { ...request.headers, host: target.host }

  const proxy = transport.request(target, {
    method: request.method,
    headers,
  }, (proxyResponse) => {
    response.writeHead(proxyResponse.statusCode || 502, proxyResponse.headers)
    proxyResponse.pipe(response)
  })

  proxy.on('error', (error) => {
    response.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' })
    response.end(`API proxy error: ${error.message}`)
  })

  request.pipe(proxy)
}

http.createServer((request, response) => {
  const urlPath = decodeURIComponent((request.url || '/').split('?')[0])

  if (apiProxyTarget && urlPath.startsWith('/api')) {
    proxyApiRequest(request, response)
    return
  }

  let filePath = path.join(root, urlPath === '/' ? 'index.html' : urlPath)

  if (!filePath.startsWith(root)) {
    response.writeHead(403)
    response.end('Forbidden')
    return
  }

  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(root, 'index.html')
  }

  response.writeHead(200, {
    'Content-Type': mime[path.extname(filePath)] || 'application/octet-stream',
  })
  fs.createReadStream(filePath).pipe(response)
}).listen(port, host, () => {
  console.log(`preview http://${host}:${port}`)
})

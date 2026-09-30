import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.ico': 'image/x-icon' };

createServer(async (request, response) => {
  let path;
  try {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const allowed = pathname.startsWith('/prototypes/feedback-web/')
      || pathname === '/apps/web/public/icons/icon-192.png'
      || pathname === '/apps/web/generated/visual-tokens.css';
    if (!allowed) throw new Error('Outside prototype assets');
    path = resolve(root, `.${pathname}`);
    if (path !== root && !path.startsWith(`${root}${sep}`)) throw new Error('Outside prototype root');
    if ((await stat(path)).isDirectory()) path = join(path, 'index.html');
    const body = await readFile(path);
    response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    response.end(body);
  } catch {
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Not found');
  }
}).listen(4173, '127.0.0.1', () => {
  process.stdout.write('Feedback prototype: http://127.0.0.1:4173/prototypes/feedback-web/\n');
});

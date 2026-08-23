const path = require('path');
const os = require('os');

const localIpv4Addresses = Object.values(os.networkInterfaces())
  .flatMap((addresses) => addresses || [])
  .filter((address) => address.family === 'IPv4' && !address.internal)
  .map((address) => address.address);

const configuredBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || '').trim();
const basePath = configuredBasePath && configuredBasePath !== '/'
  ? `/${configuredBasePath.replace(/^\/+|\/+$/g, '')}`
  : '';

function pythonBackendOrigin(value = process.env.PYTHON_API_ORIGIN) {
  const parsed = new URL((value || 'http://127.0.0.1:8000').trim());
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '::1'].includes(parsed.hostname)) {
    throw new Error('PYTHON_API_ORIGIN must use HTTP on a loopback host');
  }
  return parsed.origin;
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || '.next',
  output: 'standalone',
  outputFileTracingRoot: path.join(__dirname, '../..'),
  allowedDevOrigins: ['127.0.0.1', 'localhost', ...localIpv4Addresses],
  devIndicators: false,
  basePath,
  httpAgentOptions: {
    keepAlive: false
  },
  async rewrites() {
    const apiOrigin = pythonBackendOrigin();
    return {
      beforeFiles: [
        {
          source: '/api/:path*',
          destination: `${apiOrigin}/api/:path*`
        },
        {
          source: '/opds/:path*',
          destination: `${apiOrigin}/opds/:path*`
        }
      ]
    };
  }
};

module.exports = nextConfig;

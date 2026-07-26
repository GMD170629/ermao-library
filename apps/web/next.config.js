const path = require('path');

const configuredBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || '').trim();
const basePath = configuredBasePath && configuredBasePath !== '/'
  ? `/${configuredBasePath.replace(/^\/+|\/+$/g, '')}`
  : '';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  basePath,
  httpAgentOptions: {
    keepAlive: false
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: '/api/v2/:path*',
          destination: 'http://127.0.0.1:8000/api/v2/:path*'
        }
      ]
    };
  },
  experimental: {
    outputFileTracingRoot: path.join(__dirname, '../..')
  }
};

module.exports = nextConfig;

const path = require('path');

const configuredBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || '').trim();
const basePath = configuredBasePath && configuredBasePath !== '/'
  ? `/${configuredBasePath.replace(/^\/+|\/+$/g, '')}`
  : '';

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || '.next',
  output: 'standalone',
  outputFileTracingRoot: path.join(__dirname, '../..'),
  allowedDevOrigins: ['127.0.0.1'],
  devIndicators: false,
  basePath,
  httpAgentOptions: {
    keepAlive: false
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: '/api/:path*',
          destination: 'http://127.0.0.1:8000/api/:path*'
        },
        {
          source: '/opds/:path*',
          destination: 'http://127.0.0.1:8000/opds/:path*'
        }
      ]
    };
  }
};

module.exports = nextConfig;

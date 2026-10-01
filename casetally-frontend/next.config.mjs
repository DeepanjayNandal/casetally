/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a self-contained server bundle in .next/standalone, including a
  // minimal node_modules with only what the built app actually imports.
  // Without this the runtime image needs a full `npm ci --omit=dev`, which
  // ships every production dependency whether the build reached it or not.
  output: 'standalone',

  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  devIndicators: false,
}

export default nextConfig

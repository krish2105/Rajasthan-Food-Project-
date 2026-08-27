/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The FastAPI backend from Phases 1-2. Proxied rather than called
  // cross-origin so the bearer token never crosses an origin boundary and no
  // CORS configuration has to be right in two places.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_ORIGIN ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};
export default nextConfig;

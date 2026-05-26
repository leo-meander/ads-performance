/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async redirects() {
    return [
      // /country was the old "Country Dashboard" route. The merged ADS
      // Performance dashboard at / now accepts the same query params
      // (country, branches, platform, funnel, range, campaign) so deep links
      // from Meta recommendations keep working.
      { source: '/country', destination: '/', permanent: false },
      // Activity log was briefly its own page; it's now folded into /
      // dashboard so users see changes alongside performance.
      { source: '/activity-log', destination: '/', permanent: false },
      // Weekly Report was renamed to Action Needed (it filters any range).
      { source: '/weekly-report', destination: '/action-needed', permanent: false },
    ]
  },
}

module.exports = nextConfig

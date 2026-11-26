# Google Ads 1.0.4

- Connecting a Google Ads account now completes. The connection asks Google for
  `openid`, `https://www.googleapis.com/auth/userinfo.email` and
  `https://www.googleapis.com/auth/adwords`, the same names Google returns when you approve
  access, so Flow Steward accepts the authorization.
- A test checks that every required scope is written the way Google grants it.

On the Google consent screen, keep the Google Ads box ticked: the connection needs it.

The catalog release remains unverified. See ACCEPTANCE.md and COMPATIBILITY.md for the installed and live acceptance status.

[Changes since v1.0.3](https://github.com/Flow-Steward/ext-google-ads/compare/v1.0.3...v1.0.4)

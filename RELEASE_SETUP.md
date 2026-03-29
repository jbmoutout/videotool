# Release Setup — Manual TODOs

## Apple Developer Signing (one-time, ~$99/year)

1. **Enroll** at https://developer.apple.com/programs/enroll/ ($99/yr, Individual plan). Takes 24-48h for verification.
2. **Create certificate** — In Keychain Access: Certificate Assistant > Request a Certificate > save to disk. Then at https://developer.apple.com/account/resources/certificates/list click **+** > **Developer ID Application** > upload the `.certSigningRequest`.
3. **Export .p12** — In Keychain Access > My Certificates, right-click the cert > Export as `.p12`. Set a password.
4. **Base64 encode**:
   ```bash
   base64 -i Certificates.p12 -o cert-base64.txt
   ```
5. **Set 6 GitHub secrets** (Settings > Secrets > Actions):

   | Secret | Value |
   |--------|-------|
   | `APPLE_CERTIFICATE` | Contents of `cert-base64.txt` |
   | `APPLE_CERTIFICATE_PASSWORD` | Password from .p12 export |
   | `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Your Name (TEAMID)` — get exact string from `security find-identity -v -p codesigning` |
   | `APPLE_ID` | Your Apple ID email |
   | `APPLE_PASSWORD` | App-specific password from https://account.apple.com/ > Sign-In and Security > App-Specific Passwords |
   | `APPLE_TEAM_ID` | 10-char ID from https://developer.apple.com/account > Membership Details |

### Gotchas

- Certificate is valid for **5 years** — set a calendar reminder.
- App-specific password is **revoked** if you change your Apple ID password — regenerate and update the secret.
- Tauri handles hardened runtime and entitlements automatically. Custom entitlements (camera, network server) go in `tauri.conf.json` under `bundle > macOS > entitlements`.

---

## Cloudflare Worker (one-time, free tier)

1. **Create account** at https://dash.cloudflare.com/ (free)
2. **Login**:
   ```bash
   npx wrangler login
   ```
3. **Create KV namespace** (for rate limiting):
   ```bash
   cd cloudflare-worker
   npx wrangler kv namespace create RATE_LIMITS
   ```
   Copy the returned ID into `wrangler.toml` where it says `id = ""`.
4. **Deploy**:
   ```bash
   npx wrangler deploy
   ```
5. **Set secrets**:
   ```bash
   npx wrangler secret put GROQ_API_KEY
   npx wrangler secret put ANTHROPIC_API_KEY
   ```
6. **Verify**:
   ```bash
   curl https://vodtool-api.<your-subdomain>.workers.dev/health
   ```

---

## Node Upgrade (optional)

Current: 20.9.0. Wrangler wants >= 20.18.1.

```bash
nvm install 20
# or
brew upgrade node
```

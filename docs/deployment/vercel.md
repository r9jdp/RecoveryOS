# Vercel frontend deployment

The frontend is deployed independently from the VM. Create a Vercel project only
after the coordinator has scaffolded the Next.js workspace and confirm its root
directory in project settings (expected: `apps/web`).

## CLI flow

Authenticate interactively on an operator workstation, then run from the web
workspace:

```bash
pnpm dlx vercel link
pnpm dlx vercel env add NEXT_PUBLIC_API_BASE_URL preview
pnpm dlx vercel env add NEXT_PUBLIC_API_BASE_URL production
pnpm dlx vercel deploy
pnpm dlx vercel deploy --prod
```

Use the staging API origin for preview and the production API origin for the
production environment. `NEXT_PUBLIC_*` values are visible to every browser and
therefore may contain origins and display flags only.

Never add any of the following as public variables:

- Razorpay key secret or webhook secret.
- Database URL.
- Temporal API key.
- ElevenLabs or Twilio credential.
- Mandate signing private key.

## Validation

- The production URL loads without local infrastructure.
- Browser network requests use HTTPS and the intended API environment.
- Preview deployments cannot trigger production actions.
- Razorpay remains test mode and guarded provider actions require the operator
  control plane.
- A secret scan of downloaded browser assets finds no server credential.

Vercel account creation, project linking, and custom-domain ownership are manual
prerequisites; repository files do not imply they have happened.

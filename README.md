# PinHire webhook

This standard-library Python service implements the seed's webhook checks:

- `POST /webhook` verifies the exact raw request body with HMAC-SHA256 using
  the `x-pinhire-hmac-2510` header.
- A transaction reference is claimed atomically for 120 seconds. Retries return
  HTTP 409 with `{"status":"duplicate"}`.
- Refunds above 520 AED are rejected with HTTP 422, regardless of customer
  message content.
- `faq.query` events receive a deterministic response without calling an AI
  service or another network dependency.
- `GET /healthz` is available for deployment health checks.

## Run locally

Use the seed's signing token as the environment variable; do not put it in
source control.

PowerShell:

```powershell
$env:PINHIRE_SEED_TOKEN = "your-seed-signing-token"
python app.py
```

The service listens on `0.0.0.0:8000` by default. Set `PORT` if your host
provides a different port. Deploy this service to a public HTTPS host before
the assessment and configure the assessment with its `/webhook` URL.

## Test

```powershell
python -m unittest -v
```

Requests must be JSON objects containing `payload.tx_ref_2510`. The refund
amount, when present, is `payload.refund_aed`; FAQ events use
`event: "faq.query"` and `payload.query`.

## Deploy on Render (free)

The repository includes a Render Blueprint in `render.yaml`. The free plan is
useful for a deployment trial, but Render may spin down an idle service and
the first request after that can take about a minute. It is not a guarantee of
availability or response time during a live assessment.

1. Create a new, empty GitHub repository. Do not add a README or other starter
   files on GitHub.
2. In PowerShell, from this project directory, initialize Git and push the
   project:

   ```powershell
   git init
   git add app.py test_app.py README.md requirements.txt render.yaml .gitignore
   git commit -m "Prepare PinHire webhook deployment"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/pinhire-webhook.git
   git push -u origin main
   ```

   Replace `YOUR-USERNAME` with your GitHub username. The `.gitignore` keeps
   the virtual environment, Python cache, and `.env` files out of the repo.
3. In Render, choose **New → Blueprint**, connect the GitHub repository, and
   apply the `render.yaml` configuration. Select the **Free** plan if asked.
4. When prompted, enter the current seed's signing token as the secret
   environment variable `PINHIRE_SEED_TOKEN`. Never put the token in GitHub,
   `render.yaml`, or a message.
5. Wait for the deploy to finish. Open the Render service's public URL plus
   `/healthz`; expect `{"status":"ok"}`. The webhook URL to provide to the
   assessment is that same public URL plus `/webhook`.

If Git reports that a remote already exists, inspect it with `git remote -v`
before changing anything. Do not force-push. If PinHire gives you a new seed,
first verify its header name, key, refund limit, TTL, and expected payload
format; this service currently uses the values documented above.

# Storage Bucket API — sample application

A small application that calls every endpoint the Kuberns storage bucket API
offers, with a button for each. Use it to see what a customer's integration
actually looks like, and to check an endpoint by hand without writing a curl
line for it.

## Running it locally

Create a credential first: Kuberns dashboard → **Buckets → Credentials → Create**.
The secret is shown once.

```bash
pip install -r requirements.txt

export KB_GATEWAY_URL=https://storage-staging.kuberns.site
export KB_ACCESS_KEY_ID=kbs...
export KB_SECRET=...

python3 app.py
```

Open http://localhost:8000.

## Deploying it on Kuberns

It is a Flask app, so deploy it as one. Set three environment variables and
nothing else:

| Variable | Value |
|---|---|
| `KB_GATEWAY_URL` | your storage gateway's address |
| `KB_ACCESS_KEY_ID` | from Buckets → Credentials |
| `KB_SECRET` | the secret shown when that credential was created |

`gunicorn` binds to `$PORT` through the `Procfile`. `GET /healthz` answers
whether the app is up and whether it has been given a credential, which is
usually the faster way to find out that one of the three is missing.

## What it covers

| Button | Call |
|---|---|
| List buckets | `GET /buckets` |
| Create bucket | `POST /buckets` |
| Bucket detail | `GET /buckets/{bucket}` |
| Delete bucket | `DELETE /buckets/{bucket}` |
| Create folder | `POST /buckets/{bucket}/folders` |
| List objects | `GET /{bucket}?prefix=&token=` |
| Upload | `PUT /{bucket}/{key}` |
| Download | `GET /{bucket}/{key}` |
| Metadata | `HEAD /{bucket}/{key}` |
| Delete object | `DELETE /{bucket}/{key}` |
| Read visibility | `GET /buckets/{bucket}/visibility?key=` |
| Set visibility | `PUT /buckets/{bucket}/visibility` |
| Get a link | `POST /buckets/{bucket}/url` |

The three walkthroughs run several of these in the order an application would.

## How the credential is used

As HTTP Basic auth — the access key id is the username, the secret is the
password. Any HTTP client can do that, so there is no SDK to install:

```
Authorization: Basic base64(<access-key-id>:<secret>)
```

The credential is held by `server.py` and never sent to the browser. That is
not a quirk of this demo. Anything in page JavaScript is readable by whoever
opens the page, so a real application keeps it on its own server exactly like
this one does.

## Two things worth noticing

**Links are CDN links.** `POST /buckets/{bucket}/url` answers with a permanent
link for a public object and a signed, expiring one for a private object. The
gateway's own address is never handed out, so there is a single address for a
file whatever its state.

**Creating credentials is not in the API.** It is dashboard-only, on purpose:
an API that can mint its own credentials cannot have them revoked by taking
one away.

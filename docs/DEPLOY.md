# ORIGIN — Manual AWS Deployment Runbook

Deploys the ORIGIN API and dashboard as an **AWS Lambda container image** behind
an **API Gateway HTTP API**.

| | |
|---|---|
| Account | `248557779236` |
| Region | `eu-central-1` (same as the S3 bucket — keep it that way) |
| Bucket | `origin-provenance-248557779236` |
| Image | `Dockerfile.lambda` (verified: builds, handler imports, 16 routes) |
| Function | `origin-api` |
| ECR repo | `origin-lambda` |
| Role | `origin-lambda-role` |
| **API ID** | **`lg7mjxz6m2`** |
| **Endpoint** | **`https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com`** |

**Why this shape:** Bedrock and Lambda **Function URLs** are blocked at account
level on this account. API Gateway is the working front door. A container image
rather than a zip because `psycopg[binary]` needs manylinux wheels that do not
build cleanly from Windows.

## Progress

- [x] **Step 0** — AWS CLI installed (`aws-cli/2.36.21`), configured, identity confirmed
- [x] **Step 1** — ECR repository `origin-lambda` created
- [x] **Step 2** — Docker authenticated to ECR (`Login Succeeded`)
- [x] **Step 3** — Built, handler import verified, pushed. ⚠️ **First push used a
      manifest list and Lambda rejected it — rebuild with `--provenance=false
      --sbom=false` and re-push.** See gotcha 2.
- [x] **Step 4** — Role policies applied; leftover `origin-s3-documents` removed
- [x] **Step 5a** — Function `origin-api` created and **Active / Successful**
      (`x86_64`, 1024 MB, 30 s)
- [x] **Step 5b** — Environment applied — all 7 keys present
- [x] **Step 5c** — Direct invoke smoke test: `"status":"ok"`, cluster reachable
- [x] **Step 6a** — API Gateway created: `lg7mjxz6m2`
- [x] **Step 6b** — `lambda add-permission` granted
- [x] **Step 7** — ✅ **Verified live end-to-end**

## ✅ DEPLOYED — verified Aug 17, 13:08 UTC

**`https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com`**

| Endpoint | Result |
|---|---|
| `GET /api/v1/health` | `"status":"ok"` · cluster reachable · CockroachDB CCL v26.2.5 · `"storage":"s3"` |
| `GET /` | 200, dashboard HTML (20.6 KB) |
| `GET /api/v1/memory/rulings` | 200 — **43 rulings remembered**, live from the memory layer |
| `POST /api/v1/sessions` *no token* | **401** — write gate engaged |
| `POST /api/v1/sessions` *with token* | 200 — session created |

Demo write token: **`origin-demo-2026`**, sent as the `X-Origin-Token` header.
Publish it with the submission so judges can exercise the write path; the 401
above is the evidence the endpoint is not simply open.

## Shell note

Commands below work in **cmd.exe** (what this deploy is being run in). Where
PowerShell differs, it is called out. JSON arguments are passed as `file://…`
rather than inline **on purpose** — inline JSON quoting differs between cmd.exe,
PowerShell 5.1, and bash, and is the single most common way this runbook fails.
Windows PowerShell 5.1 also has no `&&`; run one line at a time either way.

---

## Read this before you start — three things that will cost you an hour each

### 1. `AWS_REGION` is a RESERVED Lambda variable — do not set it

Lambda **rejects** any attempt to set `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, or `AWS_SESSION_TOKEN` as function environment
variables. The update fails with a validation error naming the reserved key.

Lambda injects `AWS_REGION` automatically, and `boto3` picks up credentials from
the **execution role**. So S3 access works with *no* credentials configured. Your
local `.env` sets these — the Lambda env var list must **not**.

### 2. Build with `--platform linux/amd64 --provenance=false --sbom=false`

**All three flags are required.** Two separate failures hide here.

`--platform linux/amd64` — the function is created as `x86_64`. An `arm64` layer
creates fine and then fails at invoke with `exec format error`.

`--provenance=false --sbom=false` — **this one actually bit us.** Modern Docker
Desktop / BuildKit attaches provenance and SBOM attestations by default, which
turns the result into an OCI **manifest list** rather than a plain image
manifest. Lambda cannot read it, and `create-function` fails with:

```
InvalidParameterValueException: The image manifest, config or layer media type
for the source image ... is not supported.
```

The message names the *image*, so the natural reading is that something is wrong
with the Dockerfile or the layers. Nothing is — only the manifest wrapper.

**Spot it in the build output.** A bad build prints these two lines; a good build
prints neither:

```
=> => exporting attestation manifest sha256:...
=> => exporting manifest list sha256:...
```

A good build ends at `exporting manifest` / `exporting config`. Verified on this
project: identical layers, identical `handler OK`, only the manifest differs.

### 3. Writes are OPEN if `ORIGIN_WRITE_TOKEN` is empty

`app.py:67` — the gate only engages when the variable is non-empty. Deploying
without it leaves `POST /api/v1/takedown` open to the internet.

Set a token, then **publish it in the README and on Devpost** as the demo token.
Judges can still exercise the write path; you are not running an open destructive
endpoint. That is a better Product-Readiness story than either extreme.

---

## Step 0 — Install and configure the AWS CLI ✅

```
winget install --id Amazon.AWSCLI -e
```

Reopen the shell, then `aws --version` and `aws configure`. Enter the access key,
secret, and `eu-central-1`. Confirm the account reads `248557779236`:

```
aws sts get-caller-identity
```

> **Credential hygiene.** Never paste `aws configure` output, screenshots of it,
> or your `DATABASE_URL` anywhere shared — both carry live secrets. If a key is
> exposed, rotate it in IAM (create new → `aws configure` → update `.env` →
> deactivate and delete the old one). The deployed Lambda is unaffected by
> rotation because it authenticates via its execution role, not these keys.

---

## Step 1 — Create the ECR repository ✅

```
aws ecr create-repository --repository-name origin-lambda --region eu-central-1
```

`EntityAlreadyExists` / `RepositoryAlreadyExistsException` is fine — move on.

---

## Step 2 — Authenticate Docker to ECR ✅

```
aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin 248557779236.dkr.ecr.eu-central-1.amazonaws.com
```

Expect `Login Succeeded`. This expires after ~12 hours — re-run if a later push
fails with an auth error.

---

## Step 3 — Build, tag, push ✅

**`cd` to the repo root first.** The Dockerfile does `COPY src/`, `COPY sql/` and
`COPY pyproject.toml`, so the build context (`.`) must be the repo root — running
from elsewhere fails with `failed to read dockerfile` even when `-f` is correct.
The path contains a space, so quote it:

```
cd "C:\DeepakJadhav\Personal\CockroachDB_AWS Hackathon\origin"
```

```
docker build --platform linux/amd64 --provenance=false --sbom=false -f Dockerfile.lambda -t origin-lambda:latest .
```

**Verify the handler imports before pushing 800 MB.** This is the check that
caught the missing `httpx`:

```
docker run --rm --entrypoint python origin-lambda:latest -c "from origin.api.lambda_handler import handler; print('handler OK')"
```

Only if that prints `handler OK`:

```
docker tag origin-lambda:latest 248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest
docker push 248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest
```

The push is ~800 MB. Expect several minutes.

---

## Step 4 — Execution role

Policy documents live in [`deploy/`](../deploy/) so no inline JSON quoting is
needed. Run these **from the repo root**.

**If the role does not exist yet:**

```
aws iam create-role --role-name origin-lambda-role --assume-role-policy-document file://deploy/trust-policy.json
```

**If it already exists** (`EntityAlreadyExists`) — do not skip this. The role may
be left over from an earlier attempt with a different trust policy, and a wrong
one fails later in a way that looks like an IAM propagation delay:

```
aws iam update-assume-role-policy --role-name origin-lambda-role --policy-document file://deploy/trust-policy.json
```

Attach CloudWatch Logs:

```
aws iam attach-role-policy --role-name origin-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

Least-privilege S3 — `deploy/s3-policy.json` grants `GetObject`/`PutObject` on
`origin/documents/*` and a prefix-scoped `ListBucket` on the bucket itself.
`ListBucket` is a **bucket-level** action, so it must target the bucket ARN, not
the object ARN — a single combined statement silently fails to authorise listing:

```
aws iam put-role-policy --role-name origin-lambda-role --policy-name origin-s3-access --policy-document file://deploy/s3-policy.json
```

Verify what actually landed:

```
aws iam list-attached-role-policies --role-name origin-lambda-role
aws iam list-role-policies --role-name origin-lambda-role
```

Expect exactly `AWSLambdaBasicExecutionRole` attached and `origin-s3-access`
inline. **Remove any leftovers from earlier attempts** — duplicate overlapping
grants undermine the least-privilege claim a judge may check:

```
aws iam get-role-policy --role-name origin-lambda-role --policy-name origin-s3-documents
aws iam delete-role-policy --role-name origin-lambda-role --policy-name origin-s3-documents
```

**Wait ~10 seconds** before Step 5, or it fails with
`InvalidParameterValueException: The role defined for the function cannot be assumed`.

---

## Step 5 — Create the function

```
aws lambda create-function --function-name origin-api --package-type Image --code ImageUri=248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest --role arn:aws:iam::248557779236:role/origin-lambda-role --architectures x86_64 --timeout 30 --memory-size 1024 --region eu-central-1
```

### Environment variables — generate, do not hand-edit

Hand-copying `DATABASE_URL` into JSON failed **twice** here, in two different
ways, and neither error pointed at the paste:

| What went wrong | How it surfaced |
|---|---|
| The console paste dragged in the trailing "Sql user" block, putting a newline inside the string | `ParamValidation: Invalid control character`. The CLI then applied **no environment at all**, so the next invoke failed on a *missing* `DATABASE_URL` — not on the thing you just changed |
| A later paste carried a superseded password | `password authentication failed for user dj`, visible only from inside the running function |

So generate it from the `.env` that already works:

```
.venv\Scripts\python deploy\make-lambda-env.py
```

That writes `%USERPROFILE%\origin-lambda-env.json` — **outside the repo**,
because it contains the cluster password. It refuses to emit a multi-line
`DATABASE_URL` or any Lambda-reserved `AWS_*` key, and it never prints the
password. (`.gitignore` blocks `*env*.json` as a backstop, but the file should
not be in the tree at all.)

`ORIGIN_DEMO_CORPUS` is **not** needed: the code default `hub-commercial`
(`app.py:57`) is the corpus on the cluster.

Apply it:

```
aws lambda update-function-configuration --function-name origin-api --region eu-central-1 --environment file://%USERPROFILE%/origin-lambda-env.json
```

> **If you rotate the CockroachDB password**, update `.env`, re-run the
> generator, and re-apply. The Lambda holds its own copy — rotating the cluster
> password without this leaves the function authenticating with a dead
> credential, and the only symptom is `"status":"degraded"` in the health body.

A successful call prints the full function configuration. Confirm independently —
do not assume:

```
aws lambda get-function-configuration --function-name origin-api --region eu-central-1 --query "Environment.Variables"
```

Expect an object with all seven keys.

`null` means **no environment is set** and the update did not take — go back and
fix the JSON. Do not pipe this through `keys(@)`: on an unset environment JMESPath
raises `invalid type for value: None` instead of printing `null`, which reads like
a broken command rather than the answer it actually is.

### Smoke test — before touching the gateway

The event must be a **complete** API Gateway v2 payload.
[`deploy/health-event.json`](../deploy/health-event.json) is one, and using a file
avoids cmd.exe quoting entirely:

```
aws lambda invoke --function-name origin-api --region eu-central-1 --cli-binary-format raw-in-base64-out --payload file://deploy/health-event.json response.json
type response.json
```

*(PowerShell: `Get-Content response.json`.)*

A minimal hand-written payload is **not** enough — Mangum reads
`requestContext.http.sourceIp`, and omitting it fails with
`KeyError: 'sourceIp'` before your application code ever runs. That looks like an
app bug and is not one.

Expected body:

```json
{"status":"ok","service":"origin-provenance-api","cluster":{"reachable":true,...},"storage":"s3","demo_corpus":"hub-commercial","writes_protected":true}
```

`writes_protected: true` confirms `ORIGIN_WRITE_TOKEN` reached the function.

This one call proves the image, IAM role, environment, and the network path to
CockroachDB Cloud are **all** correct. **Do not proceed until it works** —
through API Gateway every one of those failures returns the same opaque 500.

---

## Step 6 — API Gateway HTTP API

```
aws apigatewayv2 create-api --name origin-api --protocol-type HTTP --target arn:aws:lambda:eu-central-1:248557779236:function:origin-api --region eu-central-1
```

`--target` creates the integration, the `$default` route, and an auto-deploying
`$default` stage in one call.

### Where the API ID comes from

The ID is created *by this call* — it does not exist beforehand. The response
carries it:

```json
{
  "ApiId": "lg7mjxz6m2",
  "ApiEndpoint": "https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com"
}
```

**For this deployment the ID is `lg7mjxz6m2`**, already substituted throughout
the rest of this document. It is also the first label of `ApiEndpoint` — the same
string. If you tear down and recreate, the new ID must be substituted again.

**Lost the output, or want to confirm what exists:**

```
aws apigatewayv2 get-apis --region eu-central-1 --query "Items[].[Name,ApiId,ApiEndpoint]" --output table
```

If that lists more than one `origin-api`, an earlier attempt left a duplicate.
Keep one, and delete the rest with
`aws apigatewayv2 delete-api --api-id <OTHER_ID> --region eu-central-1`.

Grant the gateway permission to invoke — **this is the step people forget**, and
without it every request returns 500:

```
aws lambda add-permission --function-name origin-api --statement-id apigw-invoke --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:eu-central-1:248557779236:lg7mjxz6m2/*/*" --region eu-central-1
```

Confirm it exists — `create-api --target` does **not** add it for you:

```
aws lambda get-policy --function-name origin-api --region eu-central-1
```

`ResourceNotFoundException` means **no** invoke permission is attached. That is
the expected error before this step and a bug after it.

---

## Step 7 — Verify

```
curl https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com/api/v1/health
```

Then in a browser:

- `https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com/` — the dashboard,
  including the live memory hit rate
- `/api/v1/memory/rulings` — the memory layer (read, no token needed)

Write path, using the token you set:

```
curl -X POST https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com/api/v1/sessions -H "X-Origin-Token: origin-demo-2026" -H "Content-Type: application/json" -d "{\"actor\":\"judge\"}"
```

**Warm it before recording.** The first invocation pulls an 800 MB image and
opens a TLS connection to CockroachDB Cloud — 10–20 s is normal. Hit
`/api/v1/health` twice before starting the screen capture.

**Record the endpoint** — it is the "functional demo app URL" the submission
requires, and it belongs in the README, Devpost, and the video.

---

## Redeploying after a code change

```
docker build --platform linux/amd64 --provenance=false --sbom=false -f Dockerfile.lambda -t origin-lambda:latest .
docker run --rm --entrypoint python origin-lambda:latest -c "from origin.api.lambda_handler import handler; print('OK')"
docker tag origin-lambda:latest 248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest
docker push 248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest
aws lambda update-function-code --function-name origin-api --image-uri 248557779236.dkr.ecr.eu-central-1.amazonaws.com/origin-lambda:latest --region eu-central-1
```

Pushing the same tag does **not** update the function — `update-function-code` is
required.

**Regression guard:** the pip list in `Dockerfile.lambda` is hand-maintained and
does **not** derive from `pyproject.toml`. `httpx` was already missing once and
made every invocation fail. Re-run the import check after any new top-level
import in `src/`.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `failed to read dockerfile` | Not in the repo root. `cd` to `origin/` (quote the path — it has a space). |
| `Runtime.ImportModuleError` | Dependency missing from `Dockerfile.lambda`'s pip list. Reproduce with the `docker run … import handler` check. |
| `image manifest, config or layer media type … is not supported` | BuildKit attestations produced a manifest list. Rebuild with `--provenance=false --sbom=false`, re-tag, re-push. The layers are unchanged, so the push is fast. Nothing is wrong with the image itself. |
| `exec format error` | Image built for arm64. Rebuild with `--platform linux/amd64`. |
| `EntityAlreadyExists` on `create-role` | Left over from an earlier attempt. Use `update-assume-role-policy`. |
| `role cannot be assumed` | IAM not propagated (wait 10 s), **or** the trust policy is wrong — re-run the Step 4 update. |
| `InvalidParameterValueException` naming `AWS_REGION` | Reserved key in the env list. Remove all `AWS_*`. |
| 500 on every gateway request | Missing `lambda add-permission` (Step 6). |
| Timeout at 30 s | Cluster asleep or unreachable. Check the CockroachDB Cloud console. |
| S3 `AccessDenied` on list | `ListBucket` targeting the object ARN instead of the bucket ARN. Use `deploy/s3-policy.json` as written. |
| 401 on POST | Missing `X-Origin-Token` header. |
| `Unable to parse` on a `--payload` / `--environment` arg | Shell quoting. Use `file://` instead of inline JSON. |
| `ParamValidation: Invalid control character` | A line break inside a JSON string value — almost always a `DATABASE_URL` pasted with the console's trailing "Sql user" block. Put it on one line. |
| `In function keys(), invalid type for value: None` | Not a broken command — `Environment.Variables` is `null`, i.e. the env was never applied. Re-run `update-function-configuration`. |
| `KeyError: 'sourceIp'` in the invoke response | Incomplete test event, not an app bug. Use `deploy/health-event.json`. |
| `"status":"degraded"` + `password authentication failed for user dj` | The function holds its own copy of `DATABASE_URL` and it is stale — usually the cluster password was rotated afterwards. Re-run `deploy/make-lambda-env.py`, re-apply, done. Everything else in the health body being correct (`storage: s3`, `writes_protected: true`) confirms the deploy itself is sound. |
| `get-policy` → `ResourceNotFoundException` | No invoke permission attached. Expected *before* Step 6b; a bug after it. |
| `aws` not found in a PowerShell session | Installed but not yet on that session's PATH. Reopen the shell, or call it by full path: `& "C:\Program Files\Amazon\AWSCLIV2\aws.exe"`. |

Logs:

```
aws logs tail /aws/lambda/origin-api --follow --region eu-central-1
```

---

## Fallback if Lambda is blocked

The same image runs on **ECS Fargate** or **App Runner** with no changes except
serving via `uvicorn` instead of the Mangum handler. Switch if Lambda is not
green by **T-8h** — do not spend the final night on packaging.

**S3 alone already satisfies the hackathon's "≥1 AWS service" requirement**, so a
failed deploy costs a submission checklist item, not compliance. If it fails, say
so plainly in the submission rather than shipping a dead link — and make sure the
README stops claiming a deployment exists.

---

## Teardown

```
aws apigatewayv2 delete-api --api-id lg7mjxz6m2 --region eu-central-1
aws lambda delete-function --function-name origin-api --region eu-central-1
aws ecr delete-repository --repository-name origin-lambda --force --region eu-central-1
aws iam delete-role-policy --role-name origin-lambda-role --policy-name origin-s3-access
aws iam detach-role-policy --role-name origin-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name origin-lambda-role
```

**Leave it running until judging closes.**

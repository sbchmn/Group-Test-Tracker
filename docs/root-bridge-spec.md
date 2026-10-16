# Root bridge integration spec

The Root half of this integration is a TypeScript bot hosted inside Root's own cloud. It is the only component that can read from or write to a Root community, and Group Test Tracker can neither reach into Root nor be reached by it. So the topology is inverted relative to Telegram and Discord: the bridge initiates every connection, POSTs normalized inbound chat events to us over HTTPS with an HMAC signature on each request, and polls us for outbound messages it then posts into a Root channel. Nothing in this repo pushes anything to the bridge.

```
 Root community (channels, members, messages)
          |
          |  Root in-process SDK only (@rootsdk/server-bot)
          v
 Root-hosted bridge bot  (TypeScript / Node, runs in Root's cloud)
          |
          |  HTTPS POST, one HMAC-SHA256 signature per request
          |  -> events in,  <- outbox messages out
          v
 Group Test Tracker  (Flask, /root/webhook + /root/outbox/*)
```

Contents

- [Why this looks backwards](#why-this-looks-backwards)
- [Configuration and tenancy](#configuration-and-tenancy)
- [Request signing](#request-signing)
- [Endpoints](#endpoints)
- [Delivery lifecycle and lease rules](#delivery-lifecycle-and-lease-rules)
- [Commands supported today](#commands-supported-today)
- [Account linking](#account-linking)
- [What the bridge must degrade](#what-the-bridge-must-degrade)
- [Security requirements for the bridge](#security-requirements-for-the-bridge)
- [Testing checklist](#testing-checklist)
- [Out of scope](#out-of-scope)
- [Changes from the old design](#changes-from-the-old-design)

Source of truth in this repo: `app/root_bridge.py` (signing scheme), `app/root_routes.py` (the four endpoints), `app/models.py` (`RootOutbox`, `RootBridgeNonce`, `RootInboundEvent`, `User.root_user_id`), `app/bot_channels.py` (what "configured" means), `app/bot_identity.py` (link tokens), `migrations/versions/c8e2f5b7d3a9_add_root_bridge_schema.py` (schema). Where this document and that code disagree, the code is correct and this document is the bug.

## Why this looks backwards

These are Root platform limits, confirmed against docs.rootapp.com on 2026-09-18. They are not quirks of our design; the design is a consequence of them.

- **Root has no inbound webhooks.** Root's own wording: "Inbound webhooks do not exist. There is no address an outside service can POST to in order to reach your App, your Bot or a channel." Group Test Tracker can never push a message into Root. This is the entire reason there is an outbox table and a polling protocol here, where Telegram and Discord get a direct `sendMessage` call.
- **Bot code must be hosted by Root** (TypeScript on Node, in Root's cloud, deployed with `rootsdk build package` then `rootsdk upload`). There is no external REST API our Python can call, so the bridge is the only thing with a Root-side voice. Root-hosted code may call out to an external web service, which is what this spec uses.
- **A bot cannot set an author name or avatar.** Root's wording: "the message always shows your Bot or App as the author". See [Changes from the old design](#changes-from-the-old-design).
- **Bots get no in-message buttons or interactive components.** Only a Root *App* — a separate registration — gets a GUI, and an App's UI lives in its own channel rather than attaching controls to a message. Anything our web UI or Telegram renders as an inline keyboard has to degrade to text. See [What the bridge must degrade](#what-the-bridge-must-degrade).
- **The job scheduler fires "within a window of about one minute"**, and chained `OneTime` jobs are Root's documented polling pattern. Outbound latency therefore has a roughly one minute floor. The bridge polls on that cadence and must never assume it is being pushed.
- **No bot to user DM.** All delivery is to channels. To direct something at a person, post in a channel and `@mention` them.
- **A Bot cannot be converted into an App later** ("Not in place… register a new App and retire the Bot"), and Root-side storage does not survive that move. **Design rule that follows: keep the bridge as close to stateless as possible.** Durable state belongs in Group Test Tracker's database. Root-side `KeyValueStore` should hold only the shared secret, the key id, and at most a last-polled cursor, so losing it costs one re-poll and not a batch of lost messages. The outbox/lease protocol in this repo is explicitly built so a bridge that loses all local state can come back and resume safely.

## Configuration and tenancy

Everything our side reads comes from the shared `notification_configs` key/value table (`NotificationConfig` in `app/models.py`), one row per key. The four keys the bridge touches are named by constants in `app/root_bridge.py:30-33`:

| Config key | Constant | Read by | Purpose |
| --- | --- | --- | --- |
| `root_bridge_key_id` | `BRIDGE_KEY_ID_KEY` | `bridge_credentials()` | Identifies this tenant to the signer. Must match the `X-Root-Bridge-Key-Id` header exactly. |
| `root_bridge_secret` | `BRIDGE_SECRET_KEY` | `bridge_credentials()` | HMAC key for every request the bridge sends. 64 lowercase hex characters (32 bytes, `secrets.token_hex(32)`). |
| `root_community_id` | `BRIDGE_COMMUNITY_KEY` | `bridge_community_id()` | The one community this instance serves. Compared against `communityId` on `/root/webhook` and `/root/outbox/claim`. |
| `root_status_channel_id` | `BRIDGE_STATUS_CHANNEL_KEY` | `bridge_status_channel_id()` | Default target channel for outbound messages queued by `send_root_message()`. Empty means outbound delivery is refused outright. |

Values are read with `str(value).strip()`, so surrounding whitespace in the admin form is tolerated; a blank value is treated as unset.

**One installation per tenant community.** There is no tenant dimension inside the protocol: one key id, one secret, one community id per Group Test Tracker instance. A second community needs a second instance and a second set of credentials. The community id is the only thing separating one tenant's traffic from another's at the HTTP layer, so the bridge must send the community id on every event and every claim.

**Credential generation.** An administrator mints the pair from the bot integrations screen — `POST /admin/settings/bots/root/bridge-credentials` (`app/routes.py:4566`), which calls `generate_bridge_key_id()` (`root-` plus 12 hex characters) and `generate_bridge_secret()`, stores both, and renders them exactly once in `app/templates/admin/root_bridge_credentials.html`. After that every view shows the secret masked. There is no way to read the stored secret back out of the UI: losing it means generating a new pair and updating the bridge, never recovering the old value. The admin pastes both values into the bridge's own Root-side settings. The bridge must not derive, guess, or persist them anywhere else.

**Entitlement gate — read this before planning a deploy.** `app/bot_channels.py` declares the `root` channel with `required_keys=("root_bridge_key_id", "root_bridge_secret", "root_status_channel_id")` and `entitlement="discord_bot"`. Root is deliberately **not** a separately-sold feature key: it rides the existing Discord bot entitlement, so a tenant on Core + Discord can use Root with no new control-plane provisioning. `entitlement_enabled()` in `app/saas.py:70` **fails closed for managed tenants**: when `GTT_DEPLOYMENT_MODE=managed`, a feature is on only if its name appears in the comma-separated `GTT_ENTITLEMENTS` environment variable. Consequences:

- Until the tenant's `GTT_ENTITLEMENTS` includes `discord_bot`, `root_in_plan` is false, so the admin UI hides the Generate Bridge Credentials button, refuses the endpoint with `404`, and refuses to write any of the four config keys. No credentials can be created, so every bridge request is rejected with `403` ("bridge is not configured").
- In `standalone` mode (`GTT_DEPLOYMENT_MODE` unset or anything other than `managed`) entitlements are not consulted and the feature is simply available.
- **No new entitlement key is required.** A managed tenant needs the same `discord_bot` entry it already needs for the Discord bot; there is no `root_bot` key in this codebase and adding one to `GTT_ENTITLEMENTS` would do nothing. Turning `discord_bot` off for a tenant also hides and blocks the Root admin screens — but see the asymmetry below, which means it does not stop an already-configured bridge.
- Note the asymmetry: the gate is enforced on the *admin* routes only. `app/root_routes.py` does not consult the entitlement; it authenticates against the stored secret. If credentials exist in the database the bridge endpoints serve them even if the plan no longer lists `discord_bot`. **Rotating the secret to a new value is the only off switch reachable from the UI** — the admin form treats a blank `root_bridge_secret` or `root_bridge_key_id` as "keep the stored value", for the same reason it treats the masked echo that way: a form rendered before a generation posts the pair back blank, and storing that would destroy a working credential while reporting success. Clearing either key to NULL has to be done in the database.

## Request signing

Implemented in `app/root_bridge.py`; reproduced here so a TypeScript implementation can be byte-exact. There is no handshake, no session, and no token exchange: each request stands on its own signature.

### Headers

Every request must carry all four. A missing or blank one is rejected (`root_bridge.py:121-129`).

| Header | Value |
| --- | --- |
| `X-Root-Bridge-Key-Id` | The configured key id, verbatim. |
| `X-Root-Bridge-Timestamp` | Decimal Unix seconds, UTC, no milliseconds, no padding. Example `1789747200`. |
| `X-Root-Bridge-Nonce` | Unique per request, 16 to 128 characters inclusive. Use 32 lowercase hex characters (16 random bytes), which is what our own reference client generates (`ROOT_NONCE_BYTES = 16`, `secrets.token_hex`). |
| `X-Root-Bridge-Signature` | The hex digest described below, lowercase. |

Header names are matched case-insensitively by the framework, but send them exactly as written above.

### Canonical string

Seven fields joined with a single `\n` (U+000A), in this order, with **no trailing newline**:

1. `root-bridge-v1` — the literal contract version (`ROOT_CONTRACT_VERSION`). Not the SDK version, not a header; a fixed string, first, always.
2. HTTP method, upper-case. Today every route is `POST`.
3. The request path only — `/root/webhook`, `/root/outbox/claim`, `/root/outbox/ack`, `/root/outbox/stats`. No scheme, host, port or query string (our blueprint is registered without a URL prefix, so the path is exactly the route).
4. The key id, identical to the header.
5. The timestamp, identical to the header.
6. The nonce, identical to the header.
7. The body digest: lowercase hex SHA-256 of the **raw request body bytes**.

Because the version prefix is a fixed first field and the separator is fixed, no field value can be re-shaped into another field's position.

### The MAC

```
signature = hex( HMAC-SHA256( key = utf8(secret), message = utf8(canonical_string) ) )
```

Lowercase hex, 64 characters, no `sha256=` prefix, no separators.

### Limits and windows

| Constant | Value | Meaning for the bridge |
| --- | --- | --- |
| `ROOT_SIGNATURE_WINDOW_SECONDS` | 300 | `abs(server_now - timestamp) > 300` is rejected. The check is symmetric, so a clock up to 300 s fast is also accepted; do not exploit that. |
| `ROOT_MAX_BODY_BYTES` | 65536 | Bodies above 64 KiB are rejected before verification. Keep request bodies well under this. |
| nonce length | 16..128 chars | Outside that range is rejected regardless of signature validity. |
| nonce lifetime | stored, single-use | Each `(key_id, nonce)` pair is recorded in `root_bridge_nonces` as `sha256("key_id:nonce")` with an `expires_at` of `now + 600 s`. Reusing one is rejected even with a perfect signature. |

The bridge must assume the replay window is a hard 600 s on our side and that every accepted request leaves a row behind. Note for the operator rather than the implementer: `prune_expired_nonces()` (`app/root_bridge.py:182`) exists but has no caller in this repo yet, so `root_bridge_nonces` grows until something schedules it.

Timestamps are compared against `datetime.now(timezone.utc)`, so the bridge's clock must be NTP-synced. `/root/outbox/stats` returns `serverTime` for drift debugging — see the parsing warning in that section.

### Verification order, and the generic 403

`verify_bridge_request()` (`root_bridge.py:142`) runs these checks **in this order** and raises on the first failure:

1. Is a key id and secret configured on this instance?
2. Are all four headers present and non-blank?
3. Does the key id match (`hmac.compare_digest`)?
4. Is the timestamp an integer?
5. Is it inside the 300 s window?
6. Is the nonce length usable?
7. Does the signature match a freshly computed one?
8. Has this nonce been used before?

In addition, before verification, `app/root_routes.py:44-71` rejects a zero-length body (`"empty request body"`), a body over 65536 bytes, and — after verification — a body that is not UTF-8 JSON or not a JSON *object*.

**Every one of those failures produces the same response**: `403` with `{"ok": false, "error": "request rejected"}`. No detail, no hint, no distinguishing status code. The specific reason is written to our notification log, which the bridge cannot see. Debugging is therefore a matter of checking each step yourself, in order, against the vectors below. A `403` on a request that "obviously" signs correctly is almost always one of: signing a re-serialized body instead of the bytes actually sent, a trailing newline in the canonical string, a query string in the path, a timestamp in milliseconds, or an uppercase hex digest.

The nonce is consumed only when the request is accepted. If JSON parsing fails after verification, the transaction is rolled back and the nonce is *not* burned, so fixing the body and retrying with the same nonce is allowed — but do not rely on that; use a fresh nonce per attempt.

### Reference vectors

All four use the same configured pair. These values are synthetic example credentials, not a live secret:

```
key id  = root-6a1c0d2e4f5a
secret  = 9c4b1f0a3d7e58c2b6a0f41d8e3572cb4a19d0e7c3f82b6541a0de7c9b8f3520
timestamp = 1789747200              (2026-09-18T16:00:00Z)
version   = root-bridge-v1
```

Compute each with a distinct nonce. The bodies below are exactly as they must appear on the wire: UTF-8, no trailing newline, compact JSON with no spaces after `:` or `,`, and keys in the shown order. Change one byte and the digest — and therefore the signature — changes.

**1. `POST /root/webhook`** — body (223 bytes):

```
{"event":"channelMessage.created","communityId":"0198ac00-7f3c-7000-8000-0001","channelId":"0198ac00-7f3c-7000-8000-00e2","messageId":"0198ac00-7f3c-7000-8000-0777","userId":"0198ac00-7f3c-7000-8000-0a01","content":"/help"}
```

```
nonce   = 7c1f9a4e03b6d2558f1ac0e7b4d39206
digest  = 1084fb2e80306013ad87c75b1b76cb7d6e3c0abfcff18c89c2cb8bae853a6e6f
signature = 03bf11c055592953791d00989a89cea6ba1cc7c26047b01de874400dd5b66d53
```

**2. `POST /root/outbox/claim`** — body (56 bytes):

```
{"communityId":"0198ac00-7f3c-7000-8000-0001","limit":5}
```

```
nonce   = b52e08af7dc413e9906b2c5d8e471fa0
digest  = 7c3c199a586e621d53efa66909d5054b5be25364993cd7d6ef516a35fd723eea
signature = 52d03efed1821690cc0832c88c37a04d0f6a1667aafc5486feba6a41636b2a80
```

**3. `POST /root/outbox/ack`** — body (154 bytes):

```
{"leaseToken":"ZmFrZS1sZWFzZS10b2tlbnMxMjM0NTY3ODl0aGlz","results":[{"id":101,"delivered":true},{"id":102,"delivered":false,"error":"channel not found"}]}
```

```
nonce   = 4d90ce17b8a6f205c31d7e9a04b6f82c
digest  = f3512f47744292508b73a57b7f138972cc6184361368e58ef961de8a9af64f1a
signature = 9252261947bb07a79b8b61906b0a95a3ec7011b299df012052bb490df0178781
```

(The `leaseToken` above is a made-up 40-character string, legal only as an opaque body value. A real one is 24 characters from `secrets.token_urlsafe(18)`, and the `lease_token` column holds up to 64; it is signed only as part of the body, never as a header.)

**4. `POST /root/outbox/stats`** — body `{}` (2 bytes). This is the minimum legal "empty" poll: a zero-length body is rejected, so always send at least `{}`.

```
nonce   = e1a7f30c9b2548d6af0e1c7d3904b5e8
digest  = 44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a
canonical string (newlines shown escaped) =
  root-bridge-v1\nPOST\n/root/outbox/stats\nroot-6a1c0d2e4f5a\n1789747200\ne1a7f30c9b2548d6af0e1c7d3904b5e8\n44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a
signature = 6f42c2ec236c60adac6c686877ad4a553f9fe49bef8c0d9d5c8cd390afeffd35
```

Note the last digest: `44136fa3...` is the SHA-256 of the two bytes `7b 7d`. It is *not* the empty-body digest `e3b0c442...`, because the body is `{}`, not empty.

### TypeScript

```ts
import { createHmac, createHash, randomBytes } from "node:crypto";

const VERSION = "root-bridge-v1";

/** body must be the exact string passed to fetch(); never sign an object. */
export function sign(
  cfg: { keyId: string; secret: string },
  path: string,
  body: string,
): Record<string, string> {
  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = randomBytes(16).toString("hex");          // 32 hex chars
  const digest = createHash("sha256").update(body, "utf8").digest("hex");
  const canonical = [
    VERSION, "POST", path, cfg.keyId, timestamp, nonce, digest,
  ].join("\n");
  const signature = createHmac("sha256", cfg.secret).update(canonical, "utf8").digest("hex");
  return {
    "X-Root-Bridge-Key-Id": cfg.keyId,
    "X-Root-Bridge-Timestamp": timestamp,
    "X-Root-Bridge-Nonce": nonce,
    "X-Root-Bridge-Signature": signature,
    "Content-Type": "application/json",
  };
}

export async function callGtt(cfg: { baseUrl: string; keyId: string; secret: string },
                              path: string, payload: unknown): Promise<Response> {
  const body = JSON.stringify(payload ?? {});   // no undefined keys: they vanish and change the digest
  return fetch(cfg.baseUrl + path, {
    method: "POST",
    headers: sign(cfg, path, body),
    body,
  });
}
```

Two ways this goes silently wrong: `JSON.stringify` dropping keys whose value is `undefined` (so the signed string is not what you meant to send), and any later re-encode of `body` before it reaches `fetch`. Build the string once, sign that string, send that string.

Self-check against the vectors above: `callGtt` with the example credentials, `path = "/root/outbox/stats"`, `payload = {}` and the nonce/timestamp pinned to the vector's values must produce `6f42c2ec236c60adac6c686877ad4a553f9fe49bef8c0d9d5c8cd390afeffd35`.

### curl-equivalent

`path`, `key id`, `timestamp`, `nonce` and `body` are the vector's literal values (`{}`), and the last line must print the vector's signature. `printf` is used rather than `echo` so no trailing newline is added to the signed bytes.

```sh
SECRET=9c4b1f0a3d7e58c2b6a0f41d8e3572cb4a19d0e7c3f82b6541a0de7c9b8f3520
KID=root-6a1c0d2e4f5a
TS=1789747200
NONCE=e1a7f30c9b2548d6af0e1c7d3904b5e8
BODY='{}'

DIGEST=$(printf '%s' "$BODY" | openssl dgst -sha256 -hex | awk '{print $NF}')
SIG=$(printf 'root-bridge-v1\nPOST\n/root/outbox/stats\n%s\n%s\n%s\n%s' \
        "$KID" "$TS" "$NONCE" "$DIGEST" \
      | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $NF}')

curl -sS -X POST https://gtt.example/root/outbox/stats \
  -H "X-Root-Bridge-Key-Id: $KID" \
  -H "X-Root-Bridge-Timestamp: $TS" \
  -H "X-Root-Bridge-Nonce: $NONCE" \
  -H "X-Root-Bridge-Signature: $SIG" \
  -H 'Content-Type: application/json' \
  --data "$BODY"
```

Against a live instance with that key id and secret configured, and a `TS` inside 300 s of the server's clock (so regenerate `TS`, `DIGEST` and `SIG` together with a fresh `NONCE`), this returns `{"ok":true,...}`. `https://gtt.example` is a placeholder for the tenant's public base URL; the admin sets it in `service_base_url`.

## Endpoints

Registered by the `root` blueprint with no URL prefix (`app/__init__.py:187-188`), all `POST`, all CSRF-exempt, all signature-authenticated. Wire field names are camelCase and exact — do not rename them, and do not add your own and expect them to be read. Unknown fields are ignored. Any authentication failure is `403 {"ok": false, "error": "request rejected"}`; the reason is only in the response for the non-auth refusals noted per endpoint, which use the same generic body anyway.

Status codes you should handle: `200` (processed), `403` (rejected for any auth or validation reason), `405` (wrong method), `413` (body over the app-wide `MAX_CONTENT_LENGTH`, which is 12 MB by default — you should never get there; above 64 KiB you get `403` first), and `500` (unexpected failure; treat it as a retry).

### `POST /root/webhook`

Purpose: deliver one normalized event, usually a channel message. Implemented at `app/root_routes.py:124-179`.

Request fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `communityId` | string | **yes** | Must equal the configured `root_community_id` after trimming, and the instance must have one bound. A mismatch is rejected — this is the tenant boundary. |
| `messageId` | string | **yes** | Root's message identifier. Non-empty after trimming. Dedupe key; keep it under 120 characters (column limit, and replies derive a 120-character `event_key` from it). |
| `event` | string | recommended | Event name. **The wire field is `event`, not `eventType`.** Stored truncated to 60 characters. Only the exact value `channelMessage.created` triggers command handling. |
| `channelId` | string | recommended | Channel the message came from, truncated to 120 on storage. A reply can only be queued if it is present. |
| `userId` | string | recommended | The Root user guid of the sender, truncated to 40 on storage. This is the only identity our side trusts, and it comes from the bridge's translation of the Root event — never from message text. |
| `content` | string | recommended | Plain message text, truncated/stripped before matching. Leading whitespace is stripped, so a command must be the first thing in the message. |

Response:

- `200 {"ok": true}` — accepted, and processed. A reply, if any, has been queued to the outbox; it has not been posted to Root yet.
- `200 {"ok": true, "duplicate": true}` — `messageId` was already in `root_inbound_events`. **Not an error. Do not retry it**; the first delivery was accepted and any queued reply already exists. Retry on this response loops forever.
- `403 {"ok": false, "error": "request rejected"}` — signature failure, missing `messageId`, wrong community, or no community bound on this instance.

Idempotency: keyed on `messageId`, unique in the database. The dedupe row is written for *any* event carrying a `messageId`, not only messages, and is committed in the same transaction as any queued reply — so a rollback leaves nothing behind and the event can be re-sent. An event with no `messageId` is refused outright, so make the bridge skip events it cannot identify rather than inventing a synthetic id (a synthetic id would poison the ledger for repeats).

### `POST /root/outbox/claim`

Purpose: pull up to `limit` messages to deliver. `app/root_routes.py:181-230`.

Request fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `communityId` | string | **yes** | Compared against the configured value; a mismatch rejects and nothing is handed out. |
| `limit` | integer | no | Default 5 when absent, null or unparsable; clamped to 1..20. |

Response `200`:

```json
{
  "ok": true,
  "leaseToken": "ZmFrZS1sZWFzZS10b2tlbnM",
  "messages": [
    { "id": 101, "channelId": "0198ac00-7f3c-7000-8000-00e2", "body": "Group Test Manager: ..." }
  ],
  "retryAfterSeconds": 120
}
```

- `leaseToken` — opaque string (24 characters from `secrets.token_urlsafe(18)`, alphabet `A-Za-z0-9-_`). Send it back verbatim in the ack. It is not a bearer credential: without the signature it grants nothing.
- `messages[].id` — JSON **number**, the `root_outbox` primary key.
- `messages[].channelId` — where to post. Root `ChannelGuid` as stored.
- `messages[].body` — plain text, post it as-is. It may already contain absolute URLs (see the degradation table).
- `retryAfterSeconds` — the lease duration in seconds, from the Flask config `ROOT_OUTBOX_LEASE_SECONDS`, default `120`. Nothing in `app/__init__.py` sets that key today, so expect `120`. It is a hint for how long you have to finish, not a poll interval; Root's scheduler granularity (about a minute) sets that.

An empty `messages` array with a valid `leaseToken` is the normal idle response, not an error. Ordering is `created_at` ascending, so oldest first.

### `POST /root/outbox/ack`

Purpose: report delivery results. `app/root_routes.py:232-277`.

Request fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `leaseToken` | string | **yes** | The token from the claim that produced these ids. Non-empty after trimming. |
| `results` | array | **yes** | Must be a JSON array; anything else is rejected. Entries are objects. |
| `results[].id` | number | yes | The id from the claim. Strings that look like integers are coerced; anything unparsable is skipped. |
| `results[].delivered` | boolean | yes | Truthy means posted to Root successfully. |
| `results[].error` | string | on failure | Free text, stored truncated to 300 characters in `last_error`. |

Note `ack` and `stats` do **not** read `communityId`. The lease token is the only correlation, which is what stops one lease's ack from touching another's rows. Send the field anyway for log legibility; it is simply ignored.

Response: always `200 {"ok": true}` once authentication and the two structural checks pass. There is no per-result verdict. Results whose `id` is unknown, or known but carrying a different `lease_token`, are **silently skipped** — which is how a late ack from a superseded lease is neutralised. Do not assume `{"ok": true}` means any given row was updated; if you need to confirm, call `stats` and watch the counters.

Idempotency: safe to re-send. After a successful ack the row's `lease_token` is cleared, so a repeat ack matches nothing. A re-acked row that has meanwhile been re-claimed under a new token will not be touched by the old ack.

### `POST /root/outbox/stats`

Purpose: counters for the bridge's own debug logs. `app/root_routes.py:279-293`.

Request: must still be a signed, non-empty JSON object. `{}` is sufficient. No field is read — including `communityId`.

Response `200`:

```json
{ "ok": true, "pending": 4, "sent": 812, "failed": 1, "serverTime": "2026-09-18T16:00:00.123456" }
```

- `pending` counts rows in `pending` **plus** `claimed`, so it is "not yet finally sent or failed", not "unclaimed".
- `sent` / `failed` are lifetime counters over the whole table. Nothing prunes them.
- `serverTime` is a naive ISO-8601 UTC timestamp with microseconds and **no `Z` suffix and no offset**. In JavaScript `new Date("2026-09-18T16:00:00.123456")` parses that as *local* time. Append `Z` before parsing if you use it to measure clock drift.

## Delivery lifecycle and lease rules

`RootOutbox` (`app/models.py:459-486`, migration `c8e2f5b7d3a9`) has four statuses: `pending`, `claimed`, `sent`, `failed`.

```
                       claim                 ack delivered=true
  queued in outbox --> [pending] ----> [claimed] ------------------> [sent]  (terminal)
                          ^                |
                          |                | ack delivered=false, attempt_count < max_attempts
                          +----------------+   status=pending, next_attempt_at = now + backoff
                          ^                |
                          |                | ack delivered=false, attempt_count >= max_attempts (5)
                          |                v
                          |             [failed]  (terminal)
                          |
                          +-- re-claim (see lease caveats below)
```

- **Queueing.** Two paths create rows: `send_root_message()` (`app/notifications.py:752-770`) writes the configured status channel with `event_key = NULL`; the command replies from `/root/webhook` write the *originating* channel with `event_key = "evt:" + messageId`. Because `event_key` is unique, one inbound message can produce at most one reply row.
- **Claim.** Sets `status = claimed`, increments `attempt_count` by one, sets `lease_token` and `lease_expires_at = now + lease_seconds`. Rows are selected when `status` is `pending` or `claimed` and any of: `next_attempt_at IS NULL`, `next_attempt_at <= now`, `lease_expires_at < now`.
- **`attempt_count` / `max_attempts`.** `max_attempts` defaults to 5 per row (`app/models.py:479`) and is never changed by the bridge. The counter is incremented at *claim* time, so a message that is never acked still burns attempts.
- **Backoff, as actually implemented** (`app/root_routes.py:273`): `next_attempt_at = now + min(300, 15 * 2 ** attempt_count)` seconds, where `attempt_count` is the value already incremented by the claim that just failed. Concretely: after the 1st failed attempt 30 s, 2nd 60 s, 3rd 120 s, 4th 240 s; a 5th failure takes the `attempt_count >= max_attempts` branch and the row goes to `failed`. The 300 s cap only matters if `max_attempts` is raised on a row.
- **Lease lapse.** If the bridge claims rows and never acks them, `lease_expires_at` passes and the rows become claimable again. **If your bridge crashes between claim and ack, do nothing at restart — no recovery call, no state to replay.** The lease lapses and another poll re-claims the rows. That is the whole point of the design and the reason Root-side state can be disposable.

  One real caveat, from the shape of the claim filter: a freshly queued row has `next_attempt_at = NULL`, and `next_attempt_at IS NULL` satisfies the `or_` on its own — so a row that is currently `claimed` with a live lease and a null `next_attempt_at` is **immediately re-claimable by a second concurrent poll**. Run **exactly one** bridge instance per tenant, and finish or abandon a claim before the next scheduled poll fires. If two instances ever poll at once, the failure mode is duplicate posting into the channel, not lost messages — which is the lesser evil, but visible to users. The lease only behaves as an exclusive lock for rows that already have a `next_attempt_at` (i.e. rows that previously failed).

- **Terminal `failed` rows are not automatically retried.** They stay `failed` until an operator intervenes in the database. Surface `failed` from `stats` in the bridge's logs.

**What "sent" means.** Our side records `sent` when the bridge reports success — see `send_root_message`'s own docstring in `app/notifications.py:752-757`: "True means the message was accepted for delivery, not that it landed in a channel." The same applies to the outbox status. Anything the bridge or our UI words as "sent" is approximate: it means posted and acked, and Root's own client may still render it late or not at all if the channel is gone. When a post fails on the Root side, report `delivered: false` with the Root error text rather than swallowing it — that is the only path by which a stuck message becomes visible.

## Commands supported today

`/root/webhook` handles exactly three cases, and only when `event == "channelMessage.created"` and the trimmed `content` starts with `/` (`app/root_routes.py:159-174`):

| Command | Behaviour |
| --- | --- |
| `/help` | Replies with the static help text from `_handle_help()`: the line `Group Test Manager on Root:`, then `/start <token> - link your Root account to your profile`, then `/help - show this message`; and, when the sender's `userId` is not linked to any `User.root_user_id` (including when `userId` is empty), a blank line plus `You are not linked yet. Open your profile, generate a link token, then send /start <token>.` |
| `/start <token>` | Account linking, see below. Replies `Your Root account is linked to <username>. Use /help to see available commands.` on success. |
| anything else starting with `/` | `Group Test Manager is not wired to that command yet. Try /help, or /start <token> to link your account.` (the `ROOT_COMMAND_HINT` constant, `app/root_routes.py:38-41`, quoted verbatim). |

Details the bridge depends on:

- Command matching is on the lower-cased first whitespace-separated token, so `/HELP` and `/Help extra` match `help`. `/help me` treats `me` as an ignored argument.
- Because the check is `content.startswith("/")`, a message that mentions the bot first (`@someone /help`) is **not** a command and is silently accepted with `{"ok": true}` and no reply. If Root delivers mention text inline in `content`, the bridge must decide whether to strip a leading bot mention before forwarding — that decision is currently the bridge's, and our side does not do it.
- Non-command messages (content not starting with `/`) are accepted, recorded in `root_inbound_events`, and produce no reply. Anything not `channelMessage.created` is likewise recorded and ignored. Do not build the bridge to expect a `4xx` for ignored events.
- A reply is only queued when the event carried a `channelId`. An event with no channel is accepted and answered with silence.

Full command parity with the Telegram and Discord bots is **not** in this repo yet: it lands when the shared command resolver is extracted (referred to in `app/root_routes.py:34-36` as "Phase 1 increment 3"). Build the bridge to forward **any** slash command through unchanged, with no command list compiled into it, so that parity arrives without a bridge release.

## Account linking

Same contract as Telegram and Discord: a member generates a single-use token on their own profile page in Group Test Tracker, then sends it to the bot; the bot's user id is then attached to that member's account. `/start <token>` is handled by `app/root_routes.py:93-106` → `claim_link_token("root", token, external_id=userId)` in `app/bot_identity.py`.

Flow:

1. Member opens their profile page in Group Test Tracker and requests a Root link token.
2. The page shows `/start <token>` where `<token>` is an opaque single-use string (32 URL-safe characters from `secrets.token_urlsafe(24)`).
3. Member sends that message in a Root channel; the bridge normalizes it and POSTs it to `/root/webhook` with their Root user id in `userId`.
4. Our side selects the `BotLinkToken` row with `provider = 'root'` and that token **under a row lock** (`with_for_update()`), so concurrent delivery cannot consume one token twice.
5. On success the member's `User.root_user_id` (`app/models.py:54`, unique, indexed) is set to the `userId`, and `used_at` is stamped.
6. The bridge picks up the confirmation from the outbox on its next poll and posts it.

Rules:

- **Provider-scoped.** Tokens are stored with their provider. A token minted for Telegram or Discord cannot be redeemed over `/root/webhook`, and vice versa — the lookup filters on `provider`, so a cross-platform token is simply "not found".
- **Single-use.** Once `used_at` is set the token is dead. Re-sending `/start <token>` gets the invalid-or-expired reply.
- **24 hour expiry** (`LINK_TOKEN_TTL` in `app/bot_identity.py`). An expired token behaves exactly like an invalid one.
- **Ownership is not moved silently.** A claim is refused (leaving the token unconsumed) if that Root user id is already linked to a different member, or if the member is already linked to a different Root user id.
- **No identity, no claim.** An event that arrives with an empty `userId` is refused **before** the token is looked up, so the token stays usable: `Group Test Manager could not identify your Root account, so it cannot link it. Ask an administrator to check the bridge configuration.` There is nothing to link without an id, and consuming a single-use token to say so would leave the member unlinked with no way to retry. Emit `userId` on every `/start` event.
- **Deactivated accounts are refused** with a distinct message: `This account is deactivated. Contact an administrator for account support.`
- Every other refusal — invalid, expired, cross-owned, missing user — is answered with the same text: `This link token is invalid or expired. Generate a new one from your profile page.` Our side deliberately does not distinguish them to the requester.

**Not finished on our side.** `app/bot_identity.py` now lists `root` in `LINK_FIELDS` with only an `external_id` mapping (no `chat_id`, no username column — Root has no DM chat and no display-handle field we store), so the *claim* half works. The *issue* half does not: the profile view only looks up `telegram` and `discord` tokens (`app/routes.py:1608-1613`) and the only two issuing routes are `/profile/telegram-link-token` and `/profile/discord-link-token` (`app/routes.py:1630` and `app/routes.py:1648`), so there is currently no supported way for a member to obtain a `provider='root'` token. Until that is added, `/start <token>` in Root always answers "invalid or expired". The bridge should implement the flow anyway — it cannot be blamed for a token it was never given.

**Exposure note.** Root has no bot-to-user DM, so `/start <token>` is necessarily posted where the bridge forwards it — usually a channel other members can read. Tokens are single-use and expire in 24 hours, but a leaked token lets an attacker bind *their* Root account to *your* Group Test Tracker identity. Forward `/start` events from the least-read channel available, and prefer a channel with restricted membership; our side does not restrict which channel the command may arrive from.

## What the bridge must degrade

| Feature elsewhere | Telegram / Discord do | Root bridge must |
| --- | --- | --- |
| Inline keyboards, link buttons | Interactive message components | Render plain text with the full absolute `https://` URL inline. Our templates are already told to include a URL, not a button definition. Do not invent a marker like `[Open]` and expect a client to act on it. |
| Sender display name / avatar | Set per message | Nothing. Root always shows the Bot as author, and the Bot cannot override it. Do not try to prefix a fake display name into the body — it reads as a user impersonating another user. |
| Per-user DM | `sendMessage` to a chat id | Post into a channel and `@mention` the person. Root's per-user primitive is `NotificationSendRequest` (a device notification, title 50 / description 150 characters, no deep link for bots), which is not a chat message and is not implemented on our side. |
| Instant delivery | Push on demand | Poll, at Root's roughly one-minute scheduler cadence. Design status messages to be tolerable minutes late. |
| Attachments | Upload or link a file | `POST /root/webhook` has no attachment field at all, so inbound media (`messageUris`) is currently dropped; outbound media must be a plain URL in `body`. |

## Security requirements for the bridge

- Never log the secret, and never log a signed canonical string alongside it. Log the key id if you must log anything.
- Store the secret in Root-side settings (the bridge's own configuration / `KeyValueStore`), never in source, never in the repo that builds the package.
- Sign **every** request, including a poll with nothing to say. `POST /root/outbox/stats` with body `{}` is still a signed request. Unsigned requests get the generic `403`.
- Use a fresh nonce per request — 16 random bytes rendered as 32 lowercase hex characters. A reused nonce inside the 600 s retention window is rejected even when the signature is correct.
- Treat `403` as a configuration error, not a transient one. Back off with a long, jittered delay and stop after a handful of attempts; do not retry on the one-minute cadence. Repeated authenticated-but-rejected traffic is written to our notification log and does nothing but burn replay capacity. `403` on `/root/webhook` *except* the duplicate case is never a reason to re-POST the message.
- Verify TLS. Pin nothing fancy, but do not disable certificate validation to get through a proxy. The HMAC protects request integrity, not transport confidentiality of the body.
- Never derive identity from message content. `userId` comes from Root's own event object as translated by the bridge. If a member types someone else's user id into a message, that string is text and nothing more — our side only ever reads the `userId` field.
- Do not widen the payload. Send the documented fields; do not forward message bodies, tokens, or Root credentials you have no use for. The link token in a `/start` event is the one secret that legitimately passes through, and it must not be logged.

## Testing checklist

No test in this repo currently covers the four endpoints or the HMAC scheme (`tests/test_bot_channels.py` covers the config-key set and the entitlement; `tests/test_notifications.py:482-521` covers outbox queueing and the no-status-channel refusal; `tests/test_bot_identity.py` covers token issuing and claiming). Python's own reference implementation is `app.root_bridge.sign_request()` and `app.root_bridge.request_headers()` — use those plus the vectors in [Request signing](#request-signing) as the oracle until HTTP-level tests exist. Every negative below is indistinguishable from every other at the endpoint (`403`, generic body), so assert on the status code and on the absence of a side effect, not on the error text.

Adversarial:

1. Unsigned request → `403`, nothing stored.
2. Correct shape, wrong secret → `403`, no `root_inbound_events` row.
3. Correct secret, key id changed → `403`.
4. Body re-serialized (key order swapped, or whitespace added) after signing → `403`.
5. Path changed (e.g. signed `/root/webhook`, sent to `/root/outbox/claim`) → `403`.
6. Timestamp 301 s stale, and 301 s fast → `403` both. Exactly 300 s → accepted (the comparison is `>`, so 300 is inside).
7. Non-m-numeric timestamp → `403`.
8. Nonce of 15 characters, and of 129 → `403`.
9. Same nonce twice, signature recomputed correctly the second time → `403` on the replay.
10. Zero-length body → `403`. Body of `{}` → accepted.
11. Body that is a JSON array or a JSON scalar → `403`.
12. `communityId` from another tenant → `403`, and no dedupe row written.

Happy path and lifecycle:

13. Sign and POST `/root/outbox/stats` → `200` with all four keys present.
14. Queue a message (`/root/webhook` with `/help`, or the admin "Queue Test Message" action) → `claim` returns it with `id`, `channelId`, `body` → `ack` it `delivered: true` → `stats` shows `sent` incremented and `pending` decremented.
15. `ack` with `delivered: false` → the row returns to `pending` with `next_attempt_at` about 30 s out; `claim` inside that window does not return it, `claim` after does.
16. Five consecutive failed attempts → row reaches `failed` and `stats.failed` increments; further claims never return it.
17. Claim and then never ack → after the lease (120 s default) the row is claimable again with `attempt_count` already incremented.
18. POST the same `messageId` twice → second response is `200 {"ok": true, "duplicate": true}` and only one reply row exists (`event_key` is unique).
19. `/start <token>` with a token minted for `telegram` → the invalid-or-expired reply, and the telegram token remains unconsumed.
20. A second `/root/webhook` POST while a reply for that message is still queued → no duplicate reply (covered by 18).

## Out of scope

- **Notification body rendering and degradation.** How a rendered notification body is chosen and reformatted per provider (`root_body` templates, `select_template_body`) is our side's problem; the bridge always receives finished text in `body`.
- **The COA review state machine.** Telegram drives it with inline buttons and threaded replies; there is no Root equivalent until the shared resolver and a channel-based review flow exist. Do not design button callbacks.
- **Per-user notifications.** `NotificationSendRequest` (title 50 / description 150 characters) is Root's only per-user primitive and is not implemented anywhere in this repo. Mention it here so nobody invents a DM mechanism: there is no DM. If device notifications are ever wanted, that is a separate spec.
- **Root App GUI.** An App is a different registration with a mandatory client, and a Bot cannot be upgraded into one in place. Out of scope for this bridge.
- **Media and attachment upload/download.** `messageUris` is not carried in the normalized inbound payload and there is no outbound attachment field. Text and URLs only.

## Changes from the old design

The Root integration originally assumed Root was a generic inbound webhook. Git history, `PROJECT_MAP.md` ("Root webhook delivery", lines 10, 119 and 188) and the tests still carry vocabulary from that design. The bridge developer will meet these names and should know they are retired:

- **`root_webhook_name` ("Root Display Name") is structurally impossible** and has been removed from the admin form and template. Root permits no author name or avatar field on a bot message ("the message always shows your Bot or App as the author"), so no value ever had an effect. Ignore any reference to setting it.
- **`root_webhook_url` is gone.** We used to POST `{text, sender}` to an operator-supplied URL. Root cannot receive such a POST, so the key is no longer read, written, or configured, and `is_configured("root")` in `app/bot_channels.py` deliberately rejects a config that only carries `root_webhook_url` (asserted in `tests/test_bot_channels.py:62-63`). The replacement for outbound delivery is this outbox, and the replacement for inbound is `/root/webhook` here — which is an endpoint *we* host, called by *the bridge*. The name is a leftover; it is not a Root webhook.
- **`send_root_message()` now means "queued", not "delivered".** It inserts an outbox row and returns true when the row is accepted (`app/notifications.py:752-770`), instead of making an HTTP call.
- **Published legal text now lags the code.** `app/templates/terms.html` still describes Root as "an outbound notification transport, not an account-login provider" and `app/templates/privacy.html` still describes posting to a destination URL. Inbound commands and account linking contradict both. Those pages need to change with the feature; they are our responsibility, not the bridge's, but flag them if you are reviewing this repo.

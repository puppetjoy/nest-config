# Gmail attachment sending

`google_workspace_gmail_send` sends plain-text or HTML Gmail messages through
the active Hermes profile's OAuth grant. It does not use `gws auth login`, read
a global CLI credential store, or return token material.

## Interface

The existing `to`, `cc`, `bcc`, `from_header`, `subject`, `body`, `html`, and
`thread_id` fields are supported. `attachments` is an optional array whose
items contain:

- `path` (required): an absolute path to a regular, non-symlink file under the
  active profile's `downloads/google-workspace` staging directory. Other
  profile files, including OAuth credentials, cannot be attached.
- `filename` (optional): a safe basename for the MIME part. The local basename
  is used by default.
- `mime_type` (optional): an explicit `type/subtype`. When omitted, the type is
  detected from the filename and falls back to `application/octet-stream`.

Successful calls return `message_id`, `thread_id`, and `idempotency_key`.
Multiple attachments are supported. Their aggregate unencoded source size is
limited to 18 MiB so base64 and MIME overhead remain below Gmail's practical
25 MiB message limit.

When `thread_id` is present, the tool reads the latest message metadata from
that profile's Gmail thread and adds the required `In-Reply-To` and
`References` headers before sending. Gmail also requires the subject to match
the existing thread subject; `THREAD_SUBJECT_MISMATCH` reports the required
subject without sending or reserving the idempotency key. A thread metadata
failure is reported before any send is attempted.

## Retry safety

Pass a stable `idempotency_key` for caller-controlled retries. If omitted, the
tool generates and returns one. The profile-private SQLite ledger binds the key
to the complete message and attachment hashes before contacting Gmail:

- A completed retry returns the original message and thread IDs with
  `duplicate_suppressed: true`.
- A key reused for different content returns `IDEMPOTENCY_KEY_REUSED`.
- A timeout, transport failure, server failure, HTTP 403/408/429 response, or
  process interruption after reservation returns or preserves
  `UNKNOWN_SEND_OUTCOME`. The same key is not sent again, because Gmail might
  already have accepted the first attempt.
- Gmail API execution uses zero automatic retries.

Do not invent a new key after `UNKNOWN_SEND_OUTCOME`; inspect Sent or ask Talon
to reconcile the outcome first.

## Actionable errors

- `ATTACHMENT_NOT_FOUND`: the path is absent or cannot be resolved.
- `ATTACHMENT_NOT_READABLE`: the file exists but cannot be read.
- `UNSUPPORTED_ATTACHMENT_PATH`: the path is relative, outside the profile's
  `downloads/google-workspace` staging directory, a symlink, or not a regular
  file.
- `ATTACHMENT_CHANGED`: the file was replaced after validation and was not
  read. Stage it again before retrying.
- `INVALID_ATTACHMENT_FILENAME` / `INVALID_ATTACHMENT_MIME_TYPE`: correct the
  supplied metadata.
- `ATTACHMENTS_TOO_LARGE`: reduce the aggregate source size below 18 MiB.
- `NOT_AUTHENTICATED` / `MISSING_SCOPE` / `AUTHENTICATION_FAILED`: ask Talon to
  refresh the profile-scoped OAuth grant; do not run a separate `gws` login.
- `THREAD_LOOKUP_FAILED`: Gmail thread metadata could not be read and no send
  was attempted; retry with the same key after correcting access or thread ID.
- `THREAD_SUBJECT_MISMATCH`: use the returned `thread_subject`; no send was
  attempted and the same idempotency key remains usable.
- `INVALID_MESSAGE_HEADERS`: correct malformed address/header values; no send
  was attempted and the same idempotency key remains usable.
- `GMAIL_CLIENT_FAILED`: the profile-scoped Gmail client could not be loaded
  and no send was attempted.
- `GMAIL_REJECTED`: Gmail rejected the request before accepting it; correct the
  message and use a new key.
- `UNKNOWN_SEND_OUTCOME`: do not resend under a new key.

Provider exception bodies are intentionally not returned because they can
contain credential-adjacent details.

## Controlled live acceptance

The acceptance script requires explicit send confirmation and recipient input.
It sends one uniquely named text attachment, reads the returned message from
Gmail, requires the `SENT` label, and verifies attachment filename, MIME type,
and size:

    HERMES_HOME=/home/joy/.hermes/profiles/star \
      /opt/hermes-agent/venv/bin/python \
      spec/app/hermes/google_workspace_gmail_send_acceptance.py \
      --confirm-send \
      --recipient CONTROLLED_ADDRESS \
      --profile-home /home/joy/.hermes/profiles/star

This is a live side effect. Run it only after the implementation is merged,
Puppet deployment is separately authorized, and the controlled recipient is
confirmed. It must not reuse the already-sent Riverdale Park message.

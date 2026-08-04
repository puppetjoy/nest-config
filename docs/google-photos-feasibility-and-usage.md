# Google Photos access for Star: feasibility and safe workflow

Date: 2026-08-04

## Executive finding

“Full Google Photos library access” is no longer available to third-party apps through an official Google Photos API.

Google removed the Library API scopes `photoslibrary.readonly`, `photoslibrary.sharing`, and `photoslibrary` on April 1, 2025. The remaining Library API can list, retrieve, and manage only media and albums created by the calling app. It cannot enumerate or search Joy’s pre-existing library, albums, favorites, people, or shared albums.

The broadest supported immediate path is the Google Photos Picker API:

1. Star creates a Picker session.
2. Joy opens Google’s `pickerUri` while signed in, searches by keyword, date, location, or album title, selects up to 2,000 photos/videos, and taps Done.
3. Star lists safe metadata for that selection and downloads the selected bytes into a profile-local managed batch directory.
4. Star processes those local files using existing image workflows.

This is broad batch selection, not standing full-library visibility. Google’s Picker UI initially shows recent photos; albums and categories are not directly listed, but Joy can search for album titles and select multiple results.

## Download fidelity

Google’s supported Picker base-URL contract is precise:

- Photos: `=d` downloads the photo while retaining EXIF metadata except location metadata.
- Videos: `=dv` returns a high-quality transcoded video, not guaranteed byte-for-byte original video.
- Base URLs are transient and normally remain active for 60 minutes.

The Star tool therefore calls the result a supported download rendition, not an exact cloud-original export. For byte-for-byte archival originals or an entire-library export, use Google Takeout. Takeout can export Google Photos as one or more archives, but it is asynchronous, may take minutes to days, does not support arbitrary date-range exports, and requires Joy’s interactive account/security flow.

## Implemented Star-facing surface

Puppet enables a dedicated `google_photos` toolset only for Star:

- `google_photos_status`
- `google_photos_create_selection`
- `google_photos_selection_status`
- `google_photos_list_selection`
- `google_photos_download_selection`

The toolset:

- uses only `photospicker.mediaitems.readonly`;
- keeps its refresh token separate at `/home/joy/.hermes/profiles/star/google_photos_token.json` with mode `0600`;
- stores downloads below `/home/joy/.hermes/profiles/star/google-photos/imports/<batch>/` with mode `0700` directories and `0600` files;
- does not expose Google media IDs or transient `baseUrl` values in normal tool results;
- writes a local `manifest.json` containing safe handles, filenames, MIME types, dimensions, local paths, byte sizes, SHA-256 checksums, and download-rendition notes;
- exposes no cloud delete, archive, share, publish, edit, upload, or album-membership mutation.

Cloud-destructive or externally visible management remains unavailable by default and must be designed separately around both Google’s current API limits and a fresh trusted approval policy. The remaining Library API could later support app-created albums/content, but cannot manage Joy’s existing library.

## OAuth and deployment handoff

Source deployment and the Star gateway restart require trusted implementation-review acceptance/follow-through. OAuth consent is a separate interactive Joy action.

Prerequisites in Google Cloud:

1. Enable **Google Photos Picker API** on Star’s existing Google Cloud project.
2. Confirm Star’s existing OAuth desktop client and consent screen are the intended app identity.
3. Add only `https://www.googleapis.com/auth/photospicker.mediaitems.readonly` for this Photos flow.
4. If the app is External/Testing, keep Joy as a test user.

After the approved Puppet rollout, Talon generates an authorization URL without printing secrets:

```sh
/opt/hermes-agent/bin/google-photos-oauth \
  --profile-home /home/joy/.hermes/profiles/star \
  --auth-url
```

Joy opens that URL, reviews the Google consent screen, and approves interactively. Google redirects to `http://localhost:1`; a browser connection failure is expected. Joy gives Talon the full final redirect URL through the trusted interactive handoff, and Talon exchanges it without logging the token:

```sh
/opt/hermes-agent/bin/google-photos-oauth \
  --profile-home /home/joy/.hermes/profiles/star \
  --auth-response '<full localhost redirect URL>'
```

Safe status check:

```sh
/opt/hermes-agent/bin/google-photos-oauth \
  --profile-home /home/joy/.hermes/profiles/star \
  --check
```

Do not paste client-secret JSON, auth codes, redirect URLs, access tokens, or refresh tokens into Kanban, Agent Requests, GitLab, logs, or ordinary chat.

## Immediate batch workflow

1. Star calls `google_photos_create_selection(max_items=...)`.
2. Joy opens the returned `picker_uri`, searches/selects the current batch, and taps Done.
3. Star calls `google_photos_selection_status(session_id=...)` until `ready=true`, respecting Google’s returned polling interval.
4. Star calls `google_photos_list_selection(session_id=..., max_items=...)` to inspect bounded safe metadata.
5. Star calls `google_photos_download_selection(session_id=..., batch='descriptive-label')` to download all selected items, or passes handles such as `item-0001` and `item-0004` to download a subset.
6. Star reads the returned `manifest_path` and processes files in the returned `batch_directory`.

A multi-item batch is represented by one private directory and one JSON manifest. Each row has a session-local `item-####` handle and a local file path; handles are not Google media IDs.

## Required live smoke after OAuth

The rollout is not complete until tested through Star’s actual gateway/tool path:

1. `google_photos_status` reports authenticated and no cloud mutations.
2. Create a bounded Picker session (for example, maximum 3 items).
3. Joy selects at least one ordinary, non-sensitive test photo and finishes the session.
4. Star lists the selection and retrieves safe metadata.
5. Star downloads the selected photo into a named managed batch.
6. Verify the file exists, is non-empty, its SHA-256 matches the manifest, and an image decoder can open it.
7. If Joy selects multiple items, verify the manifest contains one row per downloaded item and stable `item-####` handles.

## Revocation and deletion

To revoke cloud access:

1. Joy opens Google Account → Security → Third-party connections and removes Star’s Google Photos access.
2. Talon removes the local Photos token and pending state:

```sh
/opt/hermes-agent/bin/google-photos-oauth \
  --profile-home /home/joy/.hermes/profiles/star \
  --remove-local-token
```

This does not delete already downloaded local batches. Delete a local batch separately only with Joy’s explicit direction. Removing the token does not alter or delete anything in Google Photos.

## Authoritative sources

- Google Photos API updates and removed scopes: https://developers.google.com/photos/support/updates
- Current authorization scopes: https://developers.google.com/photos/overview/authorization
- Picker flow: https://developers.google.com/photos/picker/guides/get-started-picker
- Picker user search/selection experience: https://developers.google.com/photos/picker/guides/picking-experience
- Picker media listing and base-URL downloads: https://developers.google.com/photos/picker/guides/media-items
- Picker session and 2,000-item limit: https://developers.google.com/photos/picker/reference/rest/v1/sessions
- Google Photos API user-data policy: https://developers.google.com/photos/support/api-policy
- Google Takeout export behavior: https://support.google.com/accounts/answer/3024190

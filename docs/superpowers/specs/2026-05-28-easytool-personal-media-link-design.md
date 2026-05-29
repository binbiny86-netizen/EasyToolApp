# EasyTool Personal Product Media Link Design

## Goal

Add an EasyTool integration that uploads Dewu-captured media into one EasyTool personal product. The integration only supports personal products.

## Scope

- Captured images are appended to the personal product `ai_reference_images` field.
- One captured video overwrites the personal product `video` field.
- No shop product APIs are used.
- No other product columns may be modified, including name, description, images, specs, SKU rows, source fields, status, and timestamps.

## EasyTool Backend

Add a dedicated multipart endpoint:

`POST /api/dewu/personal-products/{productId}/media`

Fields:

- `images`: optional repeated files.
- `video`: optional single file.

The endpoint validates the logged-in user's personal product permission, uploads files through the existing `ImageService`, deduplicates image assets by stored path or URL, enforces the existing 12-image AI reference limit, and updates only the affected columns through repository partial update queries:

- `ai_reference_images`
- `video`

It must not call the normal full product update flow.

## Dewu Capture App

Add EasyTool controls to the gallery tab with:

- EasyTool API base URL.
- Username/password login that calls `/api/auth/login`.
- Personal product ID.
- Captured image multi-selection directly on image cards.
- Captured video single-selection directly on video cards.
- Upload action that sends selected files to the new EasyTool endpoint.

The Tauri backend performs the HTTP calls so local file paths do not need browser file handles.

## Error Handling

- Missing login, product ID, selected media, or EasyTool URL produce local validation errors.
- EasyTool API errors are surfaced in the app notice area.
- Partial EasyTool product updates are atomic at the backend transaction level.

## Verification

- Build Dewu frontend and run `cargo check` from `src-tauri`.
- Build/check EasyTool backend.
- Verify the new UI renders locally.

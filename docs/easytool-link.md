# EasyTool Personal Product Link

The Dewu capture app can upload captured media into an EasyTool personal product.

## EasyTool Endpoint

EasyTool must expose:

`POST /api/dewu/personal-products/{productId}/media`

Only these personal product fields are updated:

- `ai_reference_images`
- `video`

The endpoint must not run the full product save flow.

## Desktop App Use

1. Start EasyTool backend.
2. Open the Dewu capture desktop app.
3. Open the gallery tab.
4. Set the EasyTool API address, for example `http://10.110.134.81:8080`.
5. Log in with an EasyTool account that has personal product permission.
6. Enter the personal product ID.
7. Select captured images or switch to videos and select one captured video.
8. Upload.

Captured images are appended to AI reference images. The selected video overwrites the current product video.

## Platform Notes

Windows and macOS use the same HTTP API. If EasyTool and the Dewu proxy run on the same machine, avoid using the same port for both services.

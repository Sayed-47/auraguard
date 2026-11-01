# Screenshots and visual tour

The [overview preview](screenshots/overview-preview.svg) is an **illustration of the disconnected interface**, recreated from the included dashboard's layout and colors. It is not a browser capture or evidence that the hardware was connected. No live hardware screenshots were supplied with this project.

## What the dashboard shows

| View | What to look for | Source |
| --- | --- | --- |
| Overview | Receiver state, baby-link state, fall and sound flags, last signal, recent events. | Receiver USB logs parsed by the local gateway. |
| Live feed | Monitoring/alert states, session counts, serial port, most recent receiver line. | Current gateway snapshot. |
| History | Recorded events, filters, search, and CSV export. | Gateway event store and receipt timestamps. |
| Settings | Connection status and browser preferences. | Gateway snapshot and local browser preferences. |

The waiting state in the preview shows `—` for readings because there is no connected receiver. That is expected. Never use a fabricated reading or a static preview to imply that a live device was tested.

## Capture real screenshots

1. Follow [LAB_SETUP.md](LAB_SETUP.md) and connect the room Uno to the local gateway.
2. Open `http://127.0.0.1:8000` on the same computer. Wait until the connection state reflects the real device.
3. Capture the **Overview**, **Live feed**, and **History** views with your operating system's screenshot tool. For an alert example, use only a controlled lab test and label the resulting image as a test.
4. Check each image for room names, port paths, timestamps, and activity that should stay private. Crop or redact those details before publishing.
5. Save approved images in `docs/screenshots/` with descriptive names such as `overview-connected.png`, `live-feed.png`, and `history.png`. Replace the preview in the main README only after a real screenshot has been reviewed.

Suggested captions: “Overview with receiver connected in a lab test,” “Live feed showing receiver status,” and “History showing recorded test events.” Mention the test setup and date in a caption if the state could otherwise be mistaken for production monitoring.

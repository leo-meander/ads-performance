# MEANDER Ads Generator — Figma Plugin

Fills MEANDER ad templates from platform render jobs. The platform queues a
"render job" (a registered template + the text/image values to fill); this
plugin clones the template's master frame in Figma and fills every
`$`-prefixed layer.

This is the **Option 1** render path: the designer triggers generation with
one click — it is not a headless server pipeline.

## How it fits together

```
Platform (AI Brief / "Send to Figma")
   └─ POST /api/figma/jobs  →  figma_jobs row (PENDING)
                                     │
Designer opens the master Figma file │
   └─ runs this plugin                ▼
        ├─ GET  /api/figma/plugin/jobs        → pending jobs + template coords
        ├─ clone master frame, fill $-layers
        └─ POST /api/figma/plugin/jobs/{id}/complete
```

The master frame must live in the **currently open** Figma file — the plugin
locates it by the template's `node_id`.

## Layer naming convention

Designers mark dynamic layers with a `$` prefix; static layers have none and
are left untouched.

- `$headline`, `$subhead`, `$cta`, `$benefit_1`, `$benefit_2`, `$location` … — TEXT layers
- `$hero_image`, `$logo`, `$sub_image_1` … — image layers (any non-text node
  that can hold a fill)

The job's `request_payload` keys are the slugs **without** the `$`.

## Build

```bash
cd figma-plugin
npm install
npm run build      # → dist/code.js   (or `npm run watch` while developing)
```

## Install in Figma (development plugin)

1. Figma desktop → **Plugins → Development → Import plugin from manifest…**
2. Pick `figma-plugin/manifest.json`
3. The plugin appears under **Plugins → Development → MEANDER Ads Generator**

## First-run setup

1. Run the plugin → expand **Connection settings**
2. **API base URL**: `https://ads-performance-fuls.zeabur.app`
3. **API key**: mint one in the platform at `/api/export/keys` (admin), paste it
4. **Save** — stored per-user via Figma `clientStorage`

## Daily use

1. Open the Figma file that contains the template master frames
2. Run the plugin → **Fetch pending jobs**
3. Tick the jobs to generate → **Generate selected**
4. Each job clones its master frame to the right and fills the `$` layers;
   generated frames are selected + zoomed to when done
5. Completed jobs drop off the pending list automatically

## Notes / limits

- Figma REST API cannot write text from outside Figma — that is why this runs
  as a plugin inside the editor.
- Fonts used by `$` text layers must be available to the editor; the plugin
  loads them with `figma.loadFontAsync` before setting text.
- Image slots fetch the URL from the job payload and apply it as a `FILL`
  scale-mode image fill.
- `networkAccess` in the manifest is `["*"]` so the plugin can reach the
  platform API and arbitrary image CDNs. Tighten this before any public
  publish.

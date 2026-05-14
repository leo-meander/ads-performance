/// <reference types="@figma/plugin-typings" />
//
// MEANDER Ads Generator — Figma plugin (Option 1 render path).
//
// The platform queues "render jobs" (a template + the text/image values to
// fill). This plugin runs in the designer's Figma session, fetches pending
// jobs, and for each one: clones the template's master frame, fills every
// $-prefixed layer from the job payload, then reports the job COMPLETED.
//
// The master frame must live in the *currently open* Figma file — the plugin
// locates it by the template's node_id.

interface PluginSettings {
  apiBase: string;
  apiKey: string;
}

interface FigmaJob {
  job_id: string;
  request_payload: Record<string, string>;
  template: {
    id: string;
    name: string;
    file_key: string;
    node_id: string;
    width: number;
    height: number;
    placeholder_schema: Record<string, { type?: string }>;
  };
}

const STORAGE_KEY = "meander-ads-settings";

figma.showUI(__html__, { width: 380, height: 560 });

// ── Settings (persisted per-user via clientStorage) ──────────

async function loadSettings(): Promise<PluginSettings> {
  const raw = (await figma.clientStorage.getAsync(STORAGE_KEY)) as PluginSettings | undefined;
  return raw || { apiBase: "", apiKey: "" };
}

async function saveSettings(s: PluginSettings): Promise<void> {
  await figma.clientStorage.setAsync(STORAGE_KEY, s);
}

// ── Backend API ──────────────────────────────────────────────

async function apiGet(s: PluginSettings, path: string): Promise<any> {
  const res = await fetch(`${s.apiBase.replace(/\/$/, "")}${path}`, {
    headers: { "X-API-Key": s.apiKey },
  });
  if (!res.ok) throw new Error(`GET ${path} → HTTP ${res.status}`);
  return res.json();
}

async function apiPost(s: PluginSettings, path: string, body: unknown): Promise<any> {
  const res = await fetch(`${s.apiBase.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: { "X-API-Key": s.apiKey, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → HTTP ${res.status}`);
  return res.json();
}

// ── Fill helpers ─────────────────────────────────────────────

async function loadFontsForTextNode(node: TextNode): Promise<void> {
  const len = node.characters.length;
  const fonts =
    len > 0
      ? node.getRangeAllFontNames(0, len)
      : [node.fontName as FontName];
  for (const f of fonts) {
    await figma.loadFontAsync(f);
  }
}

function looksLikeUrl(v: string): boolean {
  return /^https?:\/\//i.test(v.trim());
}

async function applyImageFill(
  node: SceneNode,
  url: string,
  log: (m: string) => void,
): Promise<boolean> {
  if (!("fills" in node)) {
    log(`  ⚠ ${node.name}: layer can't hold an image fill, skipped`);
    return false;
  }
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buf = await resp.arrayBuffer();
    const image = figma.createImage(new Uint8Array(buf));
    (node as GeometryMixin).fills = [
      { type: "IMAGE", scaleMode: "FILL", imageHash: image.hash },
    ];
    return true;
  } catch (e) {
    log(`  ⚠ ${node.name}: image fetch failed (${String(e)})`);
    return false;
  }
}

// ── Core: generate one job ───────────────────────────────────

async function generateJob(
  s: PluginSettings,
  job: FigmaJob,
  offsetIndex: number,
  log: (m: string) => void,
): Promise<SceneNode | null> {
  const master = await figma.getNodeByIdAsync(job.template.node_id);

  if (!master) {
    log(`✗ ${job.template.name}: master ${job.template.node_id} not in this file`);
    await apiPost(s, `/api/figma/plugin/jobs/${job.job_id}/fail`, {
      error: `Master frame ${job.template.node_id} not found in the open Figma file. Open the right file and retry.`,
    });
    return null;
  }
  if (!("clone" in master)) {
    log(`✗ ${job.template.name}: node ${job.template.node_id} is not cloneable`);
    await apiPost(s, `/api/figma/plugin/jobs/${job.job_id}/fail`, {
      error: "Master node is not a cloneable frame/component.",
    });
    return null;
  }

  const masterFrame = master as FrameNode;
  const clone = masterFrame.clone();
  figma.currentPage.appendChild(clone);
  // Stack each generated frame to the right of the master, one per row.
  clone.x = masterFrame.x + masterFrame.width + 120;
  clone.y = masterFrame.y + offsetIndex * (masterFrame.height + 80);
  clone.name = `${masterFrame.name} — ${job.job_id.slice(0, 8)}`;

  const payload = job.request_payload || {};
  const schema = job.template.placeholder_schema || {};

  const descendants: SceneNode[] =
    "findAll" in clone
      ? ((clone as ChildrenMixin).findAll(() => true) as SceneNode[])
      : [];

  let filled = 0;
  let missing = 0;
  for (const node of descendants) {
    if (!node.name || node.name[0] !== "$") continue;
    const slug = node.name.slice(1).trim();
    const value = payload[slug];
    if (value === undefined || value === null || value === "") {
      missing++;
      continue;
    }
    const slotType = schema[slug] && schema[slug].type;

    if (node.type === "TEXT" && slotType !== "image") {
      try {
        await loadFontsForTextNode(node as TextNode);
        (node as TextNode).characters = String(value);
        filled++;
      } catch (e) {
        log(`  ⚠ ${node.name}: text fill failed (${String(e)})`);
      }
    } else if (slotType === "image" || looksLikeUrl(String(value))) {
      const ok = await applyImageFill(node, String(value), log);
      if (ok) filled++;
    }
  }

  log(`✓ ${clone.name}: filled ${filled} slot(s)${missing ? `, ${missing} empty` : ""}`);

  const deepLink = `https://www.figma.com/file/${job.template.file_key}?node-id=${encodeURIComponent(clone.id)}`;
  try {
    await apiPost(s, `/api/figma/plugin/jobs/${job.job_id}/complete`, {
      output_figma_url: deepLink,
    });
  } catch (e) {
    log(`  ⚠ generated in Figma but failed to report to API (${String(e)})`);
  }
  return clone;
}

// ── UI message handler ───────────────────────────────────────

figma.ui.onmessage = async (msg: any) => {
  try {
    if (msg.type === "init") {
      const s = await loadSettings();
      figma.ui.postMessage({ type: "settings", settings: s });
      return;
    }

    if (msg.type === "save-settings") {
      await saveSettings(msg.settings as PluginSettings);
      figma.ui.postMessage({ type: "saved" });
      return;
    }

    if (msg.type === "fetch-jobs") {
      const s = await loadSettings();
      if (!s.apiBase || !s.apiKey) {
        figma.ui.postMessage({ type: "error", message: "Set the API base URL + key first." });
        return;
      }
      const data = await apiGet(s, "/api/figma/plugin/jobs");
      figma.ui.postMessage({ type: "jobs", jobs: (data && data.data && data.data.items) || [] });
      return;
    }

    if (msg.type === "generate") {
      const s = await loadSettings();
      const jobs: FigmaJob[] = msg.jobs || [];
      const created: SceneNode[] = [];
      for (let i = 0; i < jobs.length; i++) {
        const node = await generateJob(s, jobs[i], i, (m) =>
          figma.ui.postMessage({ type: "log", message: m }),
        );
        if (node) created.push(node);
      }
      if (created.length > 0) {
        figma.currentPage.selection = created;
        figma.viewport.scrollAndZoomIntoView(created);
      }
      figma.ui.postMessage({ type: "done", count: created.length, total: jobs.length });
      return;
    }

    if (msg.type === "close") {
      figma.closePlugin();
      return;
    }
  } catch (e: any) {
    figma.ui.postMessage({ type: "error", message: String((e && e.message) || e) });
  }
};

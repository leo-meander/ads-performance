"""Build a Meta AdCreative for a combo, sourcing the image from Figma.

Background
----------
launch_service used to pass `combo.material_id` (an internal "MAT-001" short
id) straight into the Meta API as a `creative_id`. Meta rejects that — the
field expects a creative id that already exists on the account. The actual
pipeline Meta requires is:

  1. Get raw image bytes for the material.
  2. POST /act_xxx/adimages with those bytes → returns an image_hash scoped
     to the ad account.
  3. POST /act_xxx/adcreatives with an object_story_spec that wires the
     copy (headline / body / CTA / destination link) onto a Page +
     image_hash → returns a real creative_id.
  4. Pass that creative_id into /act_xxx/ads.

This module owns steps 1–3 and caches step 2's hash on the material so
re-launches don't re-upload. Step 1 prefers Figma (figma_file_key +
figma_node_id on ad_materials) because the Figma REST API can render
frames as PNG URLs that need no auth to download. Drive URLs are not
supported yet — the launch will fail with a clear error pointing the
designer at the Figma fields.

Resilience
----------
- All Meta calls run through the facebook_business SDK. They're mocked in
  tests by patching the upload/creative helpers below.
- httpx download has a 30s timeout. A failure raises CreativeBuilderError
  with the source URL so the operator can debug.
- If the material already has meta_image_hash we skip render+upload, but
  we still build a fresh AdCreative because copy + destination may have
  changed since last launch.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.services.figma_client import FigmaClient, FigmaClientError

logger = logging.getLogger(__name__)


class CreativeBuilderError(RuntimeError):
    """Raised when a creative cannot be built for a combo."""


# ── CTA mapping ──────────────────────────────────────────────
#
# Meta's call_to_action.type is a fixed enum. combo.copy.cta is freeform
# multilingual text. Map by keyword on a lowercased + stripped version.
# Default to LEARN_MORE — the safest fallback for hotel awareness ads.

_CTA_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("book now", "đặt phòng", "đặt ngay", "đặt", "predétat", "予約", "立即预订", "立即預訂"), "BOOK_TRAVEL"),
    (("shop now", "mua ngay", "mua", "购买", "購買"), "SHOP_NOW"),
    (("sign up", "đăng ký", "register", "註冊", "注册"), "SIGN_UP"),
    (("contact us", "liên hệ", "contact", "聯絡", "联系", "お問い合わせ"), "CONTACT_US"),
    (("get offer", "ưu đãi", "deal", "優惠", "优惠"), "GET_OFFER"),
    (("download", "tải", "下載", "下载"), "DOWNLOAD"),
    (("order now", "đặt món", "order", "订购", "訂購"), "ORDER_NOW"),
    (("learn more", "tìm hiểu", "more", "了解更多", "詳細"), "LEARN_MORE"),
]
_DEFAULT_CTA = "LEARN_MORE"


def meta_cta_for(text: Optional[str]) -> str:
    """Map a freeform CTA string to Meta's call_to_action enum."""
    if not text:
        return _DEFAULT_CTA
    needle = text.strip().lower()
    if not needle:
        return _DEFAULT_CTA
    for keywords, enum_value in _CTA_KEYWORDS:
        if any(k in needle for k in keywords):
            return enum_value
    return _DEFAULT_CTA


# ── Public entry point ───────────────────────────────────────


def build_or_get_meta_creative(
    db: Session,
    account: AdAccount,
    combo: AdCombo,
    *,
    figma_client: Optional[FigmaClient] = None,
    http_client: Optional[httpx.Client] = None,
) -> str:
    """Return a Meta `creative_id` ready to plug into AdAccount.create_ad.

    Reuses the cached meta_image_hash when available; otherwise renders the
    Figma frame, uploads to /adimages, and stores the hash on ad_materials.
    Always builds a fresh AdCreative so headline/body/CTA reflect the most
    recent copy.
    """
    if not account.meta_page_id:
        raise CreativeBuilderError(
            f"Branch '{account.account_name}' has no meta_page_id set. "
            f"Open Accounts settings and add the Facebook Page id before launching."
        )

    material = (
        db.query(AdMaterial).filter(AdMaterial.material_id == combo.material_id).first()
    )
    if not material:
        raise CreativeBuilderError(f"Material {combo.material_id} not found")

    copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first()
    if not copy:
        raise CreativeBuilderError(f"Copy {combo.copy_id} not found")

    image_hash = material.meta_image_hash
    if not image_hash:
        image_bytes = _fetch_creative_bytes(material, figma_client=figma_client, http_client=http_client)
        image_hash = _upload_adimage(account, image_bytes)
        material.meta_image_hash = image_hash
        db.commit()
        logger.info(
            "Uploaded material %s to account %s — cached hash %s",
            material.material_id,
            account.account_id,
            image_hash,
        )

    destination = account.default_destination_url or ""
    if not destination:
        raise CreativeBuilderError(
            f"Branch '{account.account_name}' has no default_destination_url. "
            f"Meta requires a link on every link ad. Set it in Accounts settings."
        )

    creative_id = _create_adcreative(
        account=account,
        image_hash=image_hash,
        page_id=account.meta_page_id,
        headline=copy.headline,
        body_text=copy.body_text,
        cta_type=meta_cta_for(copy.cta),
        link=destination,
        name=f"{combo.combo_id} · {copy.copy_id}",
    )
    return creative_id


# ── Image sourcing ───────────────────────────────────────────


def _fetch_creative_bytes(
    material: AdMaterial,
    *,
    figma_client: Optional[FigmaClient] = None,
    http_client: Optional[httpx.Client] = None,
) -> bytes:
    """Resolve the material to raw PNG bytes.

    Priority:
      1. Figma render — if figma_file_key + figma_node_id are set we hit
         /v1/images, then GET the returned CDN URL.
      2. Drive — not supported yet; raises so the operator wires Figma.
    """
    if material.figma_file_key and material.figma_node_id:
        client = figma_client or FigmaClient()
        try:
            exports = client.export_images(
                material.figma_file_key, [material.figma_node_id], fmt="png"
            )
        except FigmaClientError as e:
            raise CreativeBuilderError(
                f"Figma render failed for material {material.material_id}: {e}"
            ) from e

        if not exports or not exports[0].image_url:
            raise CreativeBuilderError(
                f"Figma returned no image URL for material {material.material_id} "
                f"(file={material.figma_file_key}, node={material.figma_node_id})"
            )

        png_url = exports[0].image_url
        return _download(png_url, http_client=http_client)

    raise CreativeBuilderError(
        f"Material {material.material_id} has no figma_file_key/figma_node_id. "
        f"Drive-only sources are not yet supported by the auto-launch pipeline — "
        f"register the master frame in Figma first."
    )


def _download(url: str, *, http_client: Optional[httpx.Client] = None) -> bytes:
    """GET the URL and return raw bytes. 30s timeout."""
    try:
        if http_client is not None:
            resp = http_client.get(url)
        else:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise CreativeBuilderError(f"Image download failed: {url} ({e})") from e
    return resp.content


# ── Meta API wrappers ────────────────────────────────────────
#
# Kept thin and isolated so tests can patch each one independently.


def _upload_adimage(account: AdAccount, image_bytes: bytes) -> str:
    """POST /act_xxx/adimages and return the resulting hash."""
    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.adobjects.adimage import AdImage
    from facebook_business.api import FacebookAdsApi

    FacebookAdsApi.init(access_token=account.access_token_enc)
    fb_account = FBAdAccount(f"act_{account.account_id}")

    image = AdImage(parent_id=fb_account.get_id_assured())
    image[AdImage.Field.bytes] = image_bytes
    image.remote_create()
    return image[AdImage.Field.hash]


def _create_adcreative(
    *,
    account: AdAccount,
    image_hash: str,
    page_id: str,
    headline: str,
    body_text: str,
    cta_type: str,
    link: str,
    name: str,
) -> str:
    """POST /act_xxx/adcreatives and return the creative id."""
    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.api import FacebookAdsApi

    FacebookAdsApi.init(access_token=account.access_token_enc)
    fb_account = FBAdAccount(f"act_{account.account_id}")

    params: dict[str, Any] = {
        "name": name[:200],
        "object_story_spec": {
            "page_id": page_id,
            "link_data": {
                "image_hash": image_hash,
                "link": link,
                "message": body_text,
                "name": headline,
                "call_to_action": {
                    "type": cta_type,
                    "value": {"link": link},
                },
            },
        },
    }
    result = fb_account.create_ad_creative(params=params)
    return result["id"]

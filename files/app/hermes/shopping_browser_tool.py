"""Narrow shopping browser bridge for Star.

This custom Hermes toolset intentionally exposes narrow inspection of the
Puppet/KubeCM-managed Kasm shopping browser plus explicitly allowlisted,
approval-gated add-to-cart-only actions.  It connects to Chrome DevTools
Protocol behind the bridge and never returns a raw browser handle, CDP URL,
cookie, local storage value, request header, screenshot, or page HTML.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

import websockets.sync.client
from tools.registry import registry

TOOLSET = "shopping_browser"
NAMESPACE = os.environ.get("SHOPPING_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("SHOPPING_BROWSER_WORKLOAD", "deployment/shopping")
REMOTE_DEBUG_PORT = int(os.environ.get("SHOPPING_BROWSER_CDP_PORT", "9222"))
MAX_RESULT_CHARS = 16000
MAX_PRODUCT_IMAGES = 6
DEFAULT_MAX_REVIEWS = 5
MAX_REVIEWS = 10
REVIEW_EXCERPT_CHARS = 900
PORT_FORWARD_TIMEOUT_SECONDS = 20
PAGE_LOAD_TIMEOUT_SECONDS = 15
APPROVED_CART_ADDITIONS = {
    "B01J01XGPK": {
        "approval_reference": "agent-request ar-20260605-094041-cfe371 / kanban t_a801c12e",
        "url": "https://www.amazon.com/dp/B01J01XGPK",
        "title_contains": "304 Stainless Steel Premium Pipe Screen Filters",
        "quantity": 1,
        "max_item_price": "7.95",
        "seller_contains": "Gray Caravan",
        "ships_from_contains": "Amazon",
        "purchase_mode": "one_time",
    },
}

AMAZON_HOST_RE = re.compile(r"(^|\.)amazon\.[a-z.]+$", re.IGNORECASE)
AMAZON_IMAGE_HOST_RE = re.compile(r"(^|\.)(m\.media-amazon|images-na\.ssl-images-amazon|ssl-images-amazon)\.com$", re.IGNORECASE)
UNSAFE_OPERATIONS = {
    "remove_from_cart",
    "update_cart",
    "checkout",
    "buy_now",
    "place_order",
    "account_settings",
    "edit_address",
    "edit_payment",
    "download_account_data",
    "export_account_data",
    "raw_cdp",
    "cookies",
    "local_storage",
    "screenshot",
    "download",
    "navigate",
    "click",
    "type",
}

PRODUCT_EXTRACT_JS = r"""
(() => {
  const cleanNodeText = (node) => {
    if (!node) return '';
    const clone = node.cloneNode(true);
    clone.querySelectorAll('script, style, noscript').forEach((child) => child.remove());
    return clone.textContent.replace(/\s+/g, ' ').trim();
  };
  const text = (selector) => cleanNodeText(document.querySelector(selector));
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const value = text(selector);
      if (value) return value;
    }
    return '';
  };
  const addImage = (urls, value) => {
    if (!value || typeof value !== 'string') return;
    const clean = value.trim();
    if (clean.startsWith('https://')) urls.push(clean);
  };
  const imageUrls = [];
  const landingImage = document.querySelector('#landingImage, #imgBlkFront, #ebooksImgBlkFront');
  if (landingImage) {
    addImage(imageUrls, landingImage.getAttribute('data-old-hires'));
    addImage(imageUrls, landingImage.getAttribute('src'));
    const dynamicImage = landingImage.getAttribute('data-a-dynamic-image');
    if (dynamicImage) {
      try {
        Object.keys(JSON.parse(dynamicImage)).forEach((url) => addImage(imageUrls, url));
      } catch (_err) {
        // Ignore malformed Amazon widget metadata; safe extraction reports empty below.
      }
    }
  }
  document.querySelectorAll('#altImages img, #imageBlock img, .imgTagWrapper img').forEach((img) => {
    addImage(imageUrls, img.getAttribute('data-old-hires'));
    addImage(imageUrls, img.getAttribute('src'));
  });
  return {
    page_title: document.title || '',
    product_title: firstText(['#productTitle', '#title', 'h1']),
    logged_in_price: firstText([
      '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
      '#corePrice_feature_div .a-price .a-offscreen',
      '#priceblock_ourprice',
      '#priceblock_dealprice',
      '.a-price .a-offscreen'
    ]),
    prime_delivery_text: firstText([
      '#mir-layout-DELIVERY_BLOCK',
      '#deliveryBlockMessage',
      '#amazonGlobal_feature_div',
      '#primeShippingMessage_feature_div'
    ]),
    stock_availability: firstText(['#availability', '#outOfStock', '#availabilityInsideBuyBox_feature_div']),
    seller: firstText([
      '#sellerProfileTriggerId',
      '#merchant-info',
      '#tabular-buybox [tabular-attribute-name="Sold by"] .tabular-buybox-text',
      '#tabular-buybox .tabular-buybox-text'
    ]),
    ship_from: firstText([
      '#tabular-buybox [tabular-attribute-name="Ships from"] .tabular-buybox-text',
      '#fulfillerInfoFeature_feature_div',
      '#merchant-info'
    ]),
    asin: firstText(['#ASIN', 'input[name="ASIN"]', 'input#ASIN']) || (document.querySelector('#ASIN, input[name="ASIN"], input#ASIN') || {}).value || '',
    image_url_candidates: Array.from(new Set(imageUrls)).slice(0, 12)
  };
})()
"""

CART_EXTRACT_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const text = (node, selector) => {
    const found = node.querySelector(selector);
    if (!found) return '';
    const clone = found.cloneNode(true);
    clone.querySelectorAll('script, style, noscript').forEach((child) => child.remove());
    return clean(clone.textContent);
  };
  const firstText = (node, selectors) => {
    for (const selector of selectors) {
      const value = text(node, selector);
      if (value) return value;
    }
    return '';
  };
  const primaryItems = Array.from(document.querySelectorAll('.sc-list-item'))
    .filter((item) => clean(item.textContent));
  const fallbackItems = Array.from(document.querySelectorAll('[data-name="Active Items"] [data-asin]'));
  const itemNodes = primaryItems.length ? primaryItems : fallbackItems;
  const items = itemNodes
    .map((item) => ({
      name: firstText(item, ['.sc-product-title', '.a-truncate-cut', 'h4', '.a-link-normal']),
      quantity: firstText(item, ['[data-a-selector="value"]', '.sc-action-quantity select option:checked', '.sc-action-quantity .a-dropdown-prompt']),
      price: firstText(item, ['.sc-product-price', '.a-price .a-offscreen', '.sc-price']),
      delivery_estimate: firstText(item, ['.sc-delivery-message', '.delivery-message', '[data-feature-id="delivery-message"]'])
    }))
    .filter((item) => item.name || item.price || item.quantity || item.delivery_estimate)
    .slice(0, 30);
  return {
    page_title: document.title || '',
    items,
    subtotal: clean([
      text(document, '#sc-subtotal-label-activecart'),
      text(document, '#sc-subtotal-amount-activecart'),
      text(document, '.sc-subtotal')
    ].filter(Boolean).join(' ')),
    delivery_estimate: text(document, '.sc-delivery-message, #delivery-block, [data-feature-id="delivery-message"]')
  };
})()
"""


ADD_TO_CART_PRECHECK_JS = r"""
(() => {
  const requestedQuantity = __QUANTITY__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const text = (selector) => {
    const node = document.querySelector(selector);
    if (!node) return '';
    const clone = node.cloneNode(true);
    clone.querySelectorAll('script, style, noscript').forEach((child) => child.remove());
    return clean(clone.textContent);
  };
  const pageText = clean(document.body ? document.body.innerText : '');
  const lowerPageText = pageText.toLowerCase();
  const challengeReason = (() => {
    if (document.querySelector('form[action*="validateCaptcha"], input[name="field-keywords"] + input[type="submit"][alt*="Continue shopping"]')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('enter the characters you see below')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('sorry, we just need to make sure you\'re not a robot')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('sign in') && (lowerPageText.includes('password') || lowerPageText.includes('passkey') || lowerPageText.includes('verification code'))) return 'Amazon sign-in, passkey, or verification challenge is visible.';
    return '';
  })();
  const asin = (document.querySelector('#ASIN, input[name="ASIN"], input#ASIN') || {}).value || '';
  const buyBoxText = clean([
    text('#buybox'),
    text('#desktop_buybox'),
    text('#ppd'),
    text('#apex_desktop')
  ].filter(Boolean).join(' '));
  const buyBoxLower = buyBoxText.toLowerCase();
  const unexpectedReason = (() => {
    if (buyBoxLower.includes('used') || buyBoxLower.includes('renewed') || buyBoxLower.includes('refurbished')) return 'Buy box appears to offer a used, renewed, or refurbished item.';
    if (buyBoxLower.includes('digital') || buyBoxLower.includes('kindle')) return 'Buy box appears to offer a digital item.';
    if (buyBoxLower.includes('add-on item')) return 'Buy box appears to be an add-on item.';
    const selectedWarranty = Array.from(document.querySelectorAll('input[type="checkbox"], input[type="radio"]'))
      .some((input) => input.checked && /warranty|protection|coverage|insurance/i.test(clean(input.closest('label, div, span') ? input.closest('label, div, span').textContent : input.name || input.id || '')));
    if (selectedWarranty) return 'A warranty/protection/coverage option appears selected.';
    return '';
  })();
  const oneTimeSelectors = [
    '#buybox-one-time-purchase-button input[type="radio"]',
    'input[name="purchaseOption"][value*="one" i]',
    'input[id*="one-time" i]',
    'input[aria-labelledby*="one-time" i]'
  ];
  for (const selector of oneTimeSelectors) {
    const input = document.querySelector(selector);
    if (input && !input.checked && !input.disabled) {
      input.click();
    }
  }
  const subscriptionSelected = Array.from(document.querySelectorAll('input[type="radio"], input[type="checkbox"]'))
    .some((input) => input.checked && /subscribe|subscription|save/i.test(clean(input.closest('label, div, span') ? input.closest('label, div, span').textContent : input.name || input.id || '')));
  const quantitySelect = document.querySelector('#quantity, select[name="quantity"]');
  let quantityState = 'not_visible';
  if (quantitySelect) {
    const desired = String(requestedQuantity);
    const option = Array.from(quantitySelect.options || []).find((candidate) => candidate.value === desired || clean(candidate.textContent) === desired);
    if (option) {
      quantitySelect.value = option.value;
      quantitySelect.dispatchEvent(new Event('change', {bubbles: true}));
      quantitySelect.dispatchEvent(new Event('input', {bubbles: true}));
      quantityState = 'set';
    } else {
      quantityState = 'requested_quantity_not_available';
    }
  } else if (requestedQuantity === 1) {
    quantityState = 'implicit_one';
  }
  const addButton = document.querySelector('#add-to-cart-button, input[name="submit.add-to-cart"]');
  return {
    asin,
    challenge_reason: challengeReason,
    unexpected_reason: unexpectedReason,
    subscription_selected: subscriptionSelected,
    add_button_visible: Boolean(addButton),
    add_button_disabled: Boolean(addButton && addButton.disabled),
    quantity_state: quantityState,
    page_title: document.title || ''
  };
})()
"""

ADD_TO_CART_CLICK_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const pageText = clean(document.body ? document.body.innerText : '');
  const lowerPageText = pageText.toLowerCase();
  if (document.querySelector('form[action*="validateCaptcha"]') || lowerPageText.includes('enter the characters you see below')) {
    return {clicked: false, reason: 'Amazon CAPTCHA or robot-check page is visible.'};
  }
  const addButton = document.querySelector('#add-to-cart-button, input[name="submit.add-to-cart"]');
  if (!addButton) return {clicked: false, reason: 'Add-to-cart button was not visible.'};
  if (addButton.disabled) return {clicked: false, reason: 'Add-to-cart button was disabled.'};
  addButton.click();
  return {clicked: true, reason: ''};
})()
"""


REVIEWS_EXTRACT_JS = r"""
(() => {
  const maxReviews = __MAX_REVIEWS__;
  const excerptChars = __EXCERPT_CHARS__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const cleanNodeText = (node) => {
    if (!node) return '';
    const clone = node.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, input, button').forEach((child) => child.remove());
    return clean(clone.textContent);
  };
  const text = (selector) => cleanNodeText(document.querySelector(selector));
  const firstText = (selectors) => {
    for (const selector of selectors) {
      const value = text(selector);
      if (value) return value;
    }
    return '';
  };
  const attrText = (node, selectors, attr) => {
    for (const selector of selectors) {
      const found = node.querySelector(selector);
      if (!found) continue;
      const value = clean(found.getAttribute(attr) || '');
      if (value) return value;
    }
    return '';
  };
  const shorten = (value, limit) => {
    const cleaned = clean(value);
    if (cleaned.length <= limit) return cleaned;
    return cleaned.slice(0, limit).replace(/\s+\S*$/, '') + '…';
  };
  const pageText = clean(document.body ? document.body.innerText : '');
  const lowerPageText = pageText.toLowerCase();
  const blockedReason = (() => {
    if (document.querySelector('form[action*="validateCaptcha"], input[name="field-keywords"] + input[type="submit"][alt*="Continue shopping"]')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('enter the characters you see below')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('sorry, we just need to make sure you\'re not a robot')) return 'Amazon CAPTCHA or robot-check page is visible.';
    if (lowerPageText.includes('sign in') && lowerPageText.includes('to see customer reviews')) return 'Amazon requires sign-in before reviews are visible.';
    return '';
  })();
  const histogram = {};
  document.querySelectorAll('#histogramTable tr, table#histogramTable tr, .histogram-row, [aria-label*="star"][aria-label*="%"]')
    .forEach((row) => {
      const label = clean(row.getAttribute('aria-label') || row.textContent);
      const starMatch = label.match(/([1-5])\s*star/i);
      const percentMatch = label.match(/(\d{1,3})\s*%/);
      if (starMatch && percentMatch) histogram[`${starMatch[1]}_star`] = `${percentMatch[1]}%`;
    });
  const reviewNodes = Array.from(document.querySelectorAll('[data-hook="review"], .review, [id^="customer_review-"]'));
  const reviews = reviewNodes.map((node) => {
    const rating = attrText(node, ['[data-hook="review-star-rating"]', '[data-hook="cmps-review-star-rating"]', '.review-rating'], 'aria-label')
      || cleanNodeText(node.querySelector('[data-hook="review-star-rating"], [data-hook="cmps-review-star-rating"], .review-rating'));
    const titleNode = node.querySelector('[data-hook="review-title"], .review-title');
    let title = cleanNodeText(titleNode);
    if (rating && title.startsWith(rating)) title = clean(title.slice(rating.length));
    return {
      star_rating: rating,
      title: title,
      date: cleanNodeText(node.querySelector('[data-hook="review-date"], .review-date')),
      verified_purchase: Boolean(node.querySelector('[data-hook="avp-badge"], .avp-badge')) || /verified purchase/i.test(cleanNodeText(node)),
      reviewer: cleanNodeText(node.querySelector('.a-profile-name, [data-hook="genome-widget"] .a-profile-name')),
      body_excerpt: shorten(cleanNodeText(node.querySelector('[data-hook="review-body"], .review-text, .review-text-content')), excerptChars)
    };
  }).filter((review) => review.star_rating || review.title || review.body_excerpt).slice(0, maxReviews);
  const topReviews = {};
  const positive = document.querySelector('[data-hook="positive-review"], #viewpoint-R1, .cr-lighthouse-term');
  const critical = document.querySelector('[data-hook="critical-review"], #viewpoint-R2');
  if (positive) topReviews.positive_excerpt = shorten(cleanNodeText(positive), excerptChars);
  if (critical) topReviews.critical_excerpt = shorten(cleanNodeText(critical), excerptChars);
  const phraseSelectors = [
    '[data-hook="cr-insights-widget"] .a-size-base',
    '[data-hook="cr-insights-widget"] .a-badge-text',
    '.cr-lighthouse-term',
    '.review-keyword'
  ];
  const commonPhrases = Array.from(new Set(phraseSelectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)).map(cleanNodeText).filter(Boolean)))).slice(0, 20);
  const result = {
    page_title: document.title || '',
    product_title: firstText(['#cm_cr-product_info .a-size-large', '[data-hook="product-title"]', '#productTitle', 'h1']),
    overall_rating: firstText(['[data-hook="rating-out-of-text"]', '#acrPopover .a-icon-alt', '.AverageCustomerReviews .a-icon-alt', '.reviewNumericalSummary .a-icon-alt']),
    review_count: firstText(['[data-hook="total-review-count"]', '#acrCustomerReviewText', '#filter-info-section .a-size-base', '.cr-filter-info-review-rating-count']),
    rating_histogram: histogram,
    top_reviews: topReviews,
    common_phrases: commonPhrases,
    reviews,
    extraction: {
      status: blockedReason ? 'blocked' : (reviews.length || Object.keys(histogram).length || firstText(['[data-hook="rating-out-of-text"]', '#acrPopover .a-icon-alt']) ? 'ok' : 'unavailable'),
      reason: blockedReason || (reviews.length ? '' : 'No public review excerpts were visible in supported Amazon review selectors.'),
      requested_max_reviews: maxReviews,
      returned_reviews: reviews.length
    }
  };
  return result;
})()
"""

SUMMARY_EXTRACT_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const text = (selector) => {
    const node = document.querySelector(selector);
    return node ? clean(node.textContent) : '';
  };
  return {
    page_title: document.title || '',
    product_title: text('#productTitle') || text('h1'),
    logged_in_price: text('#corePriceDisplay_desktop_feature_div .a-price .a-offscreen') || text('.a-price .a-offscreen'),
    stock_availability: text('#availability'),
    cart_subtotal: text('#sc-subtotal-amount-activecart') || text('.sc-subtotal')
  };
})()
"""


def _json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if len(payload) > MAX_RESULT_CHARS:
        payload = payload[:MAX_RESULT_CHARS] + "… [truncated]"
    return payload


def _check_shopping_browser() -> bool:
    return shutil.which("kubectl") is not None


def _sanitize_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _sanitize_product_image_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not AMAZON_IMAGE_HOST_RE.search(parsed.netloc):
        return None
    if not parsed.path.startswith("/images/"):
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _normalize_product_images(result: dict[str, Any]) -> None:
    candidates = result.pop("image_url_candidates", None) or []
    image_urls: list[str] = []
    for candidate in candidates:
        sanitized = _sanitize_product_image_url(str(candidate))
        if sanitized and sanitized not in image_urls:
            image_urls.append(sanitized)
        if len(image_urls) >= MAX_PRODUCT_IMAGES:
            break
    result["primary_image_url"] = image_urls[0] if image_urls else None
    result["image_urls"] = image_urls
    if image_urls:
        result["image_extraction"] = {"status": "ok", "count": len(image_urls)}
    else:
        result["image_extraction"] = {
            "status": "failed",
            "reason": "No public Amazon product image URLs were visible in the supported product image selectors.",
        }


def _validate_amazon_url(value: str, operation: str = "inspect_product") -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not AMAZON_HOST_RE.search(parsed.netloc):
        raise ValueError(f"{operation} only accepts https://*.amazon.* URLs")
    if any(word in parsed.path.lower() for word in ("cart", "checkout", "buy", "gp/your-account", "hz/mycd", "orders", "addresses", "wallet")):
        raise ValueError("URL path is outside the read-only product inspection scope")
    return value



def _extract_asin(value: str) -> str | None:
    parsed = urlparse(value)
    candidates = [part for part in parsed.path.split('/') if part]
    for index, part in enumerate(candidates):
        if part in ('dp', 'product', 'product-reviews') and index + 1 < len(candidates):
            asin = candidates[index + 1]
            if re.fullmatch(r'[A-Z0-9]{10}', asin, re.IGNORECASE):
                return asin.upper()
    for part in candidates:
        if re.fullmatch(r'[A-Z0-9]{10}', part, re.IGNORECASE):
            return part.upper()
    return None



def _product_url_from_url_or_asin(value: str) -> tuple[str, str]:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("url_or_asin is required")
    if re.fullmatch(r"[A-Z0-9]{10}", candidate, re.IGNORECASE):
        asin = candidate.upper()
        return f"https://www.amazon.com/dp/{asin}", asin
    safe_url = _validate_amazon_url(candidate, operation="add_to_cart")
    asin = _extract_asin(safe_url)
    if not asin:
        raise ValueError("url_or_asin must contain an exact Amazon ASIN")
    return safe_url, asin


def _parse_decimal_money(value: Any, field: str) -> Decimal:
    if value in (None, ""):
        raise ValueError(f"{field} is required")
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a decimal price") from None
    if parsed <= Decimal("0"):
        raise ValueError(f"{field} must be greater than 0")
    return parsed.quantize(Decimal("0.01"))


def _parse_quantity(value: Any) -> int:
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        raise ValueError("quantity must be an integer") from None
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    if quantity > 3:
        raise ValueError("quantity exceeds this tool's hard safety cap of 3")
    return quantity


def _price_from_text(value: Any) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"\$?\s*([0-9]+(?:\.[0-9]{2})?)", str(value).replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(1)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _assert_text_contains(actual: Any, expected: str, field: str) -> None:
    if expected and expected.lower() not in str(actual or "").lower():
        raise ValueError(f"Verified {field} did not match approved item expectation")


def _approved_cart_addition(asin: str, quantity: int, max_item_price: Decimal, purchase_mode: str) -> dict[str, Any]:
    approved = APPROVED_CART_ADDITIONS.get(asin.upper())
    if not approved:
        raise ValueError("ASIN is not in the currently approved add-to-cart allowlist")
    if quantity != int(approved["quantity"]):
        raise ValueError("quantity does not match Joy's approved item quantity")
    approved_max = Decimal(str(approved["max_item_price"])).quantize(Decimal("0.01"))
    if max_item_price > approved_max:
        raise ValueError("max_item_price exceeds the approved item price cap")
    if purchase_mode != approved["purchase_mode"]:
        raise ValueError("purchase_mode does not match Joy's approved purchase mode")
    return approved


def _review_url(value: str) -> tuple[str, str | None]:
    safe_url = _validate_amazon_url(value, operation='inspect_reviews')
    parsed = urlparse(safe_url)
    asin = _extract_asin(safe_url)
    if asin:
        return urlunparse((parsed.scheme, parsed.netloc, f'/product-reviews/{asin}', '', '', '')), asin
    return safe_url, None


def _bounded_max_reviews(value: Any) -> int:
    if value in (None, ''):
        return DEFAULT_MAX_REVIEWS
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError('max_reviews must be an integer') from None
    if parsed < 1:
        raise ValueError('max_reviews must be at least 1')
    return min(parsed, MAX_REVIEWS)


def _reject_unsafe_operation(operation: str) -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    if op in UNSAFE_OPERATIONS:
        return {
            "allowed": False,
            "error": "OPERATION_NOT_ALLOWED",
            "operation": op,
            "message": "Star's shopping bridge is read-only: product/review/cart/page inspection only. Joy handles login, Bitwarden, passkeys, 2FA, CAPTCHA, checkout, account, address, payment, and order actions manually.",
        }
    return {"allowed": True, "operation": op}


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PortForward:
    def __init__(self) -> None:
        self.local_port = _free_port()
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> int:
        cmd = [
            "kubectl",
            "-n",
            NAMESPACE,
            "port-forward",
            "--address",
            "127.0.0.1",
            WORKLOAD,
            f"{self.local_port}:{REMOTE_DEBUG_PORT}",
        ]
        env = os.environ.copy()
        env.setdefault("HOME", "/home/joy")
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        deadline = time.time() + PORT_FORWARD_TIMEOUT_SECONDS
        version_url = f"http://127.0.0.1:{self.local_port}/json/version"
        while time.time() < deadline:
            if self.process.poll() is not None:
                stderr = (self.process.stderr.read() if self.process.stderr else "").strip()
                raise RuntimeError(f"kubectl port-forward failed: {stderr[:800]}")
            try:
                with urlopen(version_url, timeout=1) as response:
                    json.loads(response.read().decode("utf-8"))
                return self.local_port
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("timed out waiting for shopping browser CDP bridge")

    def __exit__(self, *_exc: object) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


class CdpSession:
    def __init__(self, websocket_url: str) -> None:
        self.ws = websockets.sync.client.connect(websocket_url, open_timeout=5, close_timeout=2)
        self.next_id = 1

    def close(self) -> None:
        self.ws.close()

    def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"id": self.next_id, "method": method}
        call_id = self.next_id
        self.next_id += 1
        if params is not None:
            msg["params"] = params
        if session_id is not None:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv(timeout=10)
            data = json.loads(raw)
            if data.get("id") == call_id:
                if "error" in data:
                    raise RuntimeError(f"CDP {method} failed: {data['error'].get('message', 'unknown error')}")
                return data.get("result") or {}


def _browser_ws_url(port: int) -> str:
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
        version = json.loads(response.read().decode("utf-8"))
    url = str(version.get("webSocketDebuggerUrl") or "")
    if not url:
        raise RuntimeError("shopping browser CDP endpoint did not report a browser websocket")
    return url


def _first_page_target(browser: CdpSession) -> str:
    targets = browser.call("Target.getTargets").get("targetInfos") or []
    for target in targets:
        if target.get("type") == "page":
            return str(target["targetId"])
    created = browser.call("Target.createTarget", {"url": "about:blank"})
    return str(created["targetId"])


def _attach(browser: CdpSession, target_id: str) -> str:
    result = browser.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    session_id = str(result["sessionId"])
    browser.call("Runtime.enable", session_id=session_id)
    browser.call("Page.enable", session_id=session_id)
    return session_id


def _evaluate(browser: CdpSession, session_id: str, expression: str) -> Any:
    result = browser.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        session_id=session_id,
    )
    value = result.get("result") or {}
    return value.get("value")


def _navigate_and_wait(browser: CdpSession, session_id: str, url: str) -> None:
    browser.call("Page.navigate", {"url": url}, session_id=session_id)
    deadline = time.time() + PAGE_LOAD_TIMEOUT_SECONDS
    while time.time() < deadline:
        ready = _evaluate(browser, session_id, "document.readyState")
        if ready in ("interactive", "complete"):
            time.sleep(1.0)
            return
        time.sleep(0.25)


def _with_browser(fn: Any) -> dict[str, Any]:
    with PortForward() as port:
        browser = CdpSession(_browser_ws_url(port))
        try:
            return fn(browser)
        finally:
            browser.close()


def _inspect_product(url: str) -> dict[str, Any]:
    safe_url = _validate_amazon_url(url)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
        session_id = _attach(browser, target_id)
        try:
            _navigate_and_wait(browser, session_id, safe_url)
            result = _evaluate(browser, session_id, PRODUCT_EXTRACT_JS) or {}
            _normalize_product_images(result)
            result["url"] = _sanitize_url(safe_url)
            result["operation"] = "inspect_product"
            return result
        finally:
            with contextlib.suppress(Exception):
                browser.call("Target.closeTarget", {"targetId": target_id})

    return _with_browser(run)


def _inspect_reviews(url: str, max_reviews: int) -> dict[str, Any]:
    reviews_url, asin = _review_url(url)
    expression = REVIEWS_EXTRACT_JS.replace('__MAX_REVIEWS__', str(max_reviews)).replace('__EXCERPT_CHARS__', str(REVIEW_EXCERPT_CHARS))

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
        session_id = _attach(browser, target_id)
        try:
            _navigate_and_wait(browser, session_id, reviews_url)
            result = _evaluate(browser, session_id, expression) or {}
            result["url"] = _sanitize_url(reviews_url)
            result["operation"] = "inspect_reviews"
            if asin:
                result["asin"] = asin
            return result
        finally:
            with contextlib.suppress(Exception):
                browser.call("Target.closeTarget", {"targetId": target_id})

    return _with_browser(run)


def _inspect_cart() -> dict[str, Any]:
    cart_url = "https://www.amazon.com/gp/cart/view.html"

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
        session_id = _attach(browser, target_id)
        try:
            _navigate_and_wait(browser, session_id, cart_url)
            result = _evaluate(browser, session_id, CART_EXTRACT_JS) or {}
            result["url"] = cart_url
            result["operation"] = "inspect_cart"
            return result
        finally:
            with contextlib.suppress(Exception):
                browser.call("Target.closeTarget", {"targetId": target_id})

    return _with_browser(run)



def _add_to_cart(url_or_asin: str, quantity: int, max_item_price: Decimal, purchase_mode: str) -> dict[str, Any]:
    safe_url, asin = _product_url_from_url_or_asin(url_or_asin)
    approved = _approved_cart_addition(asin, quantity, max_item_price, purchase_mode)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
        session_id = _attach(browser, target_id)
        try:
            _navigate_and_wait(browser, session_id, safe_url)
            product = _evaluate(browser, session_id, PRODUCT_EXTRACT_JS) or {}
            _normalize_product_images(product)
            page_asin = str(product.get("asin") or asin).upper()
            if page_asin and page_asin != asin:
                raise ValueError("Loaded product ASIN did not match the approved ASIN")
            _assert_text_contains(product.get("product_title"), str(approved.get("title_contains") or ""), "title")
            _assert_text_contains(product.get("seller"), str(approved.get("seller_contains") or ""), "seller")
            _assert_text_contains(product.get("ship_from"), str(approved.get("ships_from_contains") or ""), "ships-from")
            observed_price = _price_from_text(product.get("logged_in_price"))
            if observed_price is None:
                raise ValueError("Could not verify item price before add-to-cart")
            if observed_price > max_item_price:
                raise ValueError("Observed item price exceeds requested max_item_price")
            if observed_price > Decimal(str(approved["max_item_price"])):
                raise ValueError("Observed item price exceeds Joy's approved item cap")
            availability = str(product.get("stock_availability") or "")
            if re.search(r"out of stock|currently unavailable|unavailable", availability, re.IGNORECASE):
                raise ValueError("Approved item is not available")

            precheck_expr = ADD_TO_CART_PRECHECK_JS.replace("__QUANTITY__", str(quantity))
            precheck = _evaluate(browser, session_id, precheck_expr) or {}
            if precheck.get("challenge_reason"):
                raise ValueError(str(precheck["challenge_reason"]))
            if precheck.get("unexpected_reason"):
                raise ValueError(str(precheck["unexpected_reason"]))
            if precheck.get("subscription_selected"):
                raise ValueError("A Subscribe & Save/subscription option appears selected; refusing add-to-cart")
            if precheck.get("quantity_state") == "requested_quantity_not_available":
                raise ValueError("Requested quantity was not available in the buy box quantity selector")
            if not precheck.get("add_button_visible") or precheck.get("add_button_disabled"):
                raise ValueError("Add-to-cart button was not available for the approved item")

            click_result = _evaluate(browser, session_id, ADD_TO_CART_CLICK_JS) or {}
            if not click_result.get("clicked"):
                raise ValueError(str(click_result.get("reason") or "Add-to-cart click was refused"))
            time.sleep(2.0)
            _navigate_and_wait(browser, session_id, "https://www.amazon.com/gp/cart/view.html")
            cart = _evaluate(browser, session_id, CART_EXTRACT_JS) or {}
            cart["url"] = "https://www.amazon.com/gp/cart/view.html"
            return {
                "operation": "add_to_cart",
                "status": "completed_add_to_cart_only",
                "approval_reference": approved["approval_reference"],
                "approved_item": {
                    "asin": asin,
                    "requested_quantity": quantity,
                    "purchase_mode": purchase_mode,
                    "requested_max_item_price": str(max_item_price),
                    "observed_item_price": str(observed_price),
                    "title": product.get("product_title"),
                    "seller": product.get("seller"),
                    "ships_from": product.get("ship_from"),
                    "availability": product.get("stock_availability"),
                },
                "cart": cart,
                "safety_boundary": "Stopped after add-to-cart and cart inspection. No checkout, Buy Now, Place Order, payment, address, account, cookie, local storage, raw CDP, DOM, screenshot, or credential data was exposed.",
            }
        finally:
            with contextlib.suppress(Exception):
                browser.call("Target.closeTarget", {"targetId": target_id})

    return _with_browser(run)


def _current_page_summary() -> dict[str, Any]:
    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        result = _evaluate(browser, session_id, SUMMARY_EXTRACT_JS) or {}
        location = _evaluate(browser, session_id, "location.href") or ""
        if location:
            result["url"] = _sanitize_url(str(location))
        result["operation"] = "current_page_summary"
        return result

    return _with_browser(run)


def shopping_browser_status_tool(args: dict[str, Any], **_kw: Any) -> str:
    status = {
        "toolset": TOOLSET,
        "namespace": NAMESPACE,
        "workload": WORKLOAD,
        "kubectl_available": shutil.which("kubectl") is not None,
        "remote_debug_port": REMOTE_DEBUG_PORT,
        "read_only_operations": ["inspect_product", "inspect_reviews", "inspect_cart", "current_page_summary"],
        "approval_gated_operations": {"add_to_cart": sorted(APPROVED_CART_ADDITIONS)},
        "blocked_operations": sorted(UNSAFE_OPERATIONS),
        "secret_policy": "No raw CDP URLs, cookies, local storage, request headers, screenshots, downloads, vault contents, passwords, passkeys, 2FA, or CAPTCHA data are returned.",
    }
    return _json(status)


def shopping_browser_inspect_product_tool(args: dict[str, Any], **_kw: Any) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return _json({"error": "url is required"})
    try:
        return _json(_inspect_product(url))
    except Exception as exc:
        return _json({"error": "INSPECT_PRODUCT_FAILED", "message": str(exc)[:1000], "operation": "inspect_product"})


def shopping_browser_inspect_reviews_tool(args: dict[str, Any], **_kw: Any) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return _json({"error": "url is required"})
    try:
        max_reviews = _bounded_max_reviews(args.get("max_reviews"))
        return _json(_inspect_reviews(url, max_reviews))
    except Exception as exc:
        return _json({"error": "INSPECT_REVIEWS_FAILED", "message": str(exc)[:1000], "operation": "inspect_reviews"})


def shopping_browser_inspect_cart_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_inspect_cart())
    except Exception as exc:
        return _json({"error": "INSPECT_CART_FAILED", "message": str(exc)[:1000], "operation": "inspect_cart"})



def shopping_browser_add_to_cart_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        url_or_asin = str(args.get("url_or_asin") or args.get("url") or args.get("asin") or "").strip()
        quantity = _parse_quantity(args.get("quantity"))
        max_item_price = _parse_decimal_money(args.get("max_item_price"), "max_item_price")
        purchase_mode = str(args.get("purchase_mode") or "one_time").strip().lower().replace("-", "_")
        if purchase_mode != "one_time":
            return _json({"error": "SUBSCRIPTION_NOT_APPROVED", "message": "Only purchase_mode='one_time' is approved for this tool invocation.", "operation": "add_to_cart"})
        return _json(_add_to_cart(url_or_asin, quantity, max_item_price, purchase_mode))
    except Exception as exc:
        return _json({"error": "ADD_TO_CART_FAILED", "message": str(exc)[:1000], "operation": "add_to_cart"})


def shopping_browser_current_page_summary_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_current_page_summary())
    except Exception as exc:
        return _json({"error": "CURRENT_PAGE_SUMMARY_FAILED", "message": str(exc)[:1000], "operation": "current_page_summary"})


def shopping_browser_guardrail_check_tool(args: dict[str, Any], **_kw: Any) -> str:
    operation = str(args.get("operation") or "").strip()
    if not operation:
        return _json({"error": "operation is required"})
    return _json(_reject_unsafe_operation(operation))


STATUS_SCHEMA = {
    "name": "shopping_browser_status",
    "description": "Show the shopping browser bridge status and safety boundary.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

INSPECT_PRODUCT_SCHEMA = {
    "name": "shopping_browser_inspect_product",
    "description": "Read-only Amazon product inspection through the Kasm shopping session. Returns product title, logged-in price, delivery/Prime text, availability, seller, ship-from text, and public Amazon product image URLs when visible. Does not expose cookies, local storage, request headers, raw CDP, screenshots, or browser handles.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTPS Amazon product URL to inspect"},
        },
        "required": ["url"],
    },
}

INSPECT_REVIEWS_SCHEMA = {
    "name": "shopping_browser_inspect_reviews",
    "description": "Read-only Amazon review inspection through the Kasm shopping session. Returns only bounded public review metadata and excerpts visible from the product/review page; max_reviews is capped at 10. Does not expose cookies, local storage, request headers, raw CDP, screenshots, or browser handles.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTPS Amazon product or product-reviews URL to inspect"},
            "max_reviews": {"type": "integer", "description": "Maximum review excerpts to return; capped at 10", "minimum": 1, "maximum": 10, "default": DEFAULT_MAX_REVIEWS},
        },
        "required": ["url"],
    },
}

INSPECT_CART_SCHEMA = {
    "name": "shopping_browser_inspect_cart",
    "description": "Read-only Amazon cart inspection through the Kasm shopping session. Returns cart line item names, quantities, prices, subtotal, and delivery estimate when visible. Does not add, remove, update, checkout, or expose secrets.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


ADD_TO_CART_SCHEMA = {
    "name": "shopping_browser_add_to_cart",
    "description": "Approval-gated Amazon add-to-cart-only tool. It only accepts exact ASINs/URLs on the current Puppet-managed allowlist, requires quantity, max_item_price, and purchase_mode='one_time', verifies the product/price/seller/ship-from/availability before adding, then stops after returning inspected cart state. It cannot checkout, Buy Now, Place Order, change payment/address/account, or expose raw browser/session data.",
    "parameters": {
        "type": "object",
        "properties": {
            "url_or_asin": {"type": "string", "description": "Exact approved Amazon product URL or ASIN"},
            "quantity": {"type": "integer", "description": "Exact approved quantity", "minimum": 1, "maximum": 3},
            "max_item_price": {"type": "string", "description": "Maximum acceptable pre-tax item price, e.g. 7.95"},
            "purchase_mode": {"type": "string", "description": "Purchase mode; only 'one_time' is accepted", "enum": ["one_time"]},
        },
        "required": ["url_or_asin", "quantity", "max_item_price", "purchase_mode"],
    },
}

CURRENT_PAGE_SUMMARY_SCHEMA = {
    "name": "shopping_browser_current_page_summary",
    "description": "Read-only summary of the current Kasm shopping browser page using safe structured fields only.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

GUARDRAIL_SCHEMA = {
    "name": "shopping_browser_guardrail_check",
    "description": "Check whether a shopping-browser operation is allowed. Arbitrary mutations/navigation/account/payment/order/raw-session operations are rejected; add_to_cart is available only through the exact approval-gated tool schema.",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "description": "Operation name to check, e.g. add_to_cart or checkout"},
        },
        "required": ["operation"],
    },
}

registry.register(
    name=STATUS_SCHEMA["name"],
    toolset=TOOLSET,
    schema=STATUS_SCHEMA,
    handler=shopping_browser_status_tool,
    check_fn=_check_shopping_browser,
    description=STATUS_SCHEMA["description"],
    emoji="🛡️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=INSPECT_PRODUCT_SCHEMA["name"],
    toolset=TOOLSET,
    schema=INSPECT_PRODUCT_SCHEMA,
    handler=shopping_browser_inspect_product_tool,
    check_fn=_check_shopping_browser,
    description=INSPECT_PRODUCT_SCHEMA["description"],
    emoji="🛒",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=INSPECT_REVIEWS_SCHEMA["name"],
    toolset=TOOLSET,
    schema=INSPECT_REVIEWS_SCHEMA,
    handler=shopping_browser_inspect_reviews_tool,
    check_fn=_check_shopping_browser,
    description=INSPECT_REVIEWS_SCHEMA["description"],
    emoji="⭐",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=INSPECT_CART_SCHEMA["name"],
    toolset=TOOLSET,
    schema=INSPECT_CART_SCHEMA,
    handler=shopping_browser_inspect_cart_tool,
    check_fn=_check_shopping_browser,
    description=INSPECT_CART_SCHEMA["description"],
    emoji="🧾",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=ADD_TO_CART_SCHEMA["name"],
    toolset=TOOLSET,
    schema=ADD_TO_CART_SCHEMA,
    handler=shopping_browser_add_to_cart_tool,
    check_fn=_check_shopping_browser,
    description=ADD_TO_CART_SCHEMA["description"],
    emoji="🛒",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=CURRENT_PAGE_SUMMARY_SCHEMA["name"],
    toolset=TOOLSET,
    schema=CURRENT_PAGE_SUMMARY_SCHEMA,
    handler=shopping_browser_current_page_summary_tool,
    check_fn=_check_shopping_browser,
    description=CURRENT_PAGE_SUMMARY_SCHEMA["description"],
    emoji="📄",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=GUARDRAIL_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GUARDRAIL_SCHEMA,
    handler=shopping_browser_guardrail_check_tool,
    check_fn=_check_shopping_browser,
    description=GUARDRAIL_SCHEMA["description"],
    emoji="🚫",
    max_result_size_chars=MAX_RESULT_CHARS,
)


if __name__ == "__main__":
    assert _reject_unsafe_operation("add_to_cart")["allowed"] is True
    assert _reject_unsafe_operation("checkout")["allowed"] is False
    assert _reject_unsafe_operation("local_storage")["allowed"] is False
    assert _reject_unsafe_operation("inspect_cart")["allowed"] is True
    assert _reject_unsafe_operation("inspect_reviews")["allowed"] is True
    assert _extract_asin("https://www.amazon.com/example/dp/B09JJNBB9C?x=1") == "B09JJNBB9C"
    assert _review_url("https://www.amazon.com/example/dp/B09JJNBB9C?x=1")[0] == "https://www.amazon.com/product-reviews/B09JJNBB9C"
    assert _bounded_max_reviews(99) == MAX_REVIEWS
    assert _product_url_from_url_or_asin("B01J01XGPK") == ("https://www.amazon.com/dp/B01J01XGPK", "B01J01XGPK")
    assert _approved_cart_addition("B01J01XGPK", 1, Decimal("7.95"), "one_time")["quantity"] == 1
    assert not any(word in json.dumps(STATUS_SCHEMA).lower() for word in ("cookie", "localstorage"))
    product = {"image_url_candidates": ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg?x=1", "https://example.com/not-amazon.jpg"]}
    _normalize_product_images(product)
    assert product["primary_image_url"] == "https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"
    assert product["image_urls"] == ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"]
    print("shopping_browser_tool smoke ok")

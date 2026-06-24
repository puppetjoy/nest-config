"""Broad secure browser bridge for Star.

This custom Hermes toolset exposes browser-like control of the Puppet/KubeCM
managed Kasm secure browser while keeping the raw Chrome DevTools endpoint,
cookies, local storage, request headers, downloads, and credential material out
of model-visible tool results.  Screenshots are scoped to the persistent
secure browser viewport and returned only as local media artifacts.  Policy
lives in the tool descriptions, bounded argument schemas, lightweight runtime
guardrails, and a high-level audit log rather than in one-off helpers for every
shopping action.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import websockets.sync.client
from tools.registry import registry

TOOLSET = "secure_browser"
NAMESPACE = os.environ.get("SECURE_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("SECURE_BROWSER_WORKLOAD", "deployment/secure-browser")
REMOTE_DEBUG_PORT = int(os.environ.get("SECURE_BROWSER_CDP_PORT", "9222"))
CDP_ENDPOINT_URL = os.environ.get("SECURE_BROWSER_CDP_URL", "").rstrip("/")
BROWSER_OWNER = os.environ.get("SECURE_BROWSER_OWNER", "shopping")
OWNERSHIP_STATE_PATH = os.environ.get("SECURE_BROWSER_OWNERSHIP_STATE", os.path.expanduser("~/.hermes/secure-browser-tabs.json"))
BROWSER_DISPLAY = os.environ.get("SECURE_BROWSER_DISPLAY", ":1")
XWD_TIMEOUT_SECONDS = float(os.environ.get("SECURE_BROWSER_XWD_TIMEOUT_SECONDS", "15"))
MAX_RESULT_CHARS = 16000
MAX_TEXT_CHARS = 12000
MAX_LINKS = 80
MAX_QUERY_RESULT_CHARS = 8000
MAX_TYPE_CHARS = 2000
SCREENSHOT_DIR = os.environ.get("SECURE_BROWSER_SCREENSHOT_DIR", os.path.expanduser("~/.hermes/profiles/star/secure-browser-screenshots"))
OWNER_CHECKOUT_REVIEW_DIR = os.environ.get("SECURE_BROWSER_OWNER_REVIEW_DIR", os.path.expanduser("~/.hermes/profiles/star/secure-browser-owner-checkout-reviews"))
AUDIT_LOG = os.environ.get("SECURE_BROWSER_AUDIT_LOG", os.path.expanduser("~/.hermes/profiles/star/secure-browser-audit.log"))
FINAL_PURCHASE_STATE_PATH = os.environ.get("SECURE_BROWSER_FINAL_PURCHASE_STATE", os.path.expanduser("~/.hermes/profiles/star/secure-browser-final-purchase-approvals.json"))
SECURE_BROWSER_ORDER_LEDGER_PATH = os.environ.get("SECURE_BROWSER_ORDER_LEDGER_PATH", os.path.expanduser("~/.hermes/profiles/star/secure-browser-order-ledger.sqlite3"))
MAX_PRODUCT_IMAGES = 6
DEFAULT_MAX_REVIEWS = 5
MAX_REVIEWS = 10
REVIEW_EXCERPT_CHARS = 900
MAX_VISUAL_CROPS = 6
MAX_VISUAL_REGIONS = 60
MAX_OWNER_REVIEW_VIEWPORTS = 12
MAX_CROP_PADDING = 80
MIN_CROP_SIZE = 8
MAX_CROP_NAME_CHARS = 80
CDP_MAX_MESSAGE_BYTES = 32 * 1024 * 1024
PORT_FORWARD_TIMEOUT_SECONDS = 20
PAGE_LOAD_TIMEOUT_SECONDS = 15
APPROVED_CART_ADDITIONS = {
    "B01J01XGPK": {
        "approval_reference": "agent-request ar-20260606-001458-375534 / kanban t_03ac4852",
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
    "update_cart",
    "buy_now",
    "place_order",
    "account_settings",
    "screenshot_sensitive_page",
    "edit_address",
    "edit_payment",
    "download_account_data",
    "export_account_data",
    "raw_cdp",
    "cookies",
    "local_storage",
    "download",
}

SENSITIVE_ACTION_RE = re.compile(
    r"\b(place\s+order|buy\s+now|payment|wallet|address|billing|card|cvv|cvc|subscribe\s*&\s*save|passkey|password|verification\s+code|captcha)\b",
    re.IGNORECASE,
)
HUMAN_TAKEOVER_URL_RE = re.compile(
    r"\b(sign\s*in|signin|login|ap/signin|bitwarden|passkey|password|two[- ]?factor|2fa|otp|verification\s+code|captcha|security\s+check|payment|wallet|billing|address|card|cvv|cvc)\b",
    re.IGNORECASE,
)
CHECKOUT_PREP_RE = re.compile(r"\b(proceed\s+to\s+checkout|checkout|review\s+your\s+order|shipping\s+(?:option|speed|method)|delivery\s+(?:option|date|window)|continue)\b", re.IGNORECASE)
FINAL_PURCHASE_RE = re.compile(r"\b(place\s+(?:your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(?:purchase|order))\b", re.IGNORECASE)
HUMAN_TAKEOVER_RE = re.compile(r"\b(sign\s*in|login|bitwarden|passkey|password|two[- ]?factor|2fa|otp|verification\s+code|captcha|security\s+check|suspicious|payment|wallet|card|cvv|cvc|billing|address|phone|email)\b", re.IGNORECASE)
CART_URL_RE = re.compile(r"/(gp/)?cart(/|$)", re.IGNORECASE)
CART_REMOVE_TEXT_RE = re.compile(r"\b(delete|remove)\b", re.IGNORECASE)
CHECKOUT_APPROVED_EFFECTS = ("checkout_prep", "select_shipping_option", "select_delivery_option", "apply_checkout_option", "fix_purchase_mode", "cart_line_adjustment")
APPROVED_CLICK_EFFECTS = ("browse", "select_option", "apply_visible_coupon", "add_to_cart", "remove_from_cart") + CHECKOUT_APPROVED_EFFECTS
APPROVED_TYPE_EFFECTS = ("type", "apply_checkout_option", "cart_line_adjustment")
SENSITIVE_FIELD_RE = re.compile(r"(password|passkey|otp|verification|card|cvv|cvc|security.?code|address|phone|email)", re.IGNORECASE)
SENSITIVE_TYPED_TEXT_RE = re.compile(
    r"([\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|\b(?:\d[ -]*?){12,19}\b|\b(?:cvv|cvc|security code)\s*[:#-]?\s*\d+\b|\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b)",
    re.IGNORECASE,
)
CHECKOUTISH_PAGE_RE = re.compile(r"checkout|buy|payselect|ship|spc|review|ordering", re.IGNORECASE)
CHECKOUT_QUERY_PAGE_RE = re.compile(r"checkout|payselect|spc|ordering|place[-\s]?order|review\s+your\s+order|order\s+review|/gp/buy|/buy|shipping\s+(address|option|speed|method)|delivery\s+(option|date|window)", re.IGNORECASE)
POST_PURCHASE_CONFIRMATION_RE = re.compile(r"thank\s*you|order\s+(?:confirmation|confirmed|placed|received)|purchase\s+(?:complete|completed|confirmed)|/gp/buy/thankyou|thankyou|order-confirmation", re.IGNORECASE)
AMAZON_ORDERS_RE = re.compile(r"/gp/(?:css/)?order-history|/gp/your-account/order|/your-orders|/order-details|orderID=", re.IGNORECASE)
SAFE_CHECKOUT_SENSITIVE_LABEL_RE = re.compile(r"shipping\s+(speed|option|method)|delivery\s+(option|date|window)|gift(?!\s*card\s*(number|code))|gift\s+card\s+balance|use\s+a\s+gift\s+card|coupon|promo|promotion|claim\s+code|payment\s+(summary|method|option)|paying\s+with|quantity|qty|delete|remove|one[-\s]?time|subscribe|subscription|cart", re.IGNORECASE)
MUTATING_QUERY_RE = re.compile(r"\b(click|submit|fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|cookie|setAttribute|removeAttribute|appendChild|removeChild|innerHTML\s*=|location\s*=|open\s*\()\b", re.IGNORECASE)


FINAL_PURCHASE_CLICK_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const finalRe = /\b(place\s+(?:your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(?:purchase|order))\b/i;
  const visible = (node) => {
    const style = window.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const enabled = (node) => !node.disabled && node.getAttribute('aria-disabled') !== 'true';
  const normalizeLabel = (label) => clean(label).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const actionPath = (node) => {
    const explicitAction = node.getAttribute('formaction');
    const form = node.form || node.closest?.('form');
    const action = explicitAction || form?.getAttribute?.('action') || form?.action || '';
    if (!action) return '';
    try {
      return new URL(action, location.href).pathname.replace(/\/+$/, '');
    } catch (_err) {
      return String(action).split(/[?#]/)[0].replace(/\/+$/, '');
    }
  };
  const rawControls = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"], a'))
    .map((node) => {
      const label = clean(node.innerText || node.value || node.getAttribute('aria-label') || node.textContent || '');
      const normalizedLabel = normalizeLabel(label);
      return {node, label, normalizedLabel};
    })
    .filter(({node, label}) => label && finalRe.test(label) && visible(node) && enabled(node));
  const controls = rawControls
    .filter((control) => !rawControls.some((other) => control.node !== other.node && control.node.contains(other.node) && control.normalizedLabel === other.normalizedLabel))
    .map((control) => {
      const rect = control.node.getBoundingClientRect();
      const tag = String(control.node.tagName || '').toLowerCase();
      const type = clean(control.node.getAttribute('type') || control.node.type || '').toLowerCase();
      const formMethod = clean(control.node.getAttribute('formmethod') || control.node.form?.method || '').toLowerCase();
      const effectKey = [control.normalizedLabel, tag, type, formMethod, actionPath(control.node)].join('|');
      return {...control, rect, effectKey};
    });
  if (controls.length < 1) {
    return {clicked: false, reason: 'No visible enabled final purchase control matched.'};
  }
  const effectKeys = Array.from(new Set(controls.map((control) => control.effectKey)));
  if (effectKeys.length > 1) {
    const groups = effectKeys.slice(0, 4).map((key) => {
      const group = controls.filter((control) => control.effectKey === key);
      const label = group[0]?.label || 'final purchase control';
      return `${label.slice(0, 80)} x${group.length}`;
    }).join('; ');
    return {clicked: false, reason: `Multiple distinct final purchase controls matched (${controls.length}: ${groups}); refusing ambiguous final purchase.`};
  }
  controls.sort((left, right) => {
    const leftInViewport = left.rect.top >= 0 && left.rect.left >= 0 && left.rect.bottom <= window.innerHeight && left.rect.right <= window.innerWidth;
    const rightInViewport = right.rect.top >= 0 && right.rect.left >= 0 && right.rect.bottom <= window.innerHeight && right.rect.right <= window.innerWidth;
    if (leftInViewport !== rightInViewport) return leftInViewport ? -1 : 1;
    return (left.rect.top - right.rect.top) || (left.rect.left - right.rect.left);
  });
  const control = controls[0];
  const rect = control.rect;
  control.node.click();
  return {
    clicked: true,
    control_label: control.label.slice(0, 120),
    control_rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
    page_title_before_click: document.title || '',
    url_before_click: location.href || ''
  };
})()
"""

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
    product_condition: firstText([
      '#condition-value',
      '#buybox #condition-value',
      '#desktop_buybox #condition-value',
      '#buybox [id*="condition" i]',
      '#desktop_buybox [id*="condition" i]',
      '#buybox [data-csa-c-content-id*="condition" i]',
      '#desktop_buybox [data-csa-c-content-id*="condition" i]'
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
  const conditionText = clean([
    text('#condition-value'),
    text('#buybox #condition-value'),
    text('#desktop_buybox #condition-value'),
    text('#buybox [id*="condition" i]'),
    text('#desktop_buybox [id*="condition" i]'),
    text('#buybox [data-csa-c-content-id*="condition" i]'),
    text('#desktop_buybox [data-csa-c-content-id*="condition" i]')
  ].filter(Boolean).join(' '));
  const selectedOfferText = clean(Array.from(document.querySelectorAll('#buyBoxAccordion input[type="radio"]:checked, #buybox input[type="radio"]:checked, #desktop_buybox input[type="radio"]:checked'))
    .map((input) => clean((input.closest('label, .a-accordion-row, .a-box, .a-section, li, div') || input).textContent))
    .filter(Boolean)
    .join(' '));
  const conditionSummary = (conditionText || selectedOfferText || '').slice(0, 240);
  const buyBoxText = clean([
    text('#buybox'),
    text('#desktop_buybox'),
    text('#apex_desktop')
  ].filter(Boolean).join(' '));
  const buyBoxLower = buyBoxText.toLowerCase();
  const unsafeConditionRe = /\b(used|renewed|refurbished|pre-owned|open box)\b/i;
  const unexpectedReason = (() => {
    if (conditionSummary && unsafeConditionRe.test(conditionSummary)) return `Buy box appears to offer a used, renewed, or refurbished item: ${conditionSummary}`;
    if (/\b(digital|kindle)\b/i.test(buyBoxLower)) return 'Buy box appears to offer a digital item.';
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
    condition_summary: conditionSummary || 'not_visible',
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


PAGE_SNAPSHOT_JS = r"""
(() => {
  const maxText = __MAX_TEXT_CHARS__;
  const maxLinks = __MAX_LINKS__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const redact = (value) => clean(value)
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email redacted]')
    .replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '[phone redacted]')
    .replace(/\b(?:\d[ -]*?){12,19}\b/g, '[payment/account number redacted]')
    .replace(/\b(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9-]{8,}\b/gi, '[order reference redacted]')
    .replace(/\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b/gi, '[street address redacted]')
    .replace(/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/g, '[state/zip redacted]')
    .replace(/\b\d{5}(?:-\d{4})?\b/g, '[zip redacted]');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const describe = (el) => {
    const parts = [];
    if (el.tagName) parts.push(el.tagName.toLowerCase());
    if (el.id) parts.push(`#${el.id}`);
    if (el.getAttribute('name')) parts.push(`[name="${el.getAttribute('name')}"]`);
    if (el.getAttribute('aria-label')) parts.push(`aria="${redact(el.getAttribute('aria-label')).slice(0, 80)}"`);
    if (el.getAttribute('role')) parts.push(`role=${el.getAttribute('role')}`);
    const label = redact(el.innerText || el.value || el.textContent || '').slice(0, 140);
    if (label) parts.push(`text="${label}"`);
    return parts.join(' ');
  };
  const bodyText = redact(document.body ? document.body.innerText : '').slice(0, maxText);
  const interactive = Array.from(document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [onclick]'))
    .filter(visible)
    .slice(0, maxLinks)
    .map((el, idx) => ({index: idx + 1, selector: uniqueSelector(el), description: describe(el).slice(0, 260)}));
  function uniqueSelector(el) {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const name = el.getAttribute('name');
    if (name && el.tagName) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria && el.tagName) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
    const path = [];
    let cur = el;
    while (cur && cur.nodeType === Node.ELEMENT_NODE && path.length < 5) {
      let part = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((sib) => sib.tagName === cur.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      path.unshift(part);
      cur = parent;
    }
    return path.join(' > ');
  }
  return {
    page_title: document.title || '',
    url: location.href || '',
    text: bodyText,
    text_truncated: bodyText.length >= maxText,
    interactive,
    sanitization: 'Visible text and control descriptions redact emails, phone numbers, street/zip address details, long payment/account numbers, and order references before returning to Star.'
  };
})()
"""

CLICK_JS = r"""
(() => {
  const selector = __SELECTOR__;
  const node = document.querySelector(selector);
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  if (!node) return {clicked: false, reason: 'selector did not match any element'};
  if (node.disabled || node.getAttribute('aria-disabled') === 'true') return {clicked: false, reason: 'matched element is disabled'};
  node.scrollIntoView({block: 'center', inline: 'center'});
  const text = clean(node.innerText || node.value || node.getAttribute('aria-label') || node.textContent || '');
  node.click();
  return {clicked: true, element_text: text.slice(0, 240), page_title: document.title || '', url: location.href || ''};
})()
"""

CART_REMOVE_CONTROL_JS = r"""
(() => {
  const selector = __SELECTOR__;
  const node = document.querySelector(selector);
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  if (!node) return {exists: false};
  const style = window.getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  const ariaLabel = clean(node.getAttribute('aria-label') || '');
  const value = clean(node.value || '');
  const text = clean(node.innerText || node.textContent || '');
  const name = clean(node.getAttribute('name') || '');
  const title = clean(node.getAttribute('title') || '');
  const id = clean(node.getAttribute('id') || '');
  const role = clean(node.getAttribute('role') || '');
  const labelledBy = clean(node.getAttribute('aria-labelledby') || '');
  const labelledByText = labelledBy.split(/\s+/)
    .map((idValue) => clean((document.getElementById(idValue) || {}).textContent || ''))
    .filter(Boolean)
    .join(' ');
  const item = node.closest('[data-asin], [data-itemid], .sc-list-item, .sc-item, li, form, [role="listitem"]');
  return {
    exists: true,
    disabled: Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true'),
    visible: Boolean(rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'),
    tag: clean(node.tagName || ''),
    type: clean(node.getAttribute('type') || ''),
    role,
    text,
    value,
    aria_label: ariaLabel,
    labelled_by_text: labelledByText,
    name,
    title,
    id,
    item_text: clean(item ? item.textContent : '').slice(0, 500),
    page_title: document.title || '',
    url: location.href || ''
  };
})()
"""


CHECKOUT_CONTROL_JS = r"""
(() => {
  const selector = __SELECTOR__;
  const node = document.querySelector(selector);
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  if (!node) return {exists: false};
  const style = window.getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  const ariaLabel = clean(node.getAttribute('aria-label') || '');
  const value = clean(node.value || '');
  const text = clean(node.innerText || node.textContent || '');
  const name = clean(node.getAttribute('name') || '');
  const title = clean(node.getAttribute('title') || '');
  const id = clean(node.getAttribute('id') || '');
  const role = clean(node.getAttribute('role') || '');
  return {
    exists: true,
    disabled: Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true'),
    visible: Boolean(rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'),
    tag: clean(node.tagName || ''),
    type: clean(node.getAttribute('type') || ''),
    role,
    text,
    value,
    aria_label: ariaLabel,
    name,
    title,
    id,
    page_title: document.title || '',
    url: location.href || ''
  };
})()
"""

CHECKOUT_PAGE_SAFETY_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const pageText = clean(document.body ? document.body.innerText : '');
  const lower = pageText.toLowerCase();
  const blockedReason = (() => {
    if (document.querySelector('form[action*="validateCaptcha"], input[name="password"], input[type="password"], input[name*="otp" i], input[name*="verification" i], input[name*="cvv" i], input[name*="cvc" i]')) return 'Sensitive login, verification, CAPTCHA, or payment security field is visible; Joy must take over.';
    if (/enter the characters you see below|not a robot|captcha/.test(lower)) return 'CAPTCHA or robot-check page is visible; Joy must take over.';
    if (/sign in|password|passkey|verification code|two[- ]?factor|2fa|security check|suspicious/.test(lower)) return 'Login, passkey, 2FA, or security prompt is visible; Joy must take over.';
    return '';
  })();
  const finalControls = Array.from(document.querySelectorAll('a, button, input, [role="button"], [role="link"]'))
    .map((el) => clean(el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || ''))
    .filter((label) => /place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(purchase|order)/i.test(label))
    .slice(0, 8);
  return {
    page_title: document.title || '',
    url: location.href || '',
    blocked_reason: blockedReason,
    final_purchase_controls_visible: finalControls,
    checkout_prep_state: blockedReason ? 'human_takeover_required' : 'checkout_prep_visible'
  };
})()
"""


CHECKOUT_PREP_CONTROLS_JS = r"""
(() => {
  const maxControls = __MAX_CONTROLS__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-secure-browser-checkout-control]').forEach((node) => node.removeAttribute('data-secure-browser-checkout-control'));
  const redact = (value) => clean(value)
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email redacted]')
    .replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '[phone redacted]')
    .replace(/\b(?:\d[ -]*?){12,19}\b/g, '[payment number redacted]')
    .replace(/\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b/gi, '[street address redacted]')
    .replace(/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/g, '[state/zip redacted]')
    .replace(/\b\d{5}(?:-\d{4})?\b/g, '[zip redacted]');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return Boolean(style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0);
  };
  const selectorFor = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';
    const unsafeSelectorText = /(password|passkey|otp|verification|captcha|cvv|cvc|card|payment|wallet|address|phone|email|login|signin)/i;
    if (el.id && !unsafeSelectorText.test(el.id)) return `#${CSS.escape(el.id)}`;
    const name = el.getAttribute('name');
    if (name && !unsafeSelectorText.test(name)) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    const dataTestId = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '';
    if (dataTestId && !unsafeSelectorText.test(dataTestId)) return `${el.tagName.toLowerCase()}[data-testid="${CSS.escape(dataTestId)}"]`;
    const aria = el.getAttribute('aria-label') || '';
    if (aria && aria.length <= 90 && !unsafeSelectorText.test(aria)) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
    const path = [];
    let cur = el;
    while (cur && cur.nodeType === Node.ELEMENT_NODE && path.length < 5) {
      let part = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((sib) => sib.tagName === cur.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      path.unshift(part);
      cur = parent;
    }
    return path.join(' > ');
  };
  const tagName = (el) => clean(el.tagName || '').toUpperCase();
  const labelFor = (el) => {
    const labelledBy = clean(el.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map((id) => clean((document.getElementById(id) || {}).textContent || ''))
      .filter(Boolean)
      .join(' ');
    const own = clean(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '');
    const controlTarget = tagName(el) === 'LABEL' && el.getAttribute('for') ? document.getElementById(el.getAttribute('for')) : null;
    const controlTargetText = controlTarget ? clean([controlTarget.value, controlTarget.getAttribute('aria-label'), controlTarget.name, controlTarget.id].join(' ')) : '';
    const contextNode = el.closest('label, li, tr, fieldset, [role="radio"], [role="checkbox"], [role="option"]');
    const rawContext = clean((contextNode || el).innerText || '');
    const context = rawContext.length <= 220 && !/place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(purchase|order)/i.test(rawContext) ? rawContext : '';
    return redact([labelledBy, own, controlTargetText, context].filter(Boolean).join(' | ')).slice(0, 240);
  };
  const stateFor = (el) => {
    const controlTarget = tagName(el) === 'LABEL' && el.getAttribute('for') ? document.getElementById(el.getAttribute('for')) : null;
    const target = controlTarget || el;
    const targetTag = tagName(target);
    const targetRole = clean(target.getAttribute('role') || '').toLowerCase();
    const targetType = clean(target.getAttribute('type') || '').toLowerCase();
    const supportsBooleanState = targetTag === 'OPTION' || ['radio', 'checkbox'].includes(targetType) || ['radio', 'checkbox', 'option'].includes(targetRole);
    const checked = Boolean(target.checked || target.getAttribute('aria-checked') === 'true');
    const selected = Boolean(target.selected || target.getAttribute('aria-selected') === 'true' || checked);
    return {
      checked,
      selected,
      state: supportsBooleanState ? (selected ? 'selected' : 'not_selected') : 'not_applicable'
    };
  };
  const regionFor = (label) => {
    if (/subscribe|subscription|delivery every|one[-\s]?time|purchase option/i.test(label)) return 'purchase_mode';
    if (/shipping speed|shipping option|shipping method|delivery option|delivery date|delivery day|arrives|ship/i.test(label)) return 'shipping_delivery';
    if (/payment\s+(summary|method|option)|paying\s+with|gift\s*card|coupon|promo|promotion|claim\s+code|apply|\b(?:visa|mastercard|amex|american express|discover)\b/i.test(label)) return 'payment_gift_card';
    if (/this is a gift|gift option/i.test(label)) return 'gift_options';
    if (/qty|quantity|delete|remove|item|cart/i.test(label)) return 'cart_line_item';
    if (/coupon|promo|promotion|gift card|claim code|apply/i.test(label)) return 'payment_gift_card';
    if (/back|return to cart|cart|change/i.test(label)) return 'navigation_review';
    return 'checkout_review';
  };
  const effectHintsFor = (label, tag, type) => {
    const hints = [];
    if (/shipping speed|shipping option|shipping method/i.test(label)) hints.push('select_shipping_option');
    if (/delivery option|delivery date|delivery day|arrives/i.test(label)) hints.push('select_delivery_option');
    if (/subscribe|subscription|delivery every|one[-\s]?time|purchase option/i.test(label)) hints.push('fix_purchase_mode');
    if (/qty|quantity|delete|remove|item|cart/i.test(label) || (tag === 'SELECT' && /quantity/i.test(label))) hints.push('cart_line_adjustment');
    if (/payment\s+(summary|method|option)|paying\s+with|gift|coupon|promo|promotion|gift card|claim code|apply|change|\b(?:visa|mastercard|amex|american express|discover)\b/i.test(label)) hints.push('apply_checkout_option');
    if (/continue|checkout|review order/i.test(label)) hints.push('checkout_prep');
    return Array.from(new Set(hints.length ? hints : ['apply_checkout_option']));
  };
  const sensitiveControl = /(password|passkey|otp|verification|captcha|cvv|cvc|security code|card number|payment method|wallet|billing|address|phone|email|sign in|login|account settings)/i;
  const finalControl = /(place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(purchase|order))/i;
  const candidates = Array.from(document.querySelectorAll('a, button, input, select, textarea, label[for], [role="button"], [role="link"], [role="radio"], [role="checkbox"], [role="option"], [onclick]'));
  const controls = [];
  const finalPurchaseControls = [];
  const skippedSensitiveControls = [];
  const seen = new Set();
  for (const el of candidates) {
    if (!visible(el)) continue;
    const tag = tagName(el);
    const type = clean(el.getAttribute('type') || '').toLowerCase();
    const role = clean(el.getAttribute('role') || '');
    if (tag === 'INPUT' && ['hidden', 'password'].includes(type)) continue;
    const label = labelFor(el);
    const directBits = clean([el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '', el.id, el.getAttribute('name'), el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('autocomplete'), type, role].join(' '));
    const rawBits = clean([label, directBits].join(' '));
    if (!label && !rawBits) continue;
    if (finalControl.test(directBits)) {
      finalPurchaseControls.push(redact(label || rawBits).slice(0, 120));
      continue;
    }
    if (sensitiveControl.test(rawBits) && !/(shipping|delivery|payment\s+(summary|method|option)|paying\s+with|\b(?:visa|mastercard|amex|american express|discover)\b|gift|coupon|promo|claim code|quantity|qty|delete|remove|one[-\s]?time|subscribe|subscription)/i.test(rawBits)) {
      skippedSensitiveControls.push(redact(label || rawBits).slice(0, 120));
      continue;
    }
    const safeControlId = `sb-checkout-${controls.length + 1}`;
    el.setAttribute('data-secure-browser-checkout-control', safeControlId);
    const selector = `[data-secure-browser-checkout-control="${safeControlId}"]`;
    if (!selector || seen.has(selector)) continue;
    seen.add(selector);
    const rect = el.getBoundingClientRect();
    const controlState = stateFor(el);
    controls.push({
      selector,
      label: label || redact(rawBits).slice(0, 160),
      role: role || (tag === 'A' ? 'link' : (['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(tag) ? tag.toLowerCase() : 'interactive')),
      tag,
      input_type: type,
      region: regionFor(label || rawBits),
      approved_effect_hints: effectHintsFor(label || rawBits, tag, type),
      checked: controlState.checked,
      selected: controlState.selected,
      state: controlState.state,
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      viewport_rect: {x: Math.round(rect.left), y: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height)}
    });
    if (controls.length >= maxControls) break;
  }
  return {
    safe_controls: controls,
    safe_control_count: controls.length,
    final_purchase_controls_visible: finalPurchaseControls.slice(0, 8),
    final_purchase_control_count: finalPurchaseControls.length,
    sensitive_controls_suppressed_count: skippedSensitiveControls.length,
    policy: 'Checkout-prep control inventory returns sanitized labels/selectors for ordinary review-page controls only. Final order submission and address/payment/account/security controls are withheld or blocked.'
  };
})()
"""

ORDER_REVIEW_EXTRACT_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const pageText = document.body ? document.body.innerText : '';
  const lines = pageText
    .split(/\n+/)
    .flatMap((line) => clean(line).split(/(?<=\$[0-9][0-9,.]*|\.)\s+/))
    .map(clean)
    .filter(Boolean)
    .filter((line) => line.length <= 500);
  const pick = (patterns, limit = 5) => lines.filter((line) => patterns.some((re) => re.test(line))).slice(0, limit);
  const redactAddress = (value) => clean(value)
    .replace(/\b\d{1,6}\s+[^,]{2,80}\b(?:,\s*)?/g, '[street address redacted] ')
    .replace(/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/g, '[state/zip redacted]')
    .replace(/\b\d{5}(?:-\d{4})?\b/g, '[zip redacted]')
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email redacted]')
    .replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '[phone redacted]');
  const paymentLabels = pick([/ending in \d{4}/i, /\b(?:visa|mastercard|amex|american express|discover|gift card)\b/i], 4)
    .map((line) => clean(line.replace(/\b(?:card|account)?\s*\d{5,}\b/g, 'ending in [redacted except visible last four]')));
  const purchaseState = (() => {
    const controlNodes = Array.from(document.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"], option, [role="option"]'));
    const labelForControl = (el) => {
      const labelledBy = clean(el.getAttribute('aria-labelledby') || '').split(/\s+/)
        .map((id) => clean((document.getElementById(id) || {}).textContent || ''))
        .filter(Boolean)
        .join(' ');
      const explicitLabel = el.id ? clean((document.querySelector(`label[for="${CSS.escape(el.id)}"]`) || {}).innerText || '') : '';
      const contextNode = el.closest('label, li, tr, fieldset, [role="radio"], [role="checkbox"], [role="option"]');
      const context = clean((contextNode || el).innerText || '');
      return clean([labelledBy, explicitLabel, el.getAttribute('aria-label'), el.value, el.name, el.id, context].filter(Boolean).join(' | '));
    };
    const controlState = (el) => Boolean(el.checked || el.selected || el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true');
    const controls = controlNodes
      .map((el) => ({label: labelForControl(el), selected: controlState(el), disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')}))
      .filter((item) => /subscribe|subscription|save and subscribe|delivery every|one[-\s]?time|purchase option/i.test(item.label));
    const subscriptionControls = controls.filter((item) => /subscribe|subscription|save and subscribe|delivery every/i.test(item.label));
    const oneTimeControls = controls.filter((item) => /one[-\s]?time/i.test(item.label));
    const subscriptionOfferVisible = /subscribe|subscription|save and subscribe|delivery every/i.test(pageText);
    const subscriptionSelected = subscriptionControls.some((item) => item.selected);
    const oneTimeSelected = oneTimeControls.some((item) => item.selected);
    const purchaseMode = subscriptionSelected ? 'subscription_selected' : (oneTimeSelected ? 'one_time_confirmed' : (subscriptionOfferVisible ? 'subscription_offer_visible_only' : 'not_detected'));
    return {
      purchase_mode: purchaseMode,
      subscription_offer_visible: subscriptionOfferVisible,
      subscription_selected: subscriptionSelected,
      subscription_control_visible: subscriptionControls.length > 0,
      one_time_selected: oneTimeSelected,
      purchase_mode_controls: controls.slice(0, 8).map((item) => ({label: redactAddress(item.label).slice(0, 160), selected: item.selected, disabled: item.disabled}))
    };
  })();
  const rawSurpriseFlags = pick([/subscribe|subscription|save and subscribe|warranty|protection plan|used|renewed|refurbished|digital|restricted|age[- ]?restricted|shipping speed|delivery option/i], 12);
  const surpriseFlags = purchaseState.subscription_selected ? rawSurpriseFlags : rawSurpriseFlags.filter((line) => !/subscribe|subscription|save and subscribe|delivery every/i.test(line));
  const informationalFlags = purchaseState.subscription_offer_visible && !purchaseState.subscription_selected ? pick([/subscribe|subscription|save and subscribe|delivery every/i], 6) : [];
  const totalLines = pick([/subtotal|shipping|tax|estimated tax|order total|total/i], 12);
  const delivery = pick([/delivery|arrives|ship|shipping speed|window/i], 8);
  const items = pick([/qty|quantity|sold by|seller|\$\d/i], 15);
  const destination = pick([/ship to|deliver to|delivery address|shipping address/i], 4).map(redactAddress);
  return {
    page_title: document.title || '',
    url: location.href || '',
    items,
    totals: totalLines,
    delivery,
    shipping_destination_label_or_city_state: destination,
    payment_method_label_last_four_only: paymentLabels,
    purchase_mode: purchaseState.purchase_mode,
    subscription_offer_visible: purchaseState.subscription_offer_visible,
    subscription_selected: purchaseState.subscription_selected,
    subscription_control_visible: purchaseState.subscription_control_visible,
    one_time_selected: purchaseState.one_time_selected,
    purchase_mode_controls: purchaseState.purchase_mode_controls,
    informational_flags: informationalFlags,
    surprise_flags: surpriseFlags,
    policy: 'Sanitized checkout-prep/order-review summary only: street addresses, full payment/account/card numbers, emails, phone numbers, raw DOM, cookies, storage, and request headers are not returned. Star must pause for Joy on login, Bitwarden, passkeys, 2FA, CAPTCHA, suspicious security prompts, payment/address/account edits, or sensitive-information prompts.'
  };
})()
"""

POST_PURCHASE_EXTRACT_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const redact = (value) => clean(value)
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email redacted]')
    .replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '[phone redacted]')
    .replace(/\b(?:\d[ -]*?){12,19}\b/g, '[payment/account number redacted]')
    .replace(/\b(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9-]{6,}\b/gi, '[order reference redacted]')
    .replace(/\b\d{1,6}\s+[^\n,]{2,80}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b/gi, '[street address redacted]')
    .replace(/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/g, '[state/zip redacted]')
    .replace(/\b\d{5}(?:-\d{4})?\b/g, '[zip redacted]');
  const pageText = clean(document.body ? document.body.innerText : '');
  const lines = pageText
    .split(/(?:\n+|\s{2,})/)
    .map(redact)
    .filter(Boolean)
    .filter((line) => line.length <= 320);
  const pick = (patterns, limit = 5) => {
    const out = [];
    for (const line of lines) {
      if (patterns.some((re) => re.test(line)) && !out.includes(line)) out.push(line);
      if (out.length >= limit) break;
    }
    return out;
  };
  const url = location.href || '';
  const title = document.title || '';
  const lower = `${url} ${title} ${pageText}`.toLowerCase();
  const ordersVisible = /your orders|order history|buy again|orders placed|track package|view order details|order details/.test(lower);
  const confirmationVisible = /thank you|order placed|order confirmed|order received|purchase complete|confirmation/.test(lower) || /\/gp\/buy\/thankyou|thankyou|order-confirmation/i.test(url);
  return {
    page_title: title,
    url,
    post_purchase_state: ordersVisible ? 'post_purchase_orders_visible' : (confirmationVisible ? 'post_purchase_confirmation_visible' : 'post_purchase_context_visible'),
    confirmation_visible: confirmationVisible,
    orders_page_visible: ordersVisible,
    order_presence: pick([/thank you|order placed|order confirmed|order received|purchase complete|confirmation|your orders|order history|orders placed/i], 6),
    delivery_status: pick([/arriv(?:es|ing)|delivered|delivery|expected|estimated|by \w+day|today|tomorrow|track package|shipped|not yet shipped/i], 8),
    item_clues: pick([/qty|quantity|sold by|seller|buy it again|view item|return or replace|write a product review/i], 8),
    action_controls_visible: pick([/track package|view order details|buy it again|return or replace|cancel items|archive order|invoice/i], 8),
    policy: 'Sanitized post-purchase confirmation/order-verification summary only: raw order numbers, full address/payment/account/contact details, raw DOM, cookies, storage, request headers, and screenshots are not returned to Star. Complete visual proof remains owner-only to Joy.'
  };
})()
"""

CHECKOUT_SCREENSHOT_REDACTION_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const sensitiveLabel = /(ship\s+to|deliver\s+to|delivery\s+address|shipping\s+address|billing\s+address|payment\s+method|wallet|card|visa|mastercard|amex|american express|discover|gift\s+card|claim\s+code|promo(?:tion)?\s+code|order\s*(?:#|number|no\.?|id)|confirmation\s*(?:#|number|no\.?|id)|email|phone|security\s+code|captcha|verification|passcode|password|passkey|cvv|cvc)/i;
  const sensitiveValue = /([\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|\b(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9-]{6,}\b|\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\b(?:\d[ -]*?){12,19}\b)/i;
  const keepFinalPurchase = /(place\s+(your\s+)?order|submit\s+order|complete\s+purchase|buy\s+now)/i;
  document.querySelectorAll('[data-secure-browser-redaction="checkout-prep"]').forEach((node) => node.remove());
  const candidates = new Set();
  const addCandidate = (node) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.closest('[data-secure-browser-redaction="checkout-prep"]')) return;
    const text = clean(node.innerText || node.textContent || node.getAttribute('aria-label') || node.value || '');
    if (keepFinalPurchase.test(text)) return;
    candidates.add(node);
  };
  document.querySelectorAll('input, textarea, select, [autocomplete], [name], [id], [aria-label]').forEach((node) => {
    const attrs = clean([node.name, node.id, node.getAttribute('aria-label'), node.getAttribute('autocomplete'), node.placeholder, node.type].join(' '));
    if (sensitiveLabel.test(attrs)) addCandidate(node.closest('form, fieldset, .a-box, .a-section, li, tr, div') || node);
  });
  document.querySelectorAll('address, [data-testid*="address" i], [id*="address" i], [class*="address" i], [id*="payment" i], [class*="payment" i], [id*="wallet" i], [class*="wallet" i]').forEach((node) => addCandidate(node));
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const value = clean(node.nodeValue || '');
      if (!value || value.length < 4) return NodeFilter.FILTER_REJECT;
      if (sensitiveLabel.test(value) || sensitiveValue.test(value)) return NodeFilter.FILTER_ACCEPT;
      return NodeFilter.FILTER_REJECT;
    }
  });
  let textNode;
  while ((textNode = walker.nextNode())) {
    const parent = textNode.parentElement;
    if (!parent) continue;
    addCandidate(parent.closest('address, form, fieldset, .a-box, .a-section, li, tr, div') || parent);
  }
  const overlays = [];
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
  candidates.forEach((node) => {
    const rect = node.getBoundingClientRect();
    if (!rect || rect.width < 4 || rect.height < 4) return;
    if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= viewportHeight || rect.left >= viewportWidth) return;
    const overlay = document.createElement('div');
    overlay.setAttribute('data-secure-browser-redaction', 'checkout-prep');
    overlay.textContent = 'redacted';
    Object.assign(overlay.style, {
      position: 'fixed',
      left: `${Math.max(0, rect.left)}px`,
      top: `${Math.max(0, rect.top)}px`,
      width: `${Math.min(rect.width, viewportWidth - Math.max(0, rect.left))}px`,
      height: `${Math.min(rect.height, viewportHeight - Math.max(0, rect.top))}px`,
      zIndex: '2147483647',
      background: 'rgba(0, 0, 0, 0.88)',
      color: '#fff',
      font: 'bold 13px sans-serif',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      textTransform: 'uppercase',
      letterSpacing: '0.04em',
      pointerEvents: 'none',
      borderRadius: '3px',
      boxSizing: 'border-box',
      padding: '2px'
    });
    document.documentElement.appendChild(overlay);
    overlays.push({left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height)});
  });
  return {redaction_overlay_count: overlays.length, redaction_rects_sha256_material: JSON.stringify(overlays)};
})()
"""

CHECKOUT_SCREENSHOT_REDACTION_CLEANUP_JS = r"""
(() => {
  const nodes = Array.from(document.querySelectorAll('[data-secure-browser-redaction="checkout-prep"]'));
  nodes.forEach((node) => node.remove());
  return {removed: nodes.length};
})()
"""

VISUAL_REGIONS_JS = r"""
(() => {
  const maxRegions = __MAX_REGIONS__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const redact = (value) => clean(value)
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email redacted]')
    .replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, '[phone redacted]')
    .replace(/\b(?:\d[ -]*?){12,19}\b/g, '[payment number redacted]')
    .replace(/\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b/gi, '[street address redacted]')
    .replace(/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/g, '[state/zip redacted]');
  const selectorFor = (node) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return '';
    const id = node.id || '';
    if (id && !/(password|passkey|otp|verification|captcha|cvv|cvc|card|payment|address|phone|email)/i.test(id)) return `#${CSS.escape(id)}`;
    const dataAsin = node.getAttribute('data-asin');
    if (dataAsin && /^[A-Z0-9]{10}$/i.test(dataAsin)) return `[data-asin="${CSS.escape(dataAsin)}"]`;
    const role = node.getAttribute('role');
    const tag = node.tagName.toLowerCase();
    if (role) return `${tag}[role="${CSS.escape(role)}"]`;
    return tag;
  };
  const scoreFor = (category, rect, text) => {
    const area = Math.max(1, rect.width * rect.height);
    const categoryBoost = {
      checkout_totals_block: 1000,
      checkout_order_summary_block: 950,
      cart_item: 900,
      buy_box: 850,
      product_title: 800,
      price: 780,
      delivery_returns: 760,
      search_result: 740,
      review_excerpt: 720,
      post_purchase_confirmation: 990,
      post_purchase_delivery: 940,
      post_purchase_order_card: 920,
      final_purchase_control_blocked: 650,
    }[category] || 100;
    return categoryBoost + Math.min(area / 100, 400) + Math.min(text.length, 200);
  };
  const regions = [];
  const seen = new Set();
  const add = (category, node, label) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.closest('[data-secure-browser-redaction="checkout-prep"]')) return;
    const rect = node.getBoundingClientRect();
    if (!rect || rect.width < 8 || rect.height < 8) return;
    if (rect.bottom + window.scrollY < 0 || rect.right + window.scrollX < 0) return;
    const docLeft = rect.left + window.scrollX;
    const docTop = rect.top + window.scrollY;
    const key = `${category}:${Math.round(docLeft)}:${Math.round(docTop)}:${Math.round(rect.width)}:${Math.round(rect.height)}`;
    if (seen.has(key)) return;
    seen.add(key);
    const text = redact(node.innerText || node.textContent || node.getAttribute('aria-label') || node.value || '');
    const selector = selectorFor(node);
    regions.push({
      region_id: `r${regions.length + 1}`,
      category,
      label: label || category.replace(/_/g, ' '),
      selector,
      text_anchor: text.slice(0, 220),
      rect: {
        x: Math.max(0, Math.round(docLeft)),
        y: Math.max(0, Math.round(docTop)),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      },
      score: scoreFor(category, rect, text)
    });
  };

  const first = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node) return node;
    }
    return null;
  };

  add('product_title', first(['#productTitle', '#title h1', 'h1']), 'product title');
  add('buy_box', first(['#desktop_buybox', '#buybox', '#rightCol', '[data-feature-name="buybox"]']), 'buy box');
  add('price', first(['#corePriceDisplay_desktop_feature_div', '#corePrice_feature_div', '.a-price', '[class*="price" i]']), 'price');
  add('delivery_returns', first(['#mir-layout-DELIVERY_BLOCK', '#deliveryBlockMessage', '#returnsInfoFeature_feature_div', '[data-feature-name*="delivery" i]']), 'delivery and returns');
  add('checkout_totals_block', first(['#subtotals-marketplace-table', '#spc-order-summary', '[data-testid*="order-summary" i]', '[id*="orderSummary" i]', '[class*="order-summary" i]']), 'checkout totals block');
  add('checkout_order_summary_block', first(['#orderSummaryPrimaryActionBtn', '#submitOrderButtonId', '[name="placeYourOrder1"]', '[data-testid*="place-order" i]'])?.closest('form, .a-box, .a-section, div') || null, 'order review block');
  add('post_purchase_confirmation', first(['#thankYou', '#order-summary', '[data-testid*="confirmation" i]', '[id*="thank" i]', '[class*="thank" i]', 'h1']), 'post-purchase confirmation');
  add('post_purchase_delivery', first(['[id*="delivery" i]', '[class*="delivery" i]', '[data-testid*="delivery" i]', '[aria-label*="delivery" i]']), 'post-purchase delivery');

  Array.from(document.querySelectorAll('.order, [class*="order" i], [data-order-id], [data-testid*="order" i], .yohtmlc-order-card')).slice(0, 8).forEach((node, index) => add('post_purchase_order_card', node, `post-purchase order card ${index + 1}`));
  Array.from(document.querySelectorAll('.s-result-item[data-asin], [data-component-type="s-search-result"], [role="listitem"], article')).slice(0, 12).forEach((node, index) => add('search_result', node, `search result ${index + 1}`));
  Array.from(document.querySelectorAll('.sc-list-item, [data-name="Active Items"] [data-asin], [data-testid*="cart-item" i]')).slice(0, 12).forEach((node, index) => add('cart_item', node, `cart item ${index + 1}`));
  Array.from(document.querySelectorAll('[data-hook="review"], .review, [id*="customer_review"], blockquote')).slice(0, 8).forEach((node, index) => add('review_excerpt', node, `review excerpt ${index + 1}`));
  Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a')).filter((node) => /place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|confirm\s+(purchase|order)/i.test(clean(node.innerText || node.value || node.getAttribute('aria-label') || node.textContent || ''))).slice(0, 6).forEach((node, index) => add('final_purchase_control_blocked', node, `blocked final purchase control ${index + 1}`));

  regions.sort((a, b) => b.score - a.score);
  regions.slice(0, maxRegions).forEach((region, index) => { region.region_id = `r${index + 1}`; delete region.score; });
  return {
    page_title: document.title || '',
    url: location.href || '',
    document: {
      width: Math.ceil(Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0, window.innerWidth || 0)),
      height: Math.ceil(Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0, window.innerHeight || 0))
    },
    viewport: {
      x: Math.round(window.scrollX || 0),
      y: Math.round(window.scrollY || 0),
      width: Math.round(window.innerWidth || document.documentElement.clientWidth || 0),
      height: Math.round(window.innerHeight || document.documentElement.clientHeight || 0),
      device_scale_factor: window.devicePixelRatio || 1
    },
    regions: regions.slice(0, maxRegions),
    safety_note: 'Bounding boxes and text anchors are sanitized page-visible hints only. Cookies, storage, request headers, raw DOM/HTML, credentials, and CDP internals are not returned.'
  };
})()
"""

TYPE_JS = r"""
(() => {
  const selector = __SELECTOR__;
  const value = __VALUE__;
  const node = document.querySelector(selector);
  if (!node) return {typed: false, reason: 'selector did not match any element'};
  if (node.disabled || node.readOnly || node.getAttribute('aria-disabled') === 'true') return {typed: false, reason: 'matched field is disabled or read-only'};
  node.scrollIntoView({block: 'center', inline: 'center'});
  node.focus();
  node.value = value;
  node.dispatchEvent(new Event('input', {bubbles: true}));
  node.dispatchEvent(new Event('change', {bubbles: true}));
  return {typed: true, page_title: document.title || '', url: location.href || ''};
})()
"""


def _compact_large_result(data: dict[str, Any]) -> dict[str, Any]:
    compact = dict(data)
    if compact.get("operation") == "owner_checkout_review":
        compact = _compact_owner_checkout_review_result(compact)
    controls = compact.get("checkout_prep_controls")
    if isinstance(controls, list) and len(controls) > 12:
        metadata = dict(compact.get("blocked_metadata") or {})
        metadata["checkout_prep_controls_returned"] = 12
        metadata["checkout_prep_controls_truncated_from"] = len(controls)
        compact["blocked_metadata"] = metadata
        compact["checkout_prep_controls"] = controls[:12]
    return compact


def _bounded_checkout_scalar(value: Any, max_chars: int = 160, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _bounded_checkout_list(value: Any, limit: int, item_chars: int = 160) -> list[str]:
    items: list[str] = []
    if isinstance(value, list):
        source = value
    elif value:
        source = [value]
    else:
        source = []
    for item in source:
        text = _bounded_checkout_scalar(item, item_chars)
        if text:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _minimal_owner_checkout_facts(checkout_review: dict[str, Any]) -> dict[str, Any]:
    """Return only compact Star-visible order facts for owner-only review acks.

    The full checkout evidence is delivered directly to Joy as screenshots.  The
    model-visible acknowledgement must not carry verbose safe-control inventories,
    final-purchase button labels, raw paths, DOM, or owner-only visual content.
    """
    return {
        "items": _bounded_checkout_list(checkout_review.get("items"), 3),
        "totals": _bounded_checkout_list(checkout_review.get("totals"), 3),
        "delivery": _bounded_checkout_list(checkout_review.get("delivery"), 3),
        "shipping_destination_city_state_or_label": _bounded_checkout_list(checkout_review.get("shipping_destination_city_state_or_label"), 2),
        "payment_method_label_last_four_only": _bounded_checkout_list(checkout_review.get("payment_method_label_last_four_only"), 2),
        "purchase_mode": _bounded_checkout_scalar(checkout_review.get("purchase_mode"), 80, "not_detected") or "not_detected",
        "subscription_offer_visible": bool(checkout_review.get("subscription_offer_visible")),
        "subscription_selected": bool(checkout_review.get("subscription_selected")),
        "subscription_control_visible": bool(checkout_review.get("subscription_control_visible")),
        "one_time_selected": bool(checkout_review.get("one_time_selected")),
        "informational_flags": _bounded_checkout_list(checkout_review.get("informational_flags"), 3),
        "surprise_flags": _bounded_checkout_list(checkout_review.get("surprise_flags"), 3),
        "final_purchase_state": "blocked_pending_trusted_approval",
    }


def _minimal_post_purchase_facts(post_purchase: dict[str, Any]) -> dict[str, Any]:
    """Return compact Star-visible facts for post-purchase owner-only proof."""
    return {
        "post_purchase_state": _bounded_checkout_scalar(post_purchase.get("post_purchase_state"), 80, "post_purchase_context_visible") or "post_purchase_context_visible",
        "confirmation_visible": bool(post_purchase.get("confirmation_visible")),
        "orders_page_visible": bool(post_purchase.get("orders_page_visible")),
        "order_presence": _bounded_checkout_list(post_purchase.get("order_presence"), 4),
        "delivery_status": _bounded_checkout_list(post_purchase.get("delivery_status"), 4),
        "item_clues": _bounded_checkout_list(post_purchase.get("item_clues"), 3),
    }


def _compact_owner_checkout_review_result(data: dict[str, Any]) -> dict[str, Any]:
    post_purchase = data.get("post_purchase_review") or data.get("post_purchase")
    if isinstance(post_purchase, dict):
        deliveries = data.get("telegram_message_ids")
        delivery_count = len(deliveries) if isinstance(deliveries, list) else 0
        return {
            "operation": "owner_post_purchase_review",
            "status": _bounded_checkout_scalar(data.get("status"), 80, "sent_owner_only") or "sent_owner_only",
            "review_id": _bounded_checkout_scalar(data.get("review_id"), 80),
            "url": _bounded_checkout_scalar(data.get("url"), 500),
            "page_title": _bounded_checkout_scalar(data.get("page_title"), 200),
            "delivery": {
                "telegram": bool(delivery_count),
                "telegram_message_count": delivery_count,
                "status": "sent" if delivery_count else "not_delivered",
            },
            "post_purchase_summary_binding": _bounded_checkout_scalar(data.get("post_purchase_summary_binding") or post_purchase.get("post_purchase_summary_binding"), 128),
            "owner_visual_evidence_binding": _bounded_checkout_scalar(data.get("owner_visual_evidence_binding"), 128),
            "capture_mode": _bounded_checkout_scalar(data.get("capture_mode"), 80),
            "artifact_count": data.get("artifact_count"),
            "minimal_post_purchase_facts": _minimal_post_purchase_facts(post_purchase),
            "shopping_order_tracking": data.get("shopping_order_tracking"),
            "retention": _bounded_checkout_scalar(data.get("retention"), 200),
            "safety_boundary": "Complete post-purchase confirmation/order-verification screenshots were sent only to Joy via the trusted Telegram path. This acknowledgement omits raw screenshots, file paths, DOM, cookies, storage, request headers, order numbers, and full address/payment/account/contact details.",
        }
    checkout_review = data.get("checkout_review")
    if not isinstance(checkout_review, dict):
        checkout_review = {}
    deliveries = data.get("telegram_message_ids")
    delivery_count = len(deliveries) if isinstance(deliveries, list) else 0
    return {
        "operation": "owner_checkout_review",
        "status": _bounded_checkout_scalar(data.get("status"), 80, "sent_owner_only") or "sent_owner_only",
        "review_id": _bounded_checkout_scalar(data.get("review_id"), 80),
        "url": _bounded_checkout_scalar(data.get("url"), 500),
        "page_title": _bounded_checkout_scalar(data.get("page_title"), 200),
        "delivery": {
            "telegram": bool(delivery_count),
            "telegram_message_count": delivery_count,
            "status": "sent" if delivery_count else "not_delivered",
        },
        "material_summary_binding": _bounded_checkout_scalar(data.get("material_summary_binding") or checkout_review.get("material_summary_binding"), 128),
        "owner_visual_evidence_binding": _bounded_checkout_scalar(data.get("owner_visual_evidence_binding"), 128),
        "capture_mode": _bounded_checkout_scalar(data.get("capture_mode"), 80),
        "artifact_count": data.get("artifact_count"),
        "minimal_order_facts": _minimal_owner_checkout_facts(checkout_review),
        "retention": _bounded_checkout_scalar(data.get("retention"), 200),
        "safety_boundary": "Complete checkout screenshots were sent only to Joy via the trusted Telegram path. This acknowledgement omits raw screenshots, file paths, DOM, cookies, storage, request headers, full address/payment/account text, and final purchase controls; final purchase remains blocked pending trusted approval.",
    }


def _json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if len(payload) <= MAX_RESULT_CHARS:
        return payload
    compact = _compact_large_result(data)
    compact["result_truncated"] = True
    payload = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    if len(payload) <= MAX_RESULT_CHARS:
        return payload
    return json.dumps({
        "error": "RESULT_TOO_LARGE",
        "message": "Sanitized result exceeded the secure browser tool result budget after compaction.",
        "operation": data.get("operation"),
        "result_truncated": True,
    }, ensure_ascii=False, sort_keys=True)


def _audit(operation: str, details: dict[str, Any]) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "details": details,
    }
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Audit is defense-in-depth; tool calls should still report their action.
        pass



ORDER_STATUSES_ACTIVE = {"pending_confirmation", "confirmed", "ordered", "processing", "shipped", "out_for_delivery"}
ORDER_STATUSES_CLOSED = {"delivered", "cancelled", "closed", "archived"}
ORDER_STATUS_ALLOWED = ORDER_STATUSES_ACTIVE | ORDER_STATUSES_CLOSED
CONSUMABLE_CONFIDENCE_ALLOWED = {"explicit", "tentative", "suggested", "repeated_purchase"}
ORDER_REFRESH_SOURCE_PRIORITY = ["amazon_your_orders", "gmail_order_email", "carrier_page"]
ORDER_NOTIFY_EVENT_TYPES = {"initial_confirmation", "eta_changed", "status_changed", "out_for_delivery", "delivered"}
SAFE_ORDER_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,80}$", re.IGNORECASE)
UNSAFE_ORDER_HANDLE_RE = re.compile(r"\b\d{3}[- ]?\d{7}[- ]?\d{7}\b|\b(?:\d[ -]*?){12,19}\b")
SAFE_ORDER_STATUS_RANK = {
    "pending_confirmation": 10,
    "confirmed": 20,
    "ordered": 25,
    "processing": 30,
    "shipped": 40,
    "out_for_delivery": 50,
    "delivered": 60,
    "cancelled": 70,
    "closed": 80,
    "archived": 90,
}


def _order_ledger_path() -> str:
    return os.path.expanduser(SECURE_BROWSER_ORDER_LEDGER_PATH)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coarse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _sanitize_checkout_text(text)[:80]
    if re.search(r"\b\d{1,2}:\d{2}\b|\b\d{5}(?:-\d{4})?\b|\b\d{1,6}\s+[^,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b", text, re.IGNORECASE):
        return ""
    return text


def _coerce_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _coerce_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _safe_order_handle(value: Any, item_nickname: str = "order") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        material = f"{item_nickname}|{int(time.time())}"
        raw = f"order-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:10]}"
    raw = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-._")[:80]
    if not raw or not SAFE_ORDER_HANDLE_RE.fullmatch(raw) or UNSAFE_ORDER_HANDLE_RE.search(str(value or "")):
        raise ValueError("order handle must be a safe nickname/slug, not a raw order number, payment number, address, or blank value")
    return raw


def _safe_order_status(value: Any, default: str = "confirmed") -> str:
    status = str(value or default).strip().lower().replace(" ", "_").replace("-", "_")
    if status not in ORDER_STATUS_ALLOWED:
        raise ValueError(f"unsupported order status: {status}")
    return status


def _safe_retailer(value: Any) -> str:
    retailer = _sanitize_checkout_text(str(value or "amazon")).strip()[:80]
    return retailer or "amazon"


def _safe_item_nickname(value: Any) -> str:
    text = _sanitize_checkout_text(str(value or "order item")).strip()
    text = re.sub(r"\b(?:order|tracking)\s*(?:#|number|id)\s*[:#-]?\s*\S+", "", text, flags=re.IGNORECASE).strip()
    return text[:120] or "order item"


def _safe_item_category(value: Any) -> str:
    text = _sanitize_checkout_text(str(value or "")).strip()[:80]
    return text


def _safe_evidence_binding(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if re.fullmatch(r"[0-9a-f]{16,128}", text):
        return text[:128]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_order_payload(args: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    item_nickname = _safe_item_nickname(args.get("item_nickname") or existing.get("item_nickname") or args.get("nickname") or "order item")
    handle = _safe_order_handle(args.get("handle") or args.get("order_handle") or existing.get("handle"), item_nickname)
    payload = {
        "handle": handle,
        "retailer": _safe_retailer(args.get("retailer") or existing.get("retailer") or "amazon"),
        "item_nickname": item_nickname,
        "item_category": _safe_item_category(args.get("item_category") or existing.get("item_category") or ""),
        "status": _safe_order_status(args.get("status") or existing.get("status") or "confirmed"),
        "eta_window": _coarse_date(args.get("eta_window") or args.get("eta") or existing.get("eta_window") or ""),
        "safe_delivery_facts": _bounded_checkout_list(args.get("safe_delivery_facts") or args.get("delivery_status") or existing.get("safe_delivery_facts"), 6),
        "evidence_bindings": [],
        "source_refs": _bounded_checkout_list(args.get("source_refs") or existing.get("source_refs"), 8),
        "refresh_sources": _bounded_checkout_list(args.get("refresh_sources") or existing.get("refresh_sources") or ORDER_REFRESH_SOURCE_PRIORITY, 4),
        "notes": _sanitize_checkout_text(str(args.get("notes") or existing.get("notes") or ""))[:500],
    }
    bindings: list[str] = []
    for value in _coerce_json_list(existing.get("evidence_bindings")) + _coerce_json_list(args.get("evidence_bindings")):
        safe = _safe_evidence_binding(value)
        if safe and safe not in bindings:
            bindings.append(safe)
    for field in ("material_summary_binding", "post_purchase_summary_binding", "owner_visual_evidence_binding", "owner_review_id", "approval_request_id", "approval_id"):
        safe = _safe_evidence_binding(args.get(field) or existing.get(field))
        if safe and safe not in bindings:
            bindings.append(safe)
    payload["evidence_bindings"] = bindings[:12]
    return payload


def _ledger_connect() -> sqlite3.Connection:
    path = _order_ledger_path()
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_order_ledger(conn)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return conn


def _init_order_ledger(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shopping_orders (
            handle TEXT PRIMARY KEY,
            retailer TEXT NOT NULL,
            item_nickname TEXT NOT NULL,
            item_category TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            eta_window TEXT NOT NULL DEFAULT '',
            safe_delivery_facts_json TEXT NOT NULL DEFAULT '[]',
            evidence_bindings_json TEXT NOT NULL DEFAULT '[]',
            source_refs_json TEXT NOT NULL DEFAULT '[]',
            refresh_sources_json TEXT NOT NULL DEFAULT '[]',
            notification_state_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            delivered_at TEXT NOT NULL DEFAULT '',
            closed_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS consumable_items (
            handle TEXT PRIMARY KEY,
            item_nickname TEXT NOT NULL,
            item_category TEXT NOT NULL DEFAULT '',
            retailer TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'tentative',
            source TEXT NOT NULL DEFAULT '',
            evidence_count INTEGER NOT NULL DEFAULT 0,
            last_order_handle TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    # Simple migrations for older local ledgers if this schema grows.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(shopping_orders)")}
    if "notification_state_json" not in columns:
        conn.execute("ALTER TABLE shopping_orders ADD COLUMN notification_state_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()


def _order_row_to_safe_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "handle": row["handle"],
        "retailer": row["retailer"],
        "item_nickname": row["item_nickname"],
        "item_category": row["item_category"],
        "status": row["status"],
        "eta_window": row["eta_window"],
        "safe_delivery_facts": _coerce_json_list(row["safe_delivery_facts_json"]),
        "evidence_bindings": _coerce_json_list(row["evidence_bindings_json"]),
        "source_refs": _coerce_json_list(row["source_refs_json"]),
        "refresh_sources": _coerce_json_list(row["refresh_sources_json"]),
        "notification_state": _coerce_json_dict(row["notification_state_json"]),
        "notes": row["notes"],
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "delivered_at": row["delivered_at"],
        "closed_at": row["closed_at"],
    }


def _consumable_row_to_safe_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "handle": row["handle"],
        "item_nickname": row["item_nickname"],
        "item_category": row["item_category"],
        "retailer": row["retailer"],
        "confidence": row["confidence"],
        "source": row["source"],
        "evidence_count": row["evidence_count"],
        "last_order_handle": row["last_order_handle"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived": bool(row["archived"]),
    }


def _get_order(conn: sqlite3.Connection, handle: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM shopping_orders WHERE handle = ?", (handle,)).fetchone()
    return _order_row_to_safe_dict(row) if row else None


def _upsert_order_entry(args: dict[str, Any]) -> dict[str, Any]:
    with _ledger_connect() as conn:
        raw_handle = str(args.get("handle") or args.get("order_handle") or "").strip()
        existing = _get_order(conn, _safe_order_handle(raw_handle)) if raw_handle else None
        payload = _safe_order_payload(args, existing)
        now = _utc_now()
        created_at = (existing or {}).get("created_at") or now
        delivered_at = (existing or {}).get("delivered_at") or ""
        closed_at = (existing or {}).get("closed_at") or ""
        archived = bool((existing or {}).get("archived"))
        if payload["status"] == "delivered" and not delivered_at:
            delivered_at = now
        if payload["status"] in ORDER_STATUSES_CLOSED and not closed_at:
            closed_at = now
        if payload["status"] in ORDER_STATUSES_CLOSED:
            archived = bool(args.get("archive", payload["status"] in {"closed", "archived"}))
        notification_state = (existing or {}).get("notification_state") or {}
        conn.execute(
            """
            INSERT INTO shopping_orders(handle, retailer, item_nickname, item_category, status, eta_window, safe_delivery_facts_json, evidence_bindings_json, source_refs_json, refresh_sources_json, notification_state_json, notes, archived, created_at, updated_at, delivered_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET
              retailer=excluded.retailer,
              item_nickname=excluded.item_nickname,
              item_category=excluded.item_category,
              status=excluded.status,
              eta_window=excluded.eta_window,
              safe_delivery_facts_json=excluded.safe_delivery_facts_json,
              evidence_bindings_json=excluded.evidence_bindings_json,
              source_refs_json=excluded.source_refs_json,
              refresh_sources_json=excluded.refresh_sources_json,
              notification_state_json=excluded.notification_state_json,
              notes=excluded.notes,
              archived=excluded.archived,
              updated_at=excluded.updated_at,
              delivered_at=excluded.delivered_at,
              closed_at=excluded.closed_at
            """,
            (
                payload["handle"], payload["retailer"], payload["item_nickname"], payload["item_category"], payload["status"], payload["eta_window"],
                json.dumps(payload["safe_delivery_facts"], ensure_ascii=False), json.dumps(payload["evidence_bindings"], ensure_ascii=False), json.dumps(payload["source_refs"], ensure_ascii=False), json.dumps(payload["refresh_sources"], ensure_ascii=False), json.dumps(notification_state, ensure_ascii=False, sort_keys=True), payload["notes"], int(archived), created_at, now, delivered_at, closed_at,
            ),
        )
        conn.commit()
        order = _get_order(conn, payload["handle"])
    _audit("shopping_order_upserted", {"handle": payload["handle"], "status": payload["status"], "retailer": payload["retailer"]})
    return {
        "operation": "shopping_order_upsert",
        "status": "stored",
        "order": order,
        "privacy_boundary": "Ledger state is Star-visible safe state only: no raw order numbers, addresses, payment details, cookies, raw DOM, or owner-only screenshots are stored.",
    }


def _list_orders(include_archived: bool = False, status: str = "") -> dict[str, Any]:
    clauses = [] if include_archived else ["archived = 0"]
    params: list[Any] = []
    if status:
        status = _safe_order_status(status)
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _ledger_connect() as conn:
        rows = conn.execute(f"SELECT * FROM shopping_orders {where} ORDER BY updated_at DESC LIMIT 100", params).fetchall()
    orders = [_order_row_to_safe_dict(row) for row in rows]
    return {
        "operation": "shopping_order_list",
        "status": "ok",
        "orders": orders,
        "active_count": sum(1 for order in orders if order["status"] in ORDER_STATUSES_ACTIVE and not order["archived"]),
        "ledger_path_hint": "profile-local secure-browser-order ledger",
    }


def _read_order(handle: str) -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
    if not order:
        return {"operation": "shopping_order_read", "status": "not_found", "handle": safe_handle}
    return {"operation": "shopping_order_read", "status": "ok", "order": order}


def _close_order(handle: str, status: str = "delivered", archive: bool = True, safe_delivery_facts: Any = None, notes: str = "") -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        existing = _get_order(conn, safe_handle)
        if not existing:
            return {"operation": "shopping_order_close", "status": "not_found", "handle": safe_handle}
    args = {
        **existing,
        "handle": safe_handle,
        "status": _safe_order_status(status, "delivered"),
        "archive": archive,
        "safe_delivery_facts": safe_delivery_facts if safe_delivery_facts is not None else existing.get("safe_delivery_facts"),
        "notes": notes or existing.get("notes") or "",
    }
    result = _upsert_order_entry(args)
    result["operation"] = "shopping_order_close"
    return result


def _notification_decision(old: dict[str, Any] | None, new: dict[str, Any], event_hint: str = "") -> dict[str, Any]:
    event_hint = str(event_hint or "").strip().lower().replace(" ", "_").replace("-", "_")
    event_type = ""
    reasons: list[str] = []
    if old is None:
        event_type = "initial_confirmation"
        reasons.append("new safe order tracking entry")
    else:
        old_status = str(old.get("status") or "")
        new_status = str(new.get("status") or "")
        old_eta = str(old.get("eta_window") or "")
        new_eta = str(new.get("eta_window") or "")
        if old_eta != new_eta and new_eta:
            event_type = "eta_changed"
            reasons.append("ETA/window changed")
        if old_status != new_status:
            status_event = "delivered" if new_status == "delivered" else "out_for_delivery" if new_status == "out_for_delivery" else "status_changed"
            if not event_type or SAFE_ORDER_STATUS_RANK.get(new_status, 0) >= SAFE_ORDER_STATUS_RANK.get(old_status, 0):
                event_type = status_event
            reasons.append(f"status changed from {old_status or 'unknown'} to {new_status or 'unknown'}")
    if event_hint in ORDER_NOTIFY_EVENT_TYPES:
        event_type = event_hint
        reasons.append(f"explicit refresh event: {event_hint}")
    notification_state = _coerce_json_dict(new.get("notification_state"))
    last_key = f"last_notified_{event_type}"
    already_notified = bool(event_type and notification_state.get(last_key))
    should_notify = bool(event_type) and not already_notified
    return {
        "should_notify": should_notify,
        "event_type": event_type or "no_material_change",
        "reasons": reasons,
        "noise_policy": "Notify initial confirmation/ETA, material ETA or status changes, day-of/out-for-delivery/delivered; suppress repeated no-change or duplicate event updates.",
        "already_notified": already_notified,
    }


def _preview_order_update(args: dict[str, Any]) -> dict[str, Any]:
    handle = _safe_order_handle(args.get("handle") or args.get("order_handle") or "", args.get("item_nickname") or "order")
    with _ledger_connect() as conn:
        existing = _get_order(conn, handle)
    payload = _safe_order_payload({**(existing or {}), **args, "handle": handle}, existing)
    candidate = {**(existing or {}), **payload}
    decision = _notification_decision(existing, candidate, str(args.get("event_type") or ""))
    return {"operation": "shopping_order_notification_preview", "status": "ok", "handle": handle, "notification_decision": decision, "candidate_order": candidate}


def _mark_order_notified(handle: str, event_type: str) -> dict[str, Any]:
    event_type = str(event_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if event_type not in ORDER_NOTIFY_EVENT_TYPES:
        raise ValueError("event_type must be one of initial_confirmation, eta_changed, status_changed, out_for_delivery, delivered")
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
        if not order:
            return {"operation": "shopping_order_mark_notified", "status": "not_found", "handle": safe_handle}
        state = _coerce_json_dict(order.get("notification_state"))
        state[f"last_notified_{event_type}"] = _utc_now()
        conn.execute("UPDATE shopping_orders SET notification_state_json = ?, updated_at = ? WHERE handle = ?", (json.dumps(state, ensure_ascii=False, sort_keys=True), _utc_now(), safe_handle))
        conn.commit()
        order = _get_order(conn, safe_handle)
    return {"operation": "shopping_order_mark_notified", "status": "stored", "order": order}


def _refresh_plan() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    due_before = (now - timedelta(hours=6)).isoformat()
    with _ledger_connect() as conn:
        placeholders = ", ".join("?" for _ in ORDER_STATUSES_ACTIVE)
        rows = conn.execute(
            f"SELECT * FROM shopping_orders WHERE archived = 0 AND status IN ({placeholders}) ORDER BY updated_at ASC LIMIT 50",
            tuple(sorted(ORDER_STATUSES_ACTIVE)),
        ).fetchall()
    due = []
    for row in rows:
        order = _order_row_to_safe_dict(row)
        if order["updated_at"] <= due_before or order["status"] in {"shipped", "out_for_delivery"}:
            due.append({
                "handle": order["handle"],
                "item_nickname": order["item_nickname"],
                "status": order["status"],
                "eta_window": order["eta_window"],
                "refresh_sources": order["refresh_sources"] or ORDER_REFRESH_SOURCE_PRIORITY,
                "next_step": "Check Amazon Your Orders through the secure browser/post-purchase evidence path first; fall back to read-only Gmail order/shipment emails; try carrier pages only when bot-accessible and treat UPS/bot blocking as non-fatal.",
            })
    return {
        "operation": "shopping_order_refresh_plan",
        "status": "ok",
        "due_orders": due,
        "scheduled_refresh_spec": {
            "cadence": "every 6h while active, with extra day-of/out-for-delivery checks when source facts expose them",
            "primary_source": "Amazon Your Orders via secure browser owner/post-purchase evidence path",
            "fallback_source": "read-only Gmail order/shipment messages",
            "opportunistic_source": "carrier pages only when bot-accessible; UPS bot blocking is non-fatal",
            "notification_policy": "notify initial confirmation/ETA, material ETA/status changes, day-of/out-for-delivery/delivered; suppress no-change repeats",
        },
    }



def _extract_order_status_from_facts(facts: list[str], current_status: str = "") -> str:
    text = " ".join(str(fact or "") for fact in facts).lower()
    if re.search(r"\bdelivered\b", text):
        return "delivered"
    if re.search(r"\bout\s+for\s+delivery\b", text):
        return "out_for_delivery"
    if re.search(r"\b(shipped|on the way|in transit|track package)\b", text):
        return "shipped"
    if re.search(r"\b(arriving|arrives|expected|estimated|delivery)\b", text):
        return current_status if current_status in {"shipped", "out_for_delivery"} else "processing"
    return current_status or "confirmed"


def _extract_order_eta_from_facts(facts: list[str], current_eta: str = "") -> str:
    for fact in facts:
        text = _coarse_date(fact)
        if not text:
            continue
        match = re.search(r"\b(?:arriv(?:es|ing)|expected|estimated|delivery|delivered)\b[^.;,]{0,80}", text, re.IGNORECASE)
        if match:
            return _coarse_date(match.group(0)) or current_eta
    return current_eta


def _order_match_terms(order: dict[str, Any]) -> list[str]:
    candidates = [order.get("item_nickname"), order.get("item_category"), order.get("handle")]
    terms: list[str] = []
    for candidate in candidates:
        text = re.sub(r"[^a-z0-9 ]+", " ", str(candidate or "").lower())
        words = [word for word in text.split() if len(word) >= 4 and word not in {"order", "item", "amazon", "shopping"}]
        terms.extend(words[:4])
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped[:6]


def _facts_match_order(order: dict[str, Any], facts: list[str]) -> bool:
    terms = _order_match_terms(order)
    if not terms:
        return True
    haystack = " ".join(str(fact or "") for fact in facts).lower()
    return any(term in haystack for term in terms)


def _amazon_your_orders_observation(order: dict[str, Any]) -> dict[str, Any]:
    if str(order.get("retailer") or "").lower() not in {"amazon", "amazon.com", ""}:
        return {"source": "amazon_your_orders", "status": "skipped", "reason": "retailer is not amazon"}

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _claim_owner_target(browser, create=True)
        session_id = _attach(browser, target_id)
        _navigate_and_wait(browser, session_id, "https://www.amazon.com/gp/your-account/order-history")
        page_url = str(_evaluate(browser, session_id, "location.href") or "")
        page_title = str(_evaluate(browser, session_id, "document.title") or "")
        if not _is_amazon_post_purchase_page(page_url, page_title):
            return {"source": "amazon_your_orders", "status": "unavailable", "reason": "Amazon order-history page was not visible without owner intervention", "page_title": _sanitize_shopping_text(page_title)[:160], "url": _sanitize_url(page_url)}
        summary = _post_purchase_summary_from_browser(browser, session_id)
        facts = _bounded_checkout_list(summary.get("delivery_status"), 8) + _bounded_checkout_list(summary.get("order_presence"), 4) + _bounded_checkout_list(summary.get("item_clues"), 4)
        if not facts:
            return {"source": "amazon_your_orders", "status": "no_update", "reason": "no sanitized order facts visible", "post_purchase_summary_binding": summary.get("post_purchase_summary_binding")}
        if not _facts_match_order(order, facts):
            return {"source": "amazon_your_orders", "status": "no_match", "reason": "visible sanitized order facts did not match this safe order nickname", "post_purchase_summary_binding": summary.get("post_purchase_summary_binding")}
        return {
            "source": "amazon_your_orders",
            "status": "ok",
            "order_status": _extract_order_status_from_facts(facts, str(order.get("status") or "confirmed")),
            "eta_window": _extract_order_eta_from_facts(facts, str(order.get("eta_window") or "")),
            "safe_delivery_facts": facts[:6],
            "evidence_bindings": [summary.get("post_purchase_summary_binding")] if summary.get("post_purchase_summary_binding") else [],
            "source_refs": ["amazon_your_orders"],
        }

    try:
        return _with_browser(run)
    except Exception as exc:
        return {"source": "amazon_your_orders", "status": "unavailable", "reason": str(exc)[:300]}


def _gmail_order_email_observation(order: dict[str, Any]) -> dict[str, Any]:
    try:
        from tools.google_workspace_tool import google_workspace_gmail_search_tool  # type: ignore[import-not-found]
    except Exception as exc:
        return {"source": "gmail_order_email", "status": "unavailable", "reason": f"Google Workspace tool unavailable: {exc}"[:300]}
    terms = _order_match_terms(order)
    query_terms = " OR ".join(terms[:3]) if terms else str(order.get("item_nickname") or "")[:80]
    query = f'newer_than:90d (from:amazon OR subject:(shipped OR delivered OR order)) ({query_terms})'
    try:
        raw = google_workspace_gmail_search_tool({"query": query, "max_results": 5})
        result = json.loads(raw)
    except Exception as exc:
        return {"source": "gmail_order_email", "status": "unavailable", "reason": str(exc)[:300]}
    if result.get("error"):
        return {"source": "gmail_order_email", "status": "unavailable", "reason": _sanitize_checkout_text(str(result.get("message") or result.get("error")))[:300]}
    messages = result.get("messages") or result.get("results") or []
    snippets: list[str] = []
    if isinstance(messages, list):
        for message in messages[:5]:
            if isinstance(message, dict):
                # Keep only sanitized subject/snippet facts.  Sender addresses and raw Gmail
                # metadata are unnecessary for matching and should not leak into ledger facts.
                snippets.extend(_bounded_checkout_list([
                    _sanitize_checkout_text(str(message.get("snippet") or ""))[:200],
                    _sanitize_checkout_text(str(message.get("subject") or ""))[:200],
                ], 3))
            else:
                snippets.append(_sanitize_checkout_text(str(message))[:200])
    snippets = _bounded_checkout_list(snippets, 8)
    if not snippets:
        return {"source": "gmail_order_email", "status": "no_update", "reason": "no matching read-only Gmail order/shipment snippets"}
    if not _facts_match_order(order, snippets):
        return {"source": "gmail_order_email", "status": "no_match", "reason": "Gmail snippets did not match this safe order nickname"}
    return {
        "source": "gmail_order_email",
        "status": "ok",
        "order_status": _extract_order_status_from_facts(snippets, str(order.get("status") or "confirmed")),
        "eta_window": _extract_order_eta_from_facts(snippets, str(order.get("eta_window") or "")),
        "safe_delivery_facts": snippets[:6],
        "source_refs": ["gmail_order_email"],
    }


def _carrier_page_observation(order: dict[str, Any]) -> dict[str, Any]:
    safe_refs = []
    for ref in _coerce_json_list(order.get("source_refs")):
        text = str(ref or "")
        if text.startswith("https://") and not re.search(r"ups\.com|tracking|tracknum|track(?:ing)?[=/:-]|\b1z[0-9a-z]+\b", text, re.IGNORECASE):
            safe_refs.append(text)
    if not safe_refs:
        return {"source": "carrier_page", "status": "skipped", "reason": "no safe bot-accessible carrier URL hint without tracking identifiers"}
    return {"source": "carrier_page", "status": "skipped", "reason": "carrier pages are opportunistic only; no safe generic adapter is enabled yet"}


def _refresh_observation_for_source(order: dict[str, Any], source: str) -> dict[str, Any]:
    if source == "amazon_your_orders":
        return _amazon_your_orders_observation(order)
    if source == "gmail_order_email":
        return _gmail_order_email_observation(order)
    if source == "carrier_page":
        return _carrier_page_observation(order)
    return {"source": source, "status": "skipped", "reason": "unknown refresh source"}


def _notification_message(order: dict[str, Any], decision: dict[str, Any]) -> str:
    event_type = str(decision.get("event_type") or "status_changed").replace("_", " ")
    facts = _bounded_checkout_list(order.get("safe_delivery_facts"), 3)
    lines = [
        f"🛒 Star order update: {event_type}",
        f"Item: {_safe_item_nickname(order.get('item_nickname'))}",
        f"Status: {_safe_order_status(order.get('status'))}",
    ]
    if order.get("eta_window"):
        lines.append(f"ETA: {_coarse_date(order.get('eta_window'))}")
    if facts:
        lines.append("Facts: " + "; ".join(facts))
    return "\n".join(_sanitize_checkout_text(line)[:500] for line in lines if line)


def _send_order_notification(message: str) -> dict[str, Any]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip() or os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
    if not token or not chat_id:
        return {"status": "skipped", "reason": "Telegram bot token or home channel unavailable in profile environment"}
    payload = json.dumps({"chat_id": chat_id, "text": message, "disable_notification": False}).encode("utf-8")
    request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read(16384).decode("utf-8", "replace")
        parsed = json.loads(body)
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)[:300]}
    if not parsed.get("ok"):
        return {"status": "failed", "reason": _sanitize_checkout_text(str(parsed.get("description") or "Telegram send failed"))[:300]}
    result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
    return {"status": "sent", "telegram_message_id": result.get("message_id")}


def _apply_refresh_observation(order: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    candidate_args = {
        **order,
        "handle": order["handle"],
        "status": observation.get("order_status") or order.get("status"),
        "eta_window": observation.get("eta_window") or order.get("eta_window"),
        "safe_delivery_facts": observation.get("safe_delivery_facts") or order.get("safe_delivery_facts"),
        "evidence_bindings": _coerce_json_list(order.get("evidence_bindings")) + _coerce_json_list(observation.get("evidence_bindings")),
        "source_refs": _coerce_json_list(order.get("source_refs")) + _coerce_json_list(observation.get("source_refs")),
        "notes": order.get("notes") or "",
    }
    preview = _preview_order_update(candidate_args)
    stored = _upsert_order_entry(candidate_args)
    notification = {"status": "not_required"}
    decision = preview.get("notification_decision") if isinstance(preview.get("notification_decision"), dict) else {}
    if decision.get("should_notify"):
        notification = _send_order_notification(_notification_message(stored["order"], decision))
        if notification.get("status") == "sent":
            _mark_order_notified(stored["order"]["handle"], str(decision.get("event_type") or "status_changed"))
    return {"observation": observation, "preview": preview, "stored_order": stored.get("order"), "notification": notification}


def _refresh_due_orders(send_notifications: bool = True, limit: int = 20) -> dict[str, Any]:
    plan = _refresh_plan()
    due_orders = plan.get("due_orders") if isinstance(plan.get("due_orders"), list) else []
    refreshed = []
    for due in due_orders[:max(0, min(int(limit), 50))]:
        handle = str(due.get("handle") or "")
        with _ledger_connect() as conn:
            order = _get_order(conn, _safe_order_handle(handle))
        if not order:
            continue
        attempts = []
        applied = None
        for source in order.get("refresh_sources") or ORDER_REFRESH_SOURCE_PRIORITY:
            observation = _refresh_observation_for_source(order, str(source))
            attempts.append(observation)
            if observation.get("status") == "ok":
                if send_notifications:
                    applied = _apply_refresh_observation(order, observation)
                else:
                    candidate_args = {**order, "status": observation.get("order_status") or order.get("status"), "eta_window": observation.get("eta_window") or order.get("eta_window"), "safe_delivery_facts": observation.get("safe_delivery_facts") or order.get("safe_delivery_facts")}
                    applied = {"observation": observation, "preview": _preview_order_update(candidate_args), "notification": {"status": "dry_run"}}
                break
        refreshed.append({"handle": handle, "attempts": attempts, "applied": applied})
    sent_count = sum(1 for item in refreshed if ((item.get("applied") or {}).get("notification") or {}).get("status") == "sent")
    _audit("shopping_order_refresh_run", {"due_count": len(due_orders), "refreshed_count": len(refreshed), "sent_count": sent_count})
    return {
        "operation": "shopping_order_refresh_run",
        "status": "ok",
        "plan": plan,
        "refreshed": refreshed,
        "notifications_sent": sent_count,
        "privacy_boundary": "Scheduled refresh stores and notifies only sanitized order status/ETA facts; it never places, cancels, reorders, returns, edits accounts/payment/address, exposes raw order numbers, or returns raw browser/Gmail/carrier content.",
    }


def _upsert_consumable(args: dict[str, Any]) -> dict[str, Any]:
    nickname = _safe_item_nickname(args.get("item_nickname") or args.get("nickname") or "consumable item")
    handle = _safe_order_handle(args.get("handle") or re.sub(r"[^a-z0-9]+", "-", nickname.lower()).strip("-") or "consumable", nickname)
    confidence = str(args.get("confidence") or "tentative").strip().lower().replace(" ", "_").replace("-", "_")
    if confidence not in CONSUMABLE_CONFIDENCE_ALLOWED:
        raise ValueError("confidence must be explicit, tentative, suggested, or repeated_purchase")
    now = _utc_now()
    with _ledger_connect() as conn:
        existing = conn.execute("SELECT * FROM consumable_items WHERE handle = ?", (handle,)).fetchone()
        created_at = existing["created_at"] if existing else now
        evidence_count = int(args.get("evidence_count") or (existing["evidence_count"] if existing else 0) or 0)
        conn.execute(
            """
            INSERT INTO consumable_items(handle, item_nickname, item_category, retailer, confidence, source, evidence_count, last_order_handle, notes, created_at, updated_at, archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET item_nickname=excluded.item_nickname, item_category=excluded.item_category, retailer=excluded.retailer, confidence=excluded.confidence, source=excluded.source, evidence_count=excluded.evidence_count, last_order_handle=excluded.last_order_handle, notes=excluded.notes, updated_at=excluded.updated_at, archived=excluded.archived
            """,
            (
                handle,
                nickname,
                _safe_item_category(args.get("item_category") or (existing["item_category"] if existing else "")),
                _safe_retailer(args.get("retailer") or (existing["retailer"] if existing else "")),
                confidence,
                _sanitize_checkout_text(str(args.get("source") or (existing["source"] if existing else "")))[:120],
                evidence_count,
                _safe_order_handle(args.get("last_order_handle") or (existing["last_order_handle"] if existing else ""), "order") if (args.get("last_order_handle") or (existing["last_order_handle"] if existing else "")) else "",
                _sanitize_checkout_text(str(args.get("notes") or (existing["notes"] if existing else "")))[:500],
                created_at,
                now,
                int(bool(args.get("archived", existing["archived"] if existing else False))),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM consumable_items WHERE handle = ?", (handle,)).fetchone()
    return {
        "operation": "shopping_consumable_upsert",
        "status": "stored",
        "consumable": _consumable_row_to_safe_dict(row),
        "learning_policy": "Explicit Joy statements may be durable; repeated purchases can be suggested/tentative; ambiguous one-offs should remain tentative or ask before durable memory.",
    }


def _list_consumables(include_archived: bool = False) -> dict[str, Any]:
    where = "" if include_archived else "WHERE archived = 0"
    with _ledger_connect() as conn:
        rows = conn.execute(f"SELECT * FROM consumable_items {where} ORDER BY updated_at DESC LIMIT 100").fetchall()
    return {"operation": "shopping_consumable_list", "status": "ok", "consumables": [_consumable_row_to_safe_dict(row) for row in rows]}


def _suggest_consumable_from_order(handle: str) -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
    if not order:
        return {"operation": "shopping_consumable_suggest_from_order", "status": "not_found", "handle": safe_handle}
    suggestion = _upsert_consumable({
        "handle": re.sub(r"[^a-z0-9]+", "-", order["item_nickname"].lower()).strip("-") or f"consumable-{safe_handle}",
        "item_nickname": order["item_nickname"],
        "item_category": order["item_category"],
        "retailer": order["retailer"],
        "confidence": "suggested",
        "source": "post_purchase_order_suggestion",
        "evidence_count": 1,
        "last_order_handle": safe_handle,
        "notes": "Suggested from a purchase; keep tentative unless Joy explicitly confirms or repeated purchases provide stronger evidence.",
    })
    suggestion["operation"] = "shopping_consumable_suggest_from_order"
    return suggestion


def _order_entry_from_final_purchase_result(result: dict[str, Any], checkout_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    checkout_summary = checkout_summary or {}
    proof = result.get("post_purchase_proof") if isinstance(result.get("post_purchase_proof"), dict) else {}
    minimal = proof.get("post_purchase_review") if isinstance(proof.get("post_purchase_review"), dict) else {}
    minimal = minimal or proof.get("post_purchase") if isinstance(proof.get("post_purchase"), dict) else minimal
    facts = _minimal_post_purchase_facts(minimal) if isinstance(minimal, dict) else {}
    item_candidates = []
    item_candidates.extend(_bounded_checkout_list(checkout_summary.get("items"), 3))
    item_candidates.extend(_bounded_checkout_list(facts.get("item_clues"), 3))
    item_nickname = item_candidates[0] if item_candidates else "recent Amazon order"
    delivery_facts = _bounded_checkout_list(facts.get("delivery_status") or checkout_summary.get("delivery"), 6)
    eta = delivery_facts[0] if delivery_facts else ""
    material = {
        "request_id": result.get("request_id"),
        "approval_id": result.get("approval_id"),
        "material_summary_binding": result.get("material_summary_binding"),
        "owner_visual_evidence_binding": result.get("owner_visual_evidence_binding"),
        "final_url": result.get("final_url"),
        "item_nickname": item_nickname,
    }
    handle = "order-" + hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return _upsert_order_entry({
        "handle": handle,
        "retailer": "amazon",
        "item_nickname": item_nickname,
        "item_category": "secure browser order",
        "status": "confirmed" if proof else "pending_confirmation",
        "eta_window": eta,
        "safe_delivery_facts": delivery_facts,
        "material_summary_binding": result.get("material_summary_binding"),
        "owner_visual_evidence_binding": result.get("owner_visual_evidence_binding"),
        "approval_request_id": result.get("request_id"),
        "approval_id": result.get("approval_id"),
        "post_purchase_summary_binding": proof.get("post_purchase_summary_binding") if isinstance(proof, dict) else "",
        "owner_review_id": proof.get("review_id") if isinstance(proof, dict) else "",
        "source_refs": ["trusted_final_purchase_executor", "owner_post_purchase_proof" if proof else "post_purchase_proof_not_available"],
        "refresh_sources": ORDER_REFRESH_SOURCE_PRIORITY,
        "notes": "Created automatically by trusted final-purchase executor after a successful final purchase click.",
    })



def _order_entry_from_post_purchase_review_result(result: dict[str, Any]) -> dict[str, Any]:
    post_purchase = result.get("post_purchase_review") if isinstance(result.get("post_purchase_review"), dict) else {}
    post_purchase = post_purchase or (result.get("post_purchase") if isinstance(result.get("post_purchase"), dict) else {})
    facts = _minimal_post_purchase_facts(post_purchase) if post_purchase else {}
    item_candidates: list[str] = []
    item_candidates.extend(_bounded_checkout_list(facts.get("item_clues"), 3))
    item_candidates.extend(_bounded_checkout_list(facts.get("order_presence"), 3))
    item_nickname = item_candidates[0] if item_candidates else "recent Amazon order"
    delivery_facts = _bounded_checkout_list(facts.get("delivery_status"), 6)
    presence_facts = _bounded_checkout_list(facts.get("order_presence"), 4)
    status = _extract_order_status_from_facts(delivery_facts + presence_facts, "confirmed")
    eta = _extract_order_eta_from_facts(delivery_facts, "")
    material = {
        "post_purchase_summary_binding": result.get("post_purchase_summary_binding") or post_purchase.get("post_purchase_summary_binding"),
        "owner_visual_evidence_binding": result.get("owner_visual_evidence_binding"),
        "review_id": result.get("review_id"),
        "url": result.get("url"),
        "item_nickname": item_nickname,
    }
    handle = "order-" + hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return _upsert_order_entry({
        "handle": handle,
        "retailer": "amazon",
        "item_nickname": item_nickname,
        "item_category": "secure browser order",
        "status": status,
        "eta_window": eta,
        "safe_delivery_facts": delivery_facts or presence_facts,
        "post_purchase_summary_binding": result.get("post_purchase_summary_binding") or post_purchase.get("post_purchase_summary_binding"),
        "owner_visual_evidence_binding": result.get("owner_visual_evidence_binding"),
        "owner_review_id": result.get("review_id"),
        "source_refs": ["owner_post_purchase_review"],
        "refresh_sources": ORDER_REFRESH_SOURCE_PRIORITY,
        "archive": False,
        "notes": "Created automatically from owner-only post-purchase confirmation/order-verification review.",
    })



def _final_purchase_state_lock():
    os.makedirs(os.path.dirname(FINAL_PURCHASE_STATE_PATH) or ".", mode=0o700, exist_ok=True)
    handle = open(FINAL_PURCHASE_STATE_PATH, "a+", encoding="utf-8")
    os.chmod(FINAL_PURCHASE_STATE_PATH, 0o600)
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def _load_final_purchase_state(handle: Any) -> dict[str, Any]:
    handle.seek(0)
    raw = handle.read()
    if not raw.strip():
        return {"tokens": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"tokens": {}}
    if not isinstance(data, dict):
        return {"tokens": {}}
    if not isinstance(data.get("tokens"), dict):
        data["tokens"] = {}
    if not isinstance(data.get("approval_requests"), dict):
        data["approval_requests"] = {}
    return data


def _store_final_purchase_state(handle: Any, state: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def _approval_token_key(request_id: str, approval_id: str, material_summary_binding: str, owner_visual_evidence_binding: str) -> str:
    material = {
        "request_id": request_id,
        "approval_id": approval_id,
        "material_summary_binding": material_summary_binding,
        "owner_visual_evidence_binding": owner_visual_evidence_binding,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _approval_request_binding_key(material_summary_binding: str, owner_visual_evidence_binding: str, owner_review_id: str) -> str:
    material = {
        "material_summary_binding": material_summary_binding,
        "owner_visual_evidence_binding": owner_visual_evidence_binding,
        "owner_review_id": owner_review_id or "",
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _assert_hex_binding(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be a 64-character sha256 hex binding")
    return text


def _agent_request_board() -> str:
    raw = os.environ.get("AGENT_REQUEST_KANBAN_BOARD_OVERRIDE", "").strip() or os.environ.get("AGENT_REQUEST_KANBAN_BOARD", "").strip()
    return raw or "agent-requests"


def _request_id_from_submit_result(submit_result: dict[str, Any]) -> str:
    request_obj = submit_result.get("request")
    request = request_obj if isinstance(request_obj, dict) else {}
    return str(
        submit_result.get("request_id")
        or request.get("request_id")
        or request.get("id")
        or ""
    ).strip()


def _submit_final_purchase_approval_request(summary: dict[str, Any], material_summary_binding: str, owner_visual_evidence_binding: str, owner_review_id: str, note: str) -> dict[str, Any]:
    facts = _minimal_owner_checkout_facts(summary)
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    binding_key = _approval_request_binding_key(material_summary_binding, owner_visual_evidence_binding, owner_review_id)
    now = datetime.now(timezone.utc).isoformat()
    with _final_purchase_state_lock() as handle:
        state = _load_final_purchase_state(handle)
        approval_requests = state.setdefault("approval_requests", {})
        existing = approval_requests.get(binding_key) if isinstance(approval_requests.get(binding_key), dict) else None
        if existing and existing.get("status") in {"submitting", "approval_requested"}:
            request_id = str(existing.get("request_id") or "").strip()
            return {
                "status": "approval_request_already_exists" if request_id else "approval_request_submission_in_progress",
                "request_id": request_id,
                "binding_key": binding_key,
                "existing_request": existing,
                "minimal_order_facts": facts,
            }
        approval_requests[binding_key] = {
            "status": "submitting",
            "request_id": "",
            "material_summary_binding": material_summary_binding,
            "owner_visual_evidence_binding": owner_visual_evidence_binding,
            "owner_review_id": owner_review_id or "",
            "minimal_order_facts": facts,
            "started_at": now,
            "updated_at": now,
        }
        _store_final_purchase_state(handle, state)

    try:
        from tools.agent_request_tool import agent_request_submit_tool, agent_request_propose_tool
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime wiring
        with _final_purchase_state_lock() as handle:
            state = _load_final_purchase_state(handle)
            approval_requests = state.setdefault("approval_requests", {})
            approval_requests[binding_key] = {
                **approval_requests.get(binding_key, {}),
                "status": "submission_failed",
                "error": f"Agent Request tool bridge is unavailable: {exc}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _store_final_purchase_state(handle, state)
        raise RuntimeError(f"Agent Request tool bridge is unavailable: {exc}") from exc

    request_body = (
        "Trusted final-purchase execution request for the Star secure browser. "
        "Do not perform shopping research or checkout-prep. After Joy approves the bound proposal, "
        "execute exactly one final Place Order action through secure_browser_execute_final_purchase, "
        "and only if the live checkout material_summary_binding and owner_visual_evidence_binding still match."
    )
    context = "\n".join([
        f"material_summary_binding: {material_summary_binding}",
        f"owner_visual_evidence_binding: {owner_visual_evidence_binding}",
        f"owner_review_id: {owner_review_id or 'not supplied'}",
        f"url: {summary.get('url') or ''}",
        f"page_title: {summary.get('page_title') or ''}",
        f"minimal_order_facts_json: {facts_json}",
        f"star_note: {str(note or '').strip()[:1000]}",
    ])
    submit_payload = {
        "title": "🛒 Trusted final purchase approval for Star checkout",
        "request": request_body,
        "context": context,
        "subject": "Joy approval to place the current Amazon order",
        "target": "talon",
        "urgency": "urgent",
        "board": _agent_request_board(),
    }
    try:
        submit_result = json.loads(agent_request_submit_tool(submit_payload))
        if submit_result.get("error"):
            raise RuntimeError(str(submit_result.get("error")))
        request_id = _request_id_from_submit_result(submit_result)
        if not request_id:
            raise RuntimeError("Agent Request submission did not return a request_id or request.id")

        proposal_text = "\n".join([
            "Approve exactly one final Amazon Place Order action for the current Star secure-browser checkout.",
            f"Bound material_summary_binding: {material_summary_binding}",
            f"Bound owner_visual_evidence_binding: {owner_visual_evidence_binding}",
            f"Owner checkout review id: {owner_review_id or 'not supplied'}",
            f"Sanitized order facts: {facts_json}",
            "The executor must re-read the live checkout page immediately before clicking and refuse if any material field changed, if sensitive verification/login/account prompts appear, if final purchase controls are ambiguous/missing, or if this approval was already used.",
            "Approval does not grant ordinary Star final-click authority and does not authorize payment/address/account edits, subscriptions, add-ons, warranty/protection changes, login, passkeys, 2FA, CAPTCHA, or security prompts.",
        ])
        propose_result = json.loads(agent_request_propose_tool({
            "request_id": request_id,
            "summary": "approval-required: place current Amazon order exactly once if bound checkout summary still matches",
            "proposal": proposal_text,
            "subject": "Final Amazon Place Order for current Star checkout",
            "response_to_requester": "If approved, Talon will execute the bound final purchase exactly once after revalidating the live checkout summary.",
            "board": _agent_request_board(),
        }))
        if propose_result.get("error"):
            raise RuntimeError(str(propose_result.get("error")))
    except Exception as exc:
        with _final_purchase_state_lock() as handle:
            state = _load_final_purchase_state(handle)
            approval_requests = state.setdefault("approval_requests", {})
            approval_requests[binding_key] = {
                **approval_requests.get(binding_key, {}),
                "status": "submission_failed",
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _store_final_purchase_state(handle, state)
        raise

    completed_at = datetime.now(timezone.utc).isoformat()
    stored_request = {
        "status": "approval_requested",
        "request_id": request_id,
        "material_summary_binding": material_summary_binding,
        "owner_visual_evidence_binding": owner_visual_evidence_binding,
        "owner_review_id": owner_review_id or "",
        "minimal_order_facts": facts,
        "started_at": now,
        "updated_at": completed_at,
    }
    with _final_purchase_state_lock() as handle:
        state = _load_final_purchase_state(handle)
        approval_requests = state.setdefault("approval_requests", {})
        approval_requests[binding_key] = stored_request
        _store_final_purchase_state(handle, state)
    return {"status": "approval_requested", "submit_result": submit_result, "proposal_result": propose_result, "request_id": request_id, "binding_key": binding_key}


def _current_agent_request_approval(request_id: str) -> dict[str, Any]:
    try:
        from agent_request_broker import kanban_backend
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime wiring
        raise RuntimeError(f"Agent Request approval backend is unavailable: {exc}") from exc
    with kanban_backend.scoped_board(_agent_request_board()):
        conn = kanban_backend.connect()
        try:
            approval = kanban_backend.current_approval(conn, request_id)
            proposal = kanban_backend.latest_proposal(conn, request_id)
        finally:
            conn.close()
    if not proposal:
        raise ValueError("approval_request_id has no current final-purchase proposal")
    if not approval:
        raise ValueError("approval_request_id is not approved through the trusted Agent Request path")
    return approval


def _request_final_purchase_approval(material_summary_binding: str, owner_visual_evidence_binding: str, owner_review_id: str = "", note: str = "") -> dict[str, Any]:
    expected_binding = _assert_hex_binding(material_summary_binding, "material_summary_binding")
    evidence_binding = _assert_hex_binding(owner_visual_evidence_binding, "owner_visual_evidence_binding")

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        summary = _checkout_summary_from_browser(browser, session_id)
        if not _is_amazon_checkoutish_page(str(summary.get("url") or ""), str(summary.get("page_title") or "")):
            raise ValueError("final-purchase approval/execution is currently limited to Amazon checkout/order-review pages")
        live_binding = str(summary.get("material_summary_binding") or "")
        if live_binding != expected_binding:
            raise ValueError("live checkout material_summary_binding does not match the requested approval binding")
        if summary.get("human_takeover_required"):
            raise ValueError("checkout page requires Joy takeover before final-purchase approval can be requested")
        blocked_metadata = summary.get("blocked_metadata") if isinstance(summary.get("blocked_metadata"), dict) else {}
        if not blocked_metadata.get("final_purchase_controls_present"):
            raise ValueError("no final purchase control is visible on the bound checkout page")
        ar_result = _submit_final_purchase_approval_request(summary, expected_binding, evidence_binding, owner_review_id, note)
        result_status = str(ar_result.get("status") or "approval_requested")
        request_id = str(ar_result.get("request_id") or "")
        _audit("final_purchase_approval_requested", {"status": result_status, "request_id": request_id, "material_summary_binding": expected_binding, "owner_visual_evidence_binding": evidence_binding, "owner_review_id": owner_review_id})
        response = {
            "operation": "request_final_purchase_approval",
            "status": result_status,
            "request_id": request_id,
            "material_summary_binding": expected_binding,
            "owner_visual_evidence_binding": evidence_binding,
            "owner_review_id": owner_review_id,
            "minimal_order_facts": _minimal_owner_checkout_facts(summary),
            "safety_boundary": "Joy approval is requested through the trusted Agent Request Telegram action path. Final purchase remains blocked until that exact proposal is approved, then secure_browser_execute_final_purchase must revalidate the live material summary and consume the approval exactly once.",
        }
        if result_status == "approval_requested":
            response["agent_request"] = ar_result["proposal_result"].get("request") or ar_result["submit_result"].get("request")
        elif result_status == "approval_request_already_exists":
            response["duplicate_state"] = "A final-purchase approval request for this material_summary_binding, owner_visual_evidence_binding, and owner_review_id already exists; no new approval prompt was submitted."
        else:
            response["duplicate_state"] = "A final-purchase approval request for this binding is already being submitted; no new approval prompt was submitted. Retry only after confirming the existing attempt is stale or failed."
        return response

    return _with_browser(run)


def _execute_final_purchase(approval_request_id: str, material_summary_binding: str, owner_visual_evidence_binding: str) -> dict[str, Any]:
    request_id = str(approval_request_id or "").strip()
    if not request_id.startswith("ar-"):
        raise ValueError("approval_request_id must be an Agent Request id")
    expected_binding = _assert_hex_binding(material_summary_binding, "material_summary_binding")
    evidence_binding = _assert_hex_binding(owner_visual_evidence_binding, "owner_visual_evidence_binding")
    approval = _current_agent_request_approval(request_id)
    approval_id = str(approval.get("approval_id") or "")
    token_key = _approval_token_key(request_id, approval_id, expected_binding, evidence_binding)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        summary = _checkout_summary_from_browser(browser, session_id)
        if not _is_amazon_checkoutish_page(str(summary.get("url") or ""), str(summary.get("page_title") or "")):
            raise ValueError("final-purchase approval/execution is currently limited to Amazon checkout/order-review pages")
        live_binding = str(summary.get("material_summary_binding") or "")
        if live_binding != expected_binding:
            raise ValueError("live checkout material_summary_binding changed since approval; refusing final purchase")
        if summary.get("human_takeover_required"):
            raise ValueError("checkout page requires Joy takeover; refusing final purchase")
        blocked_metadata = summary.get("blocked_metadata") if isinstance(summary.get("blocked_metadata"), dict) else {}
        if not blocked_metadata.get("final_purchase_controls_present"):
            raise ValueError("no final purchase control is visible on the approved checkout page")
        with _final_purchase_state_lock() as handle:
            state = _load_final_purchase_state(handle)
            tokens = state.setdefault("tokens", {})
            if token_key in tokens:
                raise ValueError("this final-purchase approval token has already been consumed")
            tokens[token_key] = {
                "status": "executing",
                "request_id": request_id,
                "approval_id": approval_id,
                "material_summary_binding": expected_binding,
                "owner_visual_evidence_binding": evidence_binding,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            _store_final_purchase_state(handle, state)
        click_result = _evaluate(browser, session_id, FINAL_PURCHASE_CLICK_JS) or {}
        if not click_result.get("clicked"):
            raise RuntimeError(str(click_result.get("reason") or "final purchase control was not clicked"))
        time.sleep(2.0)
        raw_final_url = str(_evaluate(browser, session_id, "location.href") or "")
        raw_final_title = str(_evaluate(browser, session_id, "document.title") or "")
        final_url = _sanitize_url(raw_final_url)
        final_title = _sanitize_shopping_text(raw_final_title)
        post_purchase_proof: dict[str, Any] = {}
        if _is_amazon_post_purchase_page(raw_final_url, raw_final_title):
            try:
                post_purchase_proof = _owner_post_purchase_review_from_attached(browser, session_id, raw_final_url, raw_final_title, retain_local=False)
            except Exception as exc:
                post_purchase_proof = {
                    "status": "post_purchase_owner_proof_failed",
                    "message": str(exc)[:500],
                    "safety_boundary": "Final purchase click had already succeeded; post-purchase proof capture failed without exposing raw order, address, payment, browser, or screenshot data to Star.",
                }
        with _final_purchase_state_lock() as handle:
            state = _load_final_purchase_state(handle)
            tokens = state.setdefault("tokens", {})
            tokens[token_key] = {
                **tokens.get(token_key, {}),
                "status": "clicked",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "final_url": final_url,
                "final_title": final_title,
                "post_purchase_proof_status": post_purchase_proof.get("status") if post_purchase_proof else "not_attempted",
            }
            _store_final_purchase_state(handle, state)
        _audit("final_purchase_executed", {"request_id": request_id, "approval_id": approval_id, "material_summary_binding": expected_binding, "owner_visual_evidence_binding": evidence_binding, "final_url": final_url, "final_title": final_title})
        result = {
            "operation": "execute_final_purchase",
            "status": "clicked",
            "request_id": request_id,
            "approval_id": approval_id,
            "material_summary_binding": expected_binding,
            "owner_visual_evidence_binding": evidence_binding,
            "final_url": final_url,
            "final_page_title": final_title,
            "control_label": _sanitize_checkout_text(str(click_result.get("control_label") or ""))[:120],
            "post_purchase_proof": post_purchase_proof or {"status": "not_attempted", "reason": "landing page was not recognized as an Amazon post-purchase confirmation/orders page"},
            "exactly_once_token": token_key,
            "safety_boundary": "Final purchase was executed only after a trusted Agent Request approval, live material-summary revalidation, and exactly-once token consumption. Post-purchase proof is owner-only when captured. The result does not expose cookies, storage, raw DOM, order references, full payment/address details, screenshots, or CDP handles.",
        }
        try:
            result["shopping_order_tracking"] = _order_entry_from_final_purchase_result(result, summary)
        except Exception as exc:
            result["shopping_order_tracking"] = {
                "status": "ledger_entry_failed",
                "message": str(exc)[:500],
                "safety_boundary": "The final purchase click already succeeded; order-ledger ingestion failed without exposing raw order/address/payment/browser evidence to Star.",
            }
        return result

    return _with_browser(run)

def _safe_browser_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("secure browser navigation only accepts http(s) URLs")
    if parsed.scheme != "https" and not parsed.hostname in ("localhost", "127.0.0.1"):
        raise ValueError("secure browser navigation requires https except localhost")
    if FINAL_PURCHASE_RE.search(candidate) or re.search(r"\bcheckout\b|/checkout|/buy/|/gp/buy(?:/|$)", candidate, re.IGNORECASE):
        raise ValueError("URL appears to target checkout, Buy Now, Place Order, or other final-purchase scope")
    if HUMAN_TAKEOVER_URL_RE.search(candidate):
        raise ValueError("URL appears to target login, credential challenge, payment, address, wallet, or security scope that requires Joy takeover")
    return candidate


def _selector_arg(value: Any) -> str:
    selector = str(value or "").strip()
    if not selector:
        raise ValueError("selector is required")
    if len(selector) > 500:
        raise ValueError("selector is too long")
    return selector


def _bounded_text(value: Any, field: str = "text") -> str:
    text = str(value or "")
    if len(text) > MAX_TYPE_CHARS:
        raise ValueError(f"{field} exceeds {MAX_TYPE_CHARS} characters")
    return text


def _safe_read_only_query(value: Any) -> str:
    expression = str(value or "").strip()
    if not expression:
        raise ValueError("expression is required")
    if len(expression) > 2000:
        raise ValueError("expression is too long")
    if MUTATING_QUERY_RE.search(expression):
        raise ValueError("expression contains mutating, network, storage, cookie, or navigation tokens")
    return expression


def _is_amazon_checkoutish_page(url: str, title: str = "") -> bool:
    parsed = urlparse(str(url or ""))
    page_material = " ".join([parsed.path, parsed.query, str(title or "")])
    if POST_PURCHASE_CONFIRMATION_RE.search(page_material) or AMAZON_ORDERS_RE.search(page_material):
        return False
    return bool(parsed.scheme == "https" and AMAZON_HOST_RE.search(parsed.netloc) and CHECKOUT_QUERY_PAGE_RE.search(page_material))


def _is_amazon_post_purchase_page(url: str, title: str = "") -> bool:
    parsed = urlparse(str(url or ""))
    page_material = " ".join([parsed.path, parsed.query, str(title or "")])
    return bool(
        parsed.scheme == "https"
        and AMAZON_HOST_RE.search(parsed.netloc)
        and (POST_PURCHASE_CONFIRMATION_RE.search(page_material) or AMAZON_ORDERS_RE.search(page_material))
    )


def _is_checkoutish_page(url: str, title: str = "") -> bool:
    parsed = urlparse(str(url or ""))
    page_material = " ".join([parsed.path, parsed.query, str(title or "")])
    return bool(CHECKOUT_QUERY_PAGE_RE.search(page_material))


def _checkout_control_filter_from_expression(expression: str) -> str:
    text = str(expression or "").lower()
    if re.search(r"payment|paying|gift\s*card|claim\s*code|promo|coupon|visa|mastercard|amex|american express|discover", text):
        return "payment_gift_card"
    if re.search(r"shipping|delivery|arrives|ship", text):
        return "shipping_delivery"
    if re.search(r"subscribe|subscription|one[-\s]?time|purchase\s+mode", text):
        return "purchase_mode"
    if re.search(r"quantity|qty|delete|remove|cart|line\s*item", text):
        return "cart_line_item"
    return ""


def _filter_checkout_controls_for_query(checkout_review: dict[str, Any], expression: str) -> str:
    requested_region = _checkout_control_filter_from_expression(expression)
    controls = checkout_review.get("checkout_prep_controls")
    if not requested_region or not isinstance(controls, list):
        return ""
    filtered = [control for control in controls if isinstance(control, dict) and str(control.get("region") or "") == requested_region]
    checkout_review["checkout_prep_controls_filter"] = {
        "requested_region": requested_region,
        "full_safe_control_count": len(controls),
        "filtered_safe_control_count": len(filtered),
        "note": "The checkout control list was compacted because the read-only query asked for a specific checkout-control category.",
    }
    checkout_review["checkout_prep_controls"] = filtered
    blocked_metadata = checkout_review.get("blocked_metadata")
    if isinstance(blocked_metadata, dict):
        blocked_metadata["checkout_prep_safe_control_count_before_filter"] = len(controls)
        blocked_metadata["checkout_prep_safe_control_filter"] = requested_region
        blocked_metadata["checkout_prep_safe_control_count"] = len(filtered)
    return requested_region


def _checkout_control_region_counts(controls: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for control in controls if isinstance(controls, list) else []:
        if not isinstance(control, dict):
            continue
        region = str(control.get("region") or "checkout_review")
        counts[region] = counts.get(region, 0) + 1
    return counts


def _checkout_query_summary_response(checkout_review: dict[str, Any], expression: str, url: str = "", title: str = "") -> dict[str, Any]:
    result = dict(checkout_review)
    _filter_checkout_controls_for_query(result, expression)
    result["operation"] = "checkout_query_summary"
    result["status"] = "ok"
    result["requested_expression_sha256"] = hashlib.sha256(str(expression or "").encode("utf-8")).hexdigest()
    result["checkout_prep_control_categories"] = {
        "regions": _checkout_control_region_counts(checkout_review.get("checkout_prep_controls")),
        "query_filter_terms": {
            "payment_gift_card": "payment, paying, gift card, claim code, promo, coupon, or visible card brand such as Visa",
            "shipping_delivery": "shipping, delivery, arrives, or ship",
            "purchase_mode": "subscribe, subscription, one-time, or purchase mode",
            "cart_line_item": "quantity, qty, delete, remove, cart, or line item",
        },
    }
    result["query_boundary"] = (
        "Generic secure_browser_query is restricted on checkout/order-review pages. "
        "The requested JavaScript was not returned directly; this result contains only the sanitized checkout-prep summary and non-secret controls. "
        "Ask for a specific checkout-control category such as payment/gift-card controls to receive a compact filtered control list."
    )
    if url and not result.get("url"):
        result["url"] = _sanitize_url(url)
    if title and not result.get("page_title"):
        result["page_title"] = _sanitize_checkout_text(title)
    return result


def _json_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


_STATE_CODES_RE = r"(?:A[LKZR]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AIT]|W[AIVY])"
_CITY_STATE_RE = re.compile(rf"\b([A-Z][A-Za-z .'-]{{1,40}}),?\s+({_STATE_CODES_RE})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_ZIP_RE = re.compile(rf"\b({_STATE_CODES_RE})\s+\d{{5}}(?:-\d{{4}})?\b")
_STREET_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9#.'&/-]+\s+){0,8}"
    r"(?:street|st\.?|avenue|ave\.?|road|rd\.?|drive|dr\.?|lane|ln\.?|court|ct\.?|circle|cir\.?|boulevard|blvd\.?|way|place|pl\.?|terrace|ter\.?|trail|trl\.?|parkway|pkwy\.?|highway|hwy\.?)"
    r"\b(?:\s+(?:apt|apartment|unit|suite|ste\.?|#)\s*[A-Za-z0-9-]+)?",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(r"\b(?:apt|apartment|unit|suite|ste\.?)\s*[A-Za-z0-9-]+\b", re.IGNORECASE)
_STANDALONE_ZIP_RE = re.compile(r"(?<![#A-Za-z0-9])\d{5}(?:-\d{4})?\b")
_LONG_PAYMENT_NUMBER_RE = re.compile(r"\b(?:\d[ -]?){5,}\d\b")
_FULL_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_PAYMENT_BRAND_RE = re.compile(r"\b(visa|mastercard|amex|american express|discover|gift card)\b", re.IGNORECASE)
_LAST_FOUR_RE = re.compile(r"(?:ending\s+in|last\s+four|\*{2,}|•{2,}|x{2,})\s*(\d{4})\b", re.IGNORECASE)
_SHIPPING_DESTINATION_CUE_RE = re.compile(r"\b(ship\s+to|deliver\s+to|delivery\s+address|shipping\s+address|billing\s+to)\b", re.IGNORECASE)
_CHECKOUT_ADMIN_FRAGMENT_RE = re.compile(
    r"\b(promo(?:tion)?\s+code|claim\s+code|gift\s+card|change|return\s+policy|terms|conditions|privacy|place\s+(?:your\s+)?order|"
    r"payment\s+method|wallet|shipping\s+address|delivery\s+address|ship\s+to|deliver\s+to|subtotal|estimated\s+tax|order\s+total)\b",
    re.IGNORECASE,
)


def _sanitize_checkout_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = _EMAIL_RE.sub("[email redacted]", text)
    text = _PHONE_RE.sub("[phone redacted]", text)
    text = _FULL_CARD_RE.sub("[payment number redacted]", text)
    text = re.sub(r"\b(?:cvv|cvc|security code)\s*[:#-]?\s*\d+\b", "[payment security code redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:account|card|routing)\s*(?:number|no\.?|#)?\s*[:#-]?\s*(?:\d[ -]?){5,}\d\b", "[account number redacted]", text, flags=re.IGNORECASE)
    text = _STREET_ADDRESS_RE.sub("[street address redacted]", text)
    text = _UNIT_RE.sub("[address unit redacted]", text)
    text = _ZIP_RE.sub(r"\1 [zip redacted]", text)
    text = _STANDALONE_ZIP_RE.sub("[zip redacted]", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _sanitize_checkout_destination_text(value: str) -> str:
    text = _sanitize_checkout_text(value)
    match = _CITY_STATE_RE.search(text)
    if match:
        return f"{match.group(1).strip()}, {match.group(2).upper()}"
    if not text:
        return ""
    return "[shipping destination redacted]"


def _checkout_text_has_sensitive_marker(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(
        marker in lowered
        for marker in (
            "street address redacted",
            "address unit redacted",
            "zip redacted",
            "phone redacted",
            "email redacted",
            "payment number redacted",
            "account number redacted",
            "payment security code redacted",
        )
    )


def _checkout_text_has_mixed_summary(value: str) -> bool:
    text = str(value or "")
    categories = 0
    for pattern in (
        r"\b(ship\s+to|deliver\s+to|delivery\s+address|shipping\s+address)\b",
        r"\b(payment\s+method|wallet|card|visa|mastercard|amex|american express|discover|gift\s+card)\b",
        r"\b(subtotal|shipping|estimated\s+tax|order\s+total|total)\b",
        r"\b(delivery|arrives|shipping\s+speed|delivery\s+(option|date|window))\b",
        r"\b(qty|quantity|sold\s+by|seller)\b",
    ):
        if re.search(pattern, text, re.IGNORECASE):
            categories += 1
    return categories > 1


def _sanitize_checkout_payment_text(value: str) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    explicit_last_four = _LAST_FOUR_RE.search(raw)
    full_card = _FULL_CARD_RE.search(raw)
    text = _sanitize_checkout_text(raw)
    brand = _PAYMENT_BRAND_RE.search(text) or _PAYMENT_BRAND_RE.search(raw)
    label = brand.group(1).title() if brand else "Payment method"
    if explicit_last_four:
        return f"{label} ending in {explicit_last_four.group(1)}"
    if full_card:
        digits = re.sub(r"\D", "", full_card.group(0))
        return f"{label} ending in {digits[-4:]}"
    if _LONG_PAYMENT_NUMBER_RE.search(text) or any(token in text.lower() for token in ("account", "card", "wallet", "payment")):
        return f"{label} [details redacted]"
    return text


def _dedupe_checkout_values(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _as_checkout_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        result: list[Any] = []
        for item in value.values():
            result.extend(_as_checkout_list(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_as_checkout_list(item))
        return result
    return [value]


def _checkout_text_is_wrong_detail_bucket(value: str, field: str) -> bool:
    field = str(field or "").lower()
    text = str(value or "")
    if field in ("items", "delivery") and _CHECKOUT_ADMIN_FRAGMENT_RE.search(text):
        return True
    if field == "items" and not re.search(r"\b(qty|quantity|sold\s+by|seller)\b|\$\d", text, re.IGNORECASE):
        return True
    if field == "delivery" and re.search(
        r"\b(payment\s+method|wallet|card|visa|mastercard|amex|american express|discover|subtotal|estimated\s+tax|order\s+total|qty|quantity|sold\s+by|seller)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def _sanitize_checkout_detail_text(value: Any, field: str = "") -> str:
    text = _sanitize_checkout_text(str(value or ""))
    if not text:
        return ""
    if FINAL_PURCHASE_RE.search(text):
        return ""
    if _checkout_text_is_wrong_detail_bucket(text, field):
        return ""
    if _checkout_text_has_sensitive_marker(text) or _checkout_text_has_mixed_summary(text):
        return "[checkout detail redacted]"
    if len(text) > 220:
        return text[:217].rstrip() + "…"
    return text


def _sanitize_checkout_detail_list(value: Any, limit: int = 12, field: str = "") -> list[str]:
    return _dedupe_checkout_values([_sanitize_checkout_detail_text(item, field=field) for item in _as_checkout_list(value)])[:limit]


def _sanitize_checkout_destination_list(value: Any) -> list[str]:
    destinations: list[str] = []
    for item in _as_checkout_list(value):
        raw = str(item or "")
        text = _sanitize_checkout_destination_text(raw)
        if not text:
            continue
        if text != "[shipping destination redacted]" or _SHIPPING_DESTINATION_CUE_RE.search(raw) or _STREET_ADDRESS_RE.search(raw):
            destinations.append(text)
    deduped = _dedupe_checkout_values(destinations)
    specific = [item for item in deduped if item != "[shipping destination redacted]"]
    return (specific or deduped)[:4]


def _sanitize_checkout_payment_list(value: Any) -> list[str]:
    return _dedupe_checkout_values([_sanitize_checkout_payment_text(item) for item in _as_checkout_list(value)])[:4]


def _sanitize_final_purchase_controls(value: Any) -> list[str]:
    controls: list[str] = []
    for item in _as_checkout_list(value):
        text = _sanitize_checkout_text(str(item or ""))
        if FINAL_PURCHASE_RE.search(text):
            controls.append(text[:120])
    return _dedupe_checkout_values(controls)[:8]


def _sanitize_checkout_control_label(value: Any) -> str:
    text = _sanitize_checkout_text(str(value or ""))
    if not text:
        return ""
    if FINAL_PURCHASE_RE.search(text):
        return ""
    if _checkout_text_has_sensitive_marker(text) or _checkout_text_has_mixed_summary(text):
        return "[checkout control label redacted]"
    if len(text) > 180:
        return text[:177].rstrip() + "…"
    return text


def _sanitize_checkout_controls(value: Any) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_regions = {"purchase_mode", "shipping_delivery", "gift_options", "cart_line_item", "payment_gift_card", "coupon_gift_card", "navigation_review", "checkout_review"}
    allowed_effects = set(CHECKOUT_APPROVED_EFFECTS)
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        selector = str(item.get("selector") or "").strip()
        if not selector or len(selector) > 500 or selector in seen:
            continue
        label = _sanitize_checkout_control_label(item.get("label"))
        if not label:
            continue
        raw_hints = item.get("approved_effect_hints") if isinstance(item.get("approved_effect_hints"), list) else []
        hints = [str(hint) for hint in raw_hints if str(hint) in allowed_effects]
        if not hints:
            hints = ["apply_checkout_option"]
        region = str(item.get("region") or "checkout_review")
        if region not in allowed_regions:
            region = "checkout_review"
        rect = item.get("viewport_rect") if isinstance(item.get("viewport_rect"), dict) else {}
        clean_rect = {
            key: int(rect.get(key) or 0)
            for key in ("x", "y", "width", "height")
        }
        controls.append({
            "selector": selector,
            "label": label,
            "role": _sanitize_checkout_text(str(item.get("role") or ""))[:40],
            "tag": _sanitize_checkout_text(str(item.get("tag") or ""))[:20],
            "input_type": _sanitize_checkout_text(str(item.get("input_type") or ""))[:30],
            "region": region,
            "approved_effect_hints": hints,
            "checked": bool(item.get("checked")),
            "selected": bool(item.get("selected")),
            "state": str(item.get("state") or "")[:40],
            "disabled": bool(item.get("disabled")),
            "viewport_rect": clean_rect,
        })
        seen.add(selector)
        if len(controls) >= MAX_LINKS:
            break
    return controls


def _sanitize_checkout_value(value: Any, field_name: str = "") -> Any:
    field = str(field_name or "").lower()
    if isinstance(value, dict):
        return {key: _sanitize_checkout_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_checkout_value(item, field_name) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_checkout_value(item, field_name) for item in value]
    if isinstance(value, str):
        if "shipping_destination" in field or "destination" in field or "address" in field:
            return _sanitize_checkout_destination_text(value)
        if "payment" in field or "card" in field or "last_four" in field:
            return _sanitize_checkout_payment_text(value)
        if "email" in field or "phone" in field or "account" in field:
            return "[sensitive contact/account detail redacted]" if value.strip() else ""
        return _sanitize_checkout_text(value)
    return value


def _sanitize_checkout_summary(summary: dict[str, Any], safety: dict[str, Any], controls: dict[str, Any] | None = None) -> dict[str, Any]:
    controls = controls or {}
    checkout_prep_controls = _sanitize_checkout_controls(controls.get("safe_controls") or [])
    final_purchase_controls = _sanitize_final_purchase_controls(controls.get("final_purchase_controls_visible") or safety.get("final_purchase_controls_visible") or summary.get("final_purchase_controls_visible") or [])
    shipping_destination = _sanitize_checkout_destination_list(summary.get("shipping_destination_label_or_city_state"))
    if not shipping_destination:
        fallback_destination_candidates = []
        for item in _as_checkout_list([summary.get("delivery"), summary.get("items"), summary.get("payment_method_label_last_four_only")]):
            if _SHIPPING_DESTINATION_CUE_RE.search(str(item or "")) or _STREET_ADDRESS_RE.search(str(item or "")):
                fallback_destination_candidates.append(item)
        shipping_destination = _sanitize_checkout_destination_list(fallback_destination_candidates)
    blocked_metadata: dict[str, Any] = {
        "final_purchase_controls_present": bool(final_purchase_controls),
        "final_purchase_control_count": len(final_purchase_controls),
        "final_purchase_controls_visible": final_purchase_controls,
        "checkout_prep_safe_control_count": len(checkout_prep_controls),
        "sensitive_controls_suppressed_count": int(controls.get("sensitive_controls_suppressed_count") or 0),
        "final_purchase_policy": "Final Buy Now, Place Order, or equivalent order-submission controls are blocked and must not be clicked through ordinary secure_browser tools.",
    }
    if safety.get("blocked_reason"):
        blocked_metadata["human_takeover_reason"] = _sanitize_checkout_text(str(safety.get("blocked_reason") or ""))

    sanitized: dict[str, Any] = {
        "operation": "checkout_review_summary",
        "page_title": _sanitize_checkout_text(str(summary.get("page_title") or safety.get("page_title") or "")),
        "url": _sanitize_url(str(summary.get("url") or safety.get("url") or "")),
        "checkout_prep_state": str(safety.get("checkout_prep_state") or "checkout_prep_visible"),
        "human_takeover_required": bool(safety.get("blocked_reason")),
        "items": _sanitize_checkout_detail_list(summary.get("items"), limit=10, field="items"),
        "totals": _sanitize_checkout_detail_list(summary.get("totals"), limit=8, field="totals"),
        "delivery": _sanitize_checkout_detail_list(summary.get("delivery"), limit=6, field="delivery"),
        "shipping_destination_city_state_or_label": shipping_destination,
        "payment_method_label_last_four_only": _sanitize_checkout_payment_list(summary.get("payment_method_label_last_four_only")),
        "purchase_mode": str(summary.get("purchase_mode") or "not_detected"),
        "subscription_offer_visible": bool(summary.get("subscription_offer_visible")),
        "subscription_selected": bool(summary.get("subscription_selected")),
        "subscription_control_visible": bool(summary.get("subscription_control_visible")),
        "one_time_selected": bool(summary.get("one_time_selected")),
        "purchase_mode_controls": _sanitize_checkout_value(summary.get("purchase_mode_controls") or [], "purchase_mode_controls"),
        "informational_flags": _sanitize_checkout_detail_list(summary.get("informational_flags"), limit=6),
        "surprise_flags": _sanitize_checkout_detail_list(summary.get("surprise_flags"), limit=10),
        "checkout_prep_controls": checkout_prep_controls,
        "checkout_prep_control_policy": "Star may inspect and use sanitized selectors/labels for ordinary checkout-prep controls only with an explicit approved_effect. Final purchase controls and address/payment/account/security edits remain blocked or Joy-only.",
        "blocked_metadata": blocked_metadata,
        "policy": "Sanitized checkout-prep/order-review summary only: structured fields are isolated; street addresses, full payment/account/card numbers, emails, phone numbers, security-code text, raw DOM, cookies, storage, request headers, and ordinary final-purchase controls are not returned as summary fields.",
    }
    binding_material = {
        "items": sanitized["items"],
        "totals": sanitized["totals"],
        "delivery": sanitized["delivery"],
        "shipping_destination_city_state_or_label": sanitized["shipping_destination_city_state_or_label"],
        "payment_method_label_last_four_only": sanitized["payment_method_label_last_four_only"],
        "purchase_mode": sanitized["purchase_mode"],
        "subscription_offer_visible": sanitized["subscription_offer_visible"],
        "subscription_selected": sanitized["subscription_selected"],
        "informational_flags": sanitized["informational_flags"],
        "surprise_flags": sanitized["surprise_flags"],
        "url": sanitized["url"],
        "final_purchase_controls_present": blocked_metadata["final_purchase_controls_present"],
    }
    sanitized["material_summary_binding"] = hashlib.sha256(json.dumps(binding_material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return sanitized


def _sanitize_post_purchase_detail_text(value: Any, field: str = "") -> str:
    raw = str(value or "")
    text = _sanitize_shopping_text(raw)
    if not text:
        return ""
    if str(field or "").lower() == "delivery_status":
        delivery_match = re.search(
            r"\b(arriv(?:es|ing)(?:\s+(?:today|tomorrow|by\s+[^,.;]+|on\s+[^,.;]+))?|expected(?:\s+delivery)?(?:\s+[^,.;]+)?|estimated(?:\s+delivery)?(?:\s+[^,.;]+)?|delivered(?:\s+[^,.;]+)?|not\s+yet\s+shipped|shipped|track\s+package)\b",
            text,
            re.IGNORECASE,
        )
        if delivery_match:
            return delivery_match.group(0)[:160].strip()
    if _checkout_text_has_sensitive_marker(text) or _checkout_text_has_mixed_summary(text):
        return "[post-purchase detail redacted]"
    if len(text) > 220:
        return text[:217].rstrip() + "…"
    return text


def _sanitize_post_purchase_detail_list(value: Any, limit: int = 8, field: str = "") -> list[str]:
    return _dedupe_checkout_values([_sanitize_post_purchase_detail_text(item, field=field) for item in _as_checkout_list(value)])[:limit]


def _sanitize_post_purchase_summary(summary: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {
        "operation": "post_purchase_summary",
        "page_title": _sanitize_shopping_text(str(summary.get("page_title") or "")),
        "url": _sanitize_url(str(summary.get("url") or "")),
        "post_purchase_state": str(summary.get("post_purchase_state") or "post_purchase_context_visible"),
        "confirmation_visible": bool(summary.get("confirmation_visible")),
        "orders_page_visible": bool(summary.get("orders_page_visible")),
        "order_presence": _sanitize_post_purchase_detail_list(summary.get("order_presence"), limit=6, field="order_presence"),
        "delivery_status": _sanitize_post_purchase_detail_list(summary.get("delivery_status"), limit=8, field="delivery_status"),
        "item_clues": _sanitize_post_purchase_detail_list(summary.get("item_clues"), limit=6, field="item_clues"),
        "action_controls_visible": _sanitize_post_purchase_detail_list(summary.get("action_controls_visible"), limit=6, field="action_controls_visible"),
        "post_purchase_visual_evidence": "owner_only_available",
        "policy": "Sanitized post-purchase confirmation/order-verification summary only: raw order numbers, full address/payment/account/contact details, raw DOM, cookies, storage, request headers, and screenshots are not returned to Star. Complete visual proof remains owner-only to Joy.",
    }
    if sanitized["post_purchase_state"] not in {"post_purchase_confirmation_visible", "post_purchase_orders_visible", "post_purchase_context_visible"}:
        sanitized["post_purchase_state"] = "post_purchase_context_visible"
    binding_material = {
        "url": sanitized["url"],
        "post_purchase_state": sanitized["post_purchase_state"],
        "confirmation_visible": sanitized["confirmation_visible"],
        "orders_page_visible": sanitized["orders_page_visible"],
        "order_presence": sanitized["order_presence"],
        "delivery_status": sanitized["delivery_status"],
    }
    sanitized["post_purchase_summary_binding"] = hashlib.sha256(json.dumps(binding_material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return sanitized


def _post_purchase_summary_from_browser(browser: CdpSession, session_id: str) -> dict[str, Any]:
    summary = _evaluate(browser, session_id, POST_PURCHASE_EXTRACT_JS) or {}
    return _sanitize_post_purchase_summary(summary)


def _check_human_takeover_text(text: str) -> None:
    if SENSITIVE_ACTION_RE.search(text) or CHECKOUT_PREP_RE.search(text) or FINAL_PURCHASE_RE.search(text):
        raise ValueError("matched element appears to involve checkout/payment/address/login challenge scope; Joy must take over or use an explicit supervised checkout-prep effect")


def _check_cart_remove_url(url: str, title: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not AMAZON_HOST_RE.search(parsed.netloc):
        raise ValueError("remove_from_cart clicks are currently limited to https://*.amazon.* cart pages")
    if not CART_URL_RE.search(parsed.path):
        raise ValueError("remove_from_cart clicks require the current page to be an Amazon cart page")
    blocked_text = " ".join([parsed.query, title]).lower()
    if SENSITIVE_ACTION_RE.search(blocked_text):
        raise ValueError("current cart page metadata appears to involve checkout/payment/address/login challenge scope; Joy must take over")


def _assert_cart_remove_click_allowed(metadata: dict[str, Any], reason: str) -> None:
    if not str(reason or "").strip():
        raise ValueError("remove_from_cart clicks require a reason/approval reference")
    if not metadata.get("exists"):
        raise ValueError("remove_from_cart selector did not match any element")
    if metadata.get("disabled"):
        raise ValueError("remove_from_cart selector matched a disabled element")
    if not metadata.get("visible"):
        raise ValueError("remove_from_cart selector must match a visible cart line-item removal control")

    tag = str(metadata.get("tag") or "").upper()
    role = str(metadata.get("role") or "").lower()
    input_type = str(metadata.get("type") or "").lower()
    if tag not in ("A", "BUTTON", "INPUT") and role not in ("button", "link"):
        raise ValueError("remove_from_cart selector must match a visible button, input, link, or equivalent role")
    if tag == "INPUT" and input_type and input_type not in ("button", "submit"):
        raise ValueError("remove_from_cart input controls must be button or submit inputs")

    control_text = " ".join(str(metadata.get(key) or "") for key in ("text", "value", "aria_label", "labelled_by_text", "name", "title", "id"))
    if not CART_REMOVE_TEXT_RE.search(control_text):
        raise ValueError("remove_from_cart selector must directly identify a Delete/Remove cart item control")
    _check_human_takeover_text(control_text)
    _check_cart_remove_url(str(metadata.get("url") or ""), str(metadata.get("page_title") or ""))



def _checkout_metadata_text(metadata: dict[str, Any]) -> str:
    return " ".join(str(metadata.get(key) or "") for key in ("text", "value", "aria_label", "name", "title", "id", "page_title", "url"))


def _checkout_control_identity_text(metadata: dict[str, Any]) -> str:
    return " ".join(str(metadata.get(key) or "") for key in ("text", "value", "aria_label", "name", "title", "id"))


def _checkoutish_page_text(metadata: dict[str, Any]) -> str:
    parsed = urlparse(str(metadata.get("url") or ""))
    return " ".join([parsed.path, parsed.query, str(metadata.get("page_title") or ""), _checkout_metadata_text(metadata)])


def _assert_checkout_page(metadata: dict[str, Any], effect: str) -> None:
    parsed = urlparse(str(metadata.get("url") or ""))
    if parsed.scheme != "https" or not AMAZON_HOST_RE.search(parsed.netloc):
        raise ValueError(f"{effect} actions are currently limited to https://*.amazon.* pages")
    if not CHECKOUTISH_PAGE_RE.search(_checkoutish_page_text(metadata)):
        raise ValueError(f"{effect} actions require the current page to be an Amazon checkout-prep/review page")


def _assert_checkout_control_not_sensitive(control_text: str) -> None:
    if HUMAN_TAKEOVER_RE.search(control_text) and not SAFE_CHECKOUT_SENSITIVE_LABEL_RE.search(control_text):
        raise ValueError("matched checkout control appears to involve sensitive login/payment/address/account/contact scope; Joy must take over")


def _assert_checkout_click_allowed(metadata: dict[str, Any], effect: str, reason: str) -> None:
    if not str(reason or "").strip():
        raise ValueError(f"{effect} clicks require a reason/supervision reference")
    if not metadata.get("exists"):
        raise ValueError(f"{effect} selector did not match any element")
    if metadata.get("disabled"):
        raise ValueError(f"{effect} selector matched a disabled element")
    if not metadata.get("visible"):
        raise ValueError(f"{effect} selector must match a visible checkout-prep control")
    parsed = urlparse(str(metadata.get("url") or ""))
    if parsed.scheme != "https" or not AMAZON_HOST_RE.search(parsed.netloc):
        raise ValueError(f"{effect} clicks are currently limited to https://*.amazon.* pages")
    control_text = _checkout_metadata_text(metadata)
    control_identity_text = _checkout_control_identity_text(metadata)
    if FINAL_PURCHASE_RE.search(control_identity_text):
        raise ValueError("final purchase controls cannot be clicked by secure_browser_click; use the trusted Telegram approval path")
    if effect == "checkout_prep":
        if not CART_URL_RE.search(parsed.path):
            raise ValueError("checkout_prep clicks must start from an Amazon cart page")
        if not CHECKOUT_PREP_RE.search(control_text):
            raise ValueError("checkout_prep selector must identify a visible checkout/proceed-to-checkout control")
        return
    _assert_checkout_page(metadata, effect)
    _assert_checkout_control_not_sensitive(control_text)


def _assert_checkout_type_allowed(metadata: dict[str, Any], effect: str, reason: str, typed_text: str) -> None:
    if not str(reason or "").strip():
        raise ValueError(f"{effect} typing requires a reason/supervision reference")
    if not metadata.get("exists"):
        raise ValueError(f"{effect} selector did not match any field")
    if metadata.get("disabled"):
        raise ValueError(f"{effect} selector matched a disabled field")
    if not metadata.get("visible"):
        raise ValueError(f"{effect} selector must match a visible checkout-prep field")
    tag = str(metadata.get("tag") or "").upper()
    role = str(metadata.get("role") or "").lower()
    input_type = str(metadata.get("type") or "").lower()
    if tag not in ("INPUT", "TEXTAREA", "SELECT") and role not in ("textbox", "spinbutton", "combobox", "option"):
        raise ValueError(f"{effect} typing is limited to visible input/select/textarea-style checkout-prep controls")
    if tag == "INPUT" and input_type in ("hidden", "password"):
        raise ValueError("matched checkout field is hidden or sensitive; Joy must take over")
    control_text = _checkout_metadata_text(metadata)
    if FINAL_PURCHASE_RE.search(_checkout_control_identity_text(metadata)):
        raise ValueError("final purchase controls cannot be modified by secure_browser_type; use the trusted Telegram approval path")
    _assert_checkout_page(metadata, effect)
    _assert_checkout_control_not_sensitive(control_text)
    if SENSITIVE_FIELD_RE.search(control_text) and not SAFE_CHECKOUT_SENSITIVE_LABEL_RE.search(control_text):
        raise ValueError("matched field appears sensitive; Joy must take over")
    if SENSITIVE_TYPED_TEXT_RE.search(str(typed_text or "")):
        raise ValueError("typed text appears to contain contact, address, payment, or security material; Joy must take over")


def _checkout_summary_from_browser(browser: CdpSession, session_id: str, max_controls: int = MAX_LINKS) -> dict[str, Any]:
    safety = _evaluate(browser, session_id, CHECKOUT_PAGE_SAFETY_JS) or {}
    summary = _evaluate(browser, session_id, ORDER_REVIEW_EXTRACT_JS) or {}
    controls_expr = CHECKOUT_PREP_CONTROLS_JS.replace("__MAX_CONTROLS__", str(max(0, min(int(max_controls), MAX_LINKS))))
    controls = _evaluate(browser, session_id, controls_expr) or {}
    return _sanitize_checkout_summary(summary, safety, controls)

def _check_secure_browser() -> bool:
    return bool(CDP_ENDPOINT_URL) or shutil.which("kubectl") is not None


def _sanitize_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


_ORDER_REFERENCE_RE = re.compile(r"\b(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9-]{8,}\b", re.IGNORECASE)


def _sanitize_shopping_text(value: Any) -> str:
    raw = _ORDER_REFERENCE_RE.sub("[order reference redacted]", str(value or ""))
    text = _sanitize_checkout_text(raw)
    text = _ORDER_REFERENCE_RE.sub("[order reference redacted]", text)
    text = text.replace("[[order reference redacted] redacted]", "[order reference redacted]")
    return text


def _sanitize_shopping_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_shopping_text(value)
    if isinstance(value, list):
        return [_sanitize_shopping_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_shopping_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_shopping_value(item) for key, item in value.items()}
    return value


def _sanitize_product_image_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not AMAZON_IMAGE_HOST_RE.search(parsed.netloc):
        return None
    if not parsed.path.startswith("/images/"):
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _safe_screenshot_path() -> str:
    os.makedirs(SCREENSHOT_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(SCREENSHOT_DIR, f"secure-browser-{stamp}-{os.getpid()}.png")


def _screenshot_policy(url: str, title: str) -> dict[str, Any]:
    parsed = urlparse(url)
    sensitive_url = " ".join([parsed.path, parsed.query, title]).lower()
    if _is_amazon_post_purchase_page(url, title):
        return {"mode": "post_purchase_redacted", "redaction_required": True}
    if re.search(r"(signin|login|ap/signin|account|orders|passkey|password|captcha|verification)", sensitive_url):
        raise ValueError("current page appears to be login, account, order-history, CAPTCHA, passkey, or verification scope; Joy must take over before screenshots")
    checkoutish = re.search(r"checkout|buy|payselect|ship|spc|review|ordering", " ".join([parsed.path, parsed.query, title]), re.IGNORECASE)
    if checkoutish and parsed.scheme == "https" and AMAZON_HOST_RE.search(parsed.netloc):
        return {"mode": "checkout_prep_redacted", "redaction_required": True}
    if re.search(r"(checkout|buy|place-order|address|wallet|payment)", sensitive_url):
        raise ValueError("current page appears to be checkout, payment, address, or wallet scope; Joy must take over before raw screenshots")
    return {"mode": "standard", "redaction_required": False}


def _redaction_hash(redaction: dict[str, Any]) -> str:
    material = str(redaction.get("redaction_rects_sha256_material") or "[]")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _write_screenshot(output_path: str, data: bytes) -> None:
    with open(output_path, "wb") as handle:
        handle.write(data)
    os.chmod(output_path, 0o600)


def _safe_owner_review_path(name: Any) -> str:
    os.makedirs(OWNER_CHECKOUT_REVIEW_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = _safe_artifact_stem(name, "owner-checkout-review")
    return os.path.join(OWNER_CHECKOUT_REVIEW_DIR, f"secure-browser-{stamp}-{os.getpid()}-{stem}.png")


def _profile_env_candidates() -> list[str]:
    candidates = []
    hermes_home = os.environ.get("HERMES_HOME")
    profile = os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_NAME")
    if hermes_home:
        candidates.append(os.path.join(hermes_home, ".env"))
    if profile:
        candidates.append(os.path.expanduser(f"~/.hermes/profiles/{profile}/.env"))
    candidates.append(os.path.expanduser("~/.hermes/profiles/star/.env"))
    candidates.append(os.path.expanduser("~/.hermes/.env"))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _dotenv_value(path: str, key: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                line_key, line_value = line.split("=", 1)
                if line_key.strip() != key:
                    continue
                value = line_value.strip()
                if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
                    value = value[1:-1]
                return value
    except OSError:
        return ""
    return ""


def _env_or_dotenv(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    for path in _profile_env_candidates():
        value = _dotenv_value(path, key).strip()
        if value:
            return value
    return ""


def _telegram_owner_destination() -> tuple[str, str | None]:
    target = _env_or_dotenv("SECURE_BROWSER_OWNER_TELEGRAM_CHAT") or _env_or_dotenv("TELEGRAM_HOME_CHANNEL")
    target = target.strip()
    if not target:
        raise RuntimeError("owner-only checkout review requires TELEGRAM_HOME_CHANNEL or SECURE_BROWSER_OWNER_TELEGRAM_CHAT")
    if target.startswith("telegram:"):
        target = target.split(":", 1)[1]
    thread_id = _env_or_dotenv("SECURE_BROWSER_OWNER_TELEGRAM_THREAD")
    if not thread_id and target.count(":") == 1 and target.split(":", 1)[0].lstrip("-").isdigit():
        target, thread_id = target.split(":", 1)
    return target, (thread_id or None)


def _multipart_request(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"secure-browser-{os.getpid()}-{int(time.time() * 1000)}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for key, (filename, data, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode("utf-8"))
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _telegram_send_document(path: str, caption: str) -> dict[str, Any]:
    token = _env_or_dotenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("owner-only checkout review requires TELEGRAM_BOT_TOKEN")
    chat_id, thread_id = _telegram_owner_destination()
    with open(path, "rb") as handle:
        data = handle.read()
    fields = {
        "chat_id": chat_id,
        "caption": caption[:1024],
        "disable_notification": "false",
    }
    if thread_id:
        fields["message_thread_id"] = thread_id
    body, content_type = _multipart_request(fields, {"document": (os.path.basename(path), data, "image/png")})
    request = Request(f"https://api.telegram.org/bot{token}/sendDocument", data=body, headers={"Content-Type": content_type})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("Telegram owner-review delivery failed")
    result = payload.get("result") or {}
    return {"message_id": result.get("message_id"), "chat_id": ((result.get("chat") or {}).get("id"))}


def _safe_artifact_stem(value: Any, fallback: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or fallback).strip().lower()).strip("-._")
    return (stem or fallback)[:MAX_CROP_NAME_CHARS]


def _safe_visual_path(name: Any, suffix: str = ".png") -> str:
    os.makedirs(SCREENSHOT_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = _safe_artifact_stem(name, "visual-evidence")
    return os.path.join(SCREENSHOT_DIR, f"secure-browser-{stamp}-{os.getpid()}-{stem}{suffix}")


def _png_dimensions(path: str) -> tuple[int, int]:
    with open(path, "rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError("screenshot artifact is not a PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _bounded_crop_rect(rect: dict[str, Any], image_width: int, image_height: int, scale_x: float, scale_y: float, padding: int) -> dict[str, int]:
    try:
        x = float(rect.get("x", 0)) * scale_x
        y = float(rect.get("y", 0)) * scale_y
        width = float(rect.get("width", 0)) * scale_x
        height = float(rect.get("height", 0)) * scale_y
    except (TypeError, ValueError):
        raise ValueError("crop rect must contain numeric x, y, width, and height") from None
    pad = max(0, min(int(padding), MAX_CROP_PADDING))
    crop_x = max(0, int(round(x - pad)))
    crop_y = max(0, int(round(y - pad)))
    crop_right = min(image_width, int(round(x + width + pad)))
    crop_bottom = min(image_height, int(round(y + height + pad)))
    crop_width = crop_right - crop_x
    crop_height = crop_bottom - crop_y
    if crop_width < MIN_CROP_SIZE or crop_height < MIN_CROP_SIZE:
        raise ValueError("crop rectangle is too small or outside the captured image")
    return {
        "x": crop_x,
        "y": crop_y,
        "width": crop_width,
        "height": crop_height,
        "highlight_x": max(0, int(round(x - crop_x))),
        "highlight_y": max(0, int(round(y - crop_y))),
        "highlight_width": max(1, min(crop_width, int(round(width)))),
        "highlight_height": max(1, min(crop_height, int(round(height)))),
    }


def _crop_png(source_path: str, output_path: str, crop: dict[str, int], highlight: bool) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for secure browser crop generation")
    crop_filter = f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}"
    filters = [crop_filter]
    if highlight:
        filters.append(f"drawbox=x={crop['highlight_x']}:y={crop['highlight_y']}:w={crop['highlight_width']}:h={crop['highlight_height']}:color=yellow@0.85:t=4")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source_path, "-vf", ",".join(filters), "-frames:v", "1", output_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=XWD_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if isinstance(proc.stderr, bytes) else str(proc.stderr)
        raise RuntimeError(f"crop generation failed: {stderr[:800]}")
    os.chmod(output_path, 0o600)


def _x11_screenshot() -> bytes:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for Kasm display screenshot fallback")
    capture = subprocess.run(
        ["kubectl", "-n", NAMESPACE, "exec", WORKLOAD, "--", "xwd", "-root", "-silent", "-display", BROWSER_DISPLAY],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=XWD_TIMEOUT_SECONDS,
        check=False,
    )
    if capture.returncode != 0 or not capture.stdout:
        stderr = capture.stderr.decode("utf-8", errors="replace") if isinstance(capture.stderr, bytes) else str(capture.stderr)
        raise RuntimeError(f"Kasm display screenshot capture failed: {stderr[:800]}")
    convert = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "xwd_pipe", "-i", "pipe:0", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
        input=capture.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=XWD_TIMEOUT_SECONDS,
        check=False,
    )
    if convert.returncode != 0 or not convert.stdout:
        stderr = convert.stderr.decode("utf-8", errors="replace") if isinstance(convert.stderr, bytes) else str(convert.stderr)
        raise RuntimeError(f"Kasm display screenshot conversion failed: {stderr[:800]}")
    return convert.stdout


def _page_targets_from_http(cdp_url: str) -> list[dict[str, str]]:
    with urlopen(f"{cdp_url}/json/list", timeout=3) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = []
    for target in targets:
        if target.get("type") == "page":
            pages.append(
                {
                    "id": str(target.get("id") or ""),
                    "url": str(target.get("url") or ""),
                    "title": str(target.get("title") or ""),
                }
            )
    return pages


def _page_info_for_id(cdp_url: str, target_id: str) -> dict[str, str]:
    for page in _page_targets_from_http(cdp_url):
        if page.get("id") == target_id:
            return page
    return {"id": target_id, "url": "about:blank", "title": ""}


def _target_page_info(cdp_url: str) -> dict[str, str]:
    pages = _page_targets_from_http(cdp_url)
    return pages[0] if pages else {"id": "", "url": "about:blank", "title": ""}


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
    if op in ("browse", "navigate", "page_snapshot", "query", "order_history", "buy_again", "past_order_details"):
        return {
            "allowed": True,
            "operation": op,
            "approval_required": False,
            "boundary": "trusted_assistant_browsing_sanitized",
            "message": "Allowed for ordinary shopping, account research, including Amazon order history and Buy Again pages. Outputs are sanitized; Star must pause for login, Bitwarden, passkeys, 2FA/CAPTCHA, suspicious security prompts, payment/address/account edits, and final purchase submission.",
        }
    if op == "checkout":
        return {
            "allowed": True,
            "operation": op,
            "approval_required": False,
            "boundary": "checkout_prep_only",
            "message": "Checkout prep is allowed under Joy's live supervision only through broad secure-browser clicks with approved_effect='checkout_prep', 'select_shipping_option', or 'apply_checkout_option'. Star must pause for login, Bitwarden, passkeys, 2FA, CAPTCHA, suspicious security prompts, payment/address/account edits, or sensitive-information prompts. Final Buy Now/Place Order remains blocked.",
        }
    if op in ("checkout_prep", "select_shipping_option", "apply_checkout_option"):
        return {
            "allowed": True,
            "operation": op,
            "approval_required": False,
            "boundary": "supervised_checkout_prep",
            "message": "Allowed only as an audited broad secure_browser_click approved_effect on visible Amazon checkout-prep controls. Final order submission and sensitive account/payment/address/login scopes are refused.",
        }
    if op == "remove_from_cart":
        return {
            "allowed": True,
            "operation": op,
            "approval_required": True,
            "message": "Allowed only through secure_browser_click with approved_effect='remove_from_cart', a human-readable reason/approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page.",
        }
    if op in ("request_final_purchase_approval", "final_purchase_approval"):
        return {
            "allowed": True,
            "operation": op,
            "approval_required": True,
            "trusted_approval_required": True,
            "boundary": "trusted_agent_request_telegram_approval",
            "message": "Star may request a trusted Agent Request Telegram approval after owner-only checkout review. The request is bound to material_summary_binding and owner_visual_evidence_binding; final execution remains separate and approval-gated.",
        }
    if op in ("place_order", "execute_final_purchase"):
        return {
            "allowed": False,
            "operation": op,
            "approval_required": True,
            "trusted_approval_required": True,
            "message": "Final purchase remains blocked from ordinary chat/tool execution. It requires a trusted Telegram approval action bound to the exact material checkout summary hash and owner visual evidence, then a trusted executor must revalidate the live checkout page and consume the approval exactly once.",
        }
    if op in UNSAFE_OPERATIONS:
        return {
            "allowed": False,
            "error": "OPERATION_NOT_ALLOWED",
            "operation": op,
            "message": "Star's shopping bridge allows scoped browsing, visible-page inspection, safe queries, careful clicks/types, cart inspection, explicitly approved add-to-cart, and explicitly approved visible cart line-item removal. Joy handles login, Bitwarden, passkeys, 2FA, CAPTCHA, checkout, Buy Now, Place Order, account, address, and payment actions manually.",
        }
    return {"allowed": True, "operation": op}


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CdpBridge:
    def __init__(self) -> None:
        self.local_port = _free_port()
        self.process: subprocess.Popen[str] | None = None
        self.cdp_url = CDP_ENDPOINT_URL

    def __enter__(self) -> str:
        if self.cdp_url:
            self._wait_for_endpoint(self.cdp_url, "secure browser CDP endpoint")
            return self.cdp_url

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
        self.cdp_url = f"http://127.0.0.1:{self.local_port}"
        self._wait_for_endpoint(self.cdp_url, "secure browser CDP bridge")
        return self.cdp_url

    def _wait_for_endpoint(self, cdp_url: str, label: str) -> None:
        deadline = time.time() + PORT_FORWARD_TIMEOUT_SECONDS
        version_url = f"{cdp_url}/json/version"
        last_error = ""
        while time.time() < deadline:
            if self.process and self.process.poll() is not None:
                stderr = (self.process.stderr.read() if self.process.stderr else "").strip()
                raise RuntimeError(f"kubectl port-forward failed: {stderr[:800]}")
            try:
                with urlopen(version_url, timeout=1) as response:
                    json.loads(response.read().decode("utf-8"))
                return
            except Exception as exc:
                last_error = str(exc)[:300]
                time.sleep(0.25)
        raise RuntimeError(f"timed out waiting for {label}: {last_error}")

    def __exit__(self, *_exc: object) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


class CdpSession:
    def __init__(self, websocket_url: str, cdp_url: str | None = None) -> None:
        self.ws = websockets.sync.client.connect(websocket_url, open_timeout=5, close_timeout=2, max_size=CDP_MAX_MESSAGE_BYTES)
        self.next_id = 1
        self.cdp_url = cdp_url

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


def _browser_ws_url(cdp_url: str) -> str:
    with urlopen(f"{cdp_url}/json/version", timeout=3) as response:
        version = json.loads(response.read().decode("utf-8"))
    url = str(version.get("webSocketDebuggerUrl") or "")
    if not url:
        raise RuntimeError("secure browser CDP endpoint did not report a browser websocket")
    endpoint = urlparse(cdp_url)
    parsed = urlparse(url)
    scheme = "wss" if endpoint.scheme == "https" else "ws"
    return urlunparse((scheme, endpoint.netloc, parsed.path, "", parsed.query, parsed.fragment))


def _current_page_ids(browser: CdpSession) -> set[str]:
    ids: set[str] = set()
    if browser.cdp_url is not None:
        with contextlib.suppress(Exception):
            ids.update(str(target["id"]) for target in _page_targets_from_http(browser.cdp_url) if target.get("id"))
    with contextlib.suppress(Exception):
        targets = browser.call("Target.getTargets").get("targetInfos") or []
        ids.update(str(target["targetId"]) for target in targets if target.get("type") == "page" and target.get("targetId"))
    return ids


def _load_owner_state(handle: Any) -> dict[str, Any]:
    handle.seek(0)
    raw = handle.read()
    if not raw.strip():
        return {"owners": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"owners": {}}
    if not isinstance(data, dict):
        return {"owners": {}}
    owners = data.get("owners")
    if not isinstance(owners, dict):
        data["owners"] = {}
    return data


def _store_owner_state(handle: Any, state: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def _claim_owner_target(browser: CdpSession, create: bool = False) -> str:
    os.makedirs(os.path.dirname(OWNERSHIP_STATE_PATH) or ".", exist_ok=True)
    with open(OWNERSHIP_STATE_PATH, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            state = _load_owner_state(handle)
            owners = state.setdefault("owners", {})
            live_ids = _current_page_ids(browser)
            existing = str(owners.get(BROWSER_OWNER, {}).get("target_id") or "")
            if existing and existing in live_ids and not create:
                return existing
            target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
            owners[BROWSER_OWNER] = {
                "target_id": target_id,
                "toolset": TOOLSET,
                "workload": WORKLOAD,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _store_owner_state(handle, state)
            return target_id
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _first_page_target(browser: CdpSession) -> str:
    return _claim_owner_target(browser, create=False)


def _owned_page_info(browser: CdpSession) -> dict[str, str]:
    target_id = _first_page_target(browser)
    if browser.cdp_url is not None:
        with contextlib.suppress(Exception):
            return _page_info_for_id(browser.cdp_url, target_id)
    return {"id": target_id, "url": "about:blank", "title": ""}


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
    with CdpBridge() as cdp_url:
        browser = CdpSession(_browser_ws_url(cdp_url), cdp_url=cdp_url)
        try:
            return fn(browser)
        finally:
            browser.close()



def _navigate(url: str, new_page: bool) -> dict[str, Any]:
    safe_url = _safe_browser_url(url)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _claim_owner_target(browser, create=True) if new_page else _first_page_target(browser)
        session_id = _attach(browser, target_id)
        _navigate_and_wait(browser, session_id, safe_url)
        result = {
            "operation": "navigate",
            "status": "ok",
            "secure_browser_owner": BROWSER_OWNER,
            "url": _sanitize_url(str(_evaluate(browser, session_id, "location.href") or safe_url)),
            "page_title": _sanitize_shopping_text(str(_evaluate(browser, session_id, "document.title") or "")),
        }
        _audit("navigate", {"url": result["url"], "page_title": result["page_title"], "new_page": new_page})
        return result

    return _with_browser(run)


def _page_snapshot(max_text_chars: int = MAX_TEXT_CHARS, max_links: int = MAX_LINKS) -> dict[str, Any]:
    max_text_chars = max(500, min(int(max_text_chars), MAX_TEXT_CHARS))
    max_links = max(0, min(int(max_links), MAX_LINKS))
    expression = PAGE_SNAPSHOT_JS.replace("__MAX_TEXT_CHARS__", str(max_text_chars)).replace("__MAX_LINKS__", str(max_links))

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        url = str(_evaluate(browser, session_id, "location.href") or "")
        title = str(_evaluate(browser, session_id, "document.title") or "")
        if re.search(r"checkout|buy|payselect|ship|spc|review|ordering", " ".join([url, title]), re.IGNORECASE):
            result = _checkout_summary_from_browser(browser, session_id, max_controls=max_links)
            result["operation"] = "checkout_prep_snapshot"
            result["snapshot_note"] = "Checkout-prep pages return a sanitized order-review summary plus non-secret checkout-prep controls instead of raw visible text to avoid address/payment/account disclosure."
            return result
        result = _evaluate(browser, session_id, expression) or {}
        result["operation"] = "page_snapshot"
        if result.get("url"):
            result["url"] = _sanitize_url(str(result["url"]))
        result["page_title"] = _sanitize_shopping_text(result.get("page_title"))
        result = _sanitize_shopping_value(result)
        return result

    return _with_browser(run)


def _query(expression: str) -> dict[str, Any]:
    safe_expression = _safe_read_only_query(expression)
    wrapped = f"(() => {{ const value = ({safe_expression}); return value; }})()"

    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owned_page_info(browser)
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        url = str(_evaluate(browser, session_id, "location.href") or page_info.get("url") or "")
        title = str(_evaluate(browser, session_id, "document.title") or page_info.get("title") or "")
        if _is_amazon_checkoutish_page(url, title):
            checkout_review = _checkout_summary_from_browser(browser, session_id)
            return _checkout_query_summary_response(checkout_review, safe_expression, url=url, title=title)
        if _is_checkoutish_page(url, title):
            raise ValueError("generic secure_browser_query is unavailable on checkout/order-review pages outside the Amazon checkout-prep sanitizer boundary")
        value = _sanitize_shopping_value(_evaluate(browser, session_id, wrapped))
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(payload) > MAX_QUERY_RESULT_CHARS:
            value = payload[:MAX_QUERY_RESULT_CHARS] + "… [truncated]"
        return {"operation": "query", "status": "ok", "secure_browser_owner": BROWSER_OWNER, "value": value}

    return _with_browser(run)


def _screenshot(full_page: bool = False) -> dict[str, Any]:
    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owned_page_info(browser)
        url = str(page_info.get("url") or "")
        title = str(page_info.get("title") or "")
        policy = _screenshot_policy(url, title)
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        checkout_review: dict[str, Any] | None = None
        redaction: dict[str, Any] = {}
        if policy["redaction_required"]:
            checkout_review = _checkout_summary_from_browser(browser, session_id)
            if checkout_review.get("human_takeover_required"):
                raise ValueError(str(checkout_review.get("blocked_reason") or "sensitive checkout/security prompt is visible; Joy must take over before screenshots"))
            redaction = _evaluate(browser, session_id, CHECKOUT_SCREENSHOT_REDACTION_JS) or {}
            if int(redaction.get("redaction_overlay_count") or 0) < 1 and policy.get("mode") == "checkout_prep_redacted":
                raise ValueError("checkout-prep screenshot redaction found no address/payment/contact regions to cover; refusing visual capture")
        params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full_page) and not policy["redaction_required"]}
        capture_method = "cdp"
        cdp_error = ""
        try:
            captured = browser.call("Page.captureScreenshot", params, session_id=session_id)
            encoded = str(captured.get("data") or "")
            if not encoded:
                raise RuntimeError("secure browser did not return screenshot data")
            png_data = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            # Amazon can leave the page target unresponsive to Page/Runtime CDP
            # calls while the Kasm display itself is still live.  Fall back to a
            # container-scoped X11 root capture.  On checkout-prep pages this is
            # only allowed after a CDP-installed redaction overlay is active.
            capture_method = "kasm_x11"
            if policy["redaction_required"] and not redaction:
                raise RuntimeError("checkout-prep screenshot requires an active redaction overlay before X11 fallback") from exc
            png_data = _x11_screenshot()
            cdp_error = str(exc)[:500]
        finally:
            if policy["redaction_required"]:
                with contextlib.suppress(Exception):
                    _evaluate(browser, session_id, CHECKOUT_SCREENSHOT_REDACTION_CLEANUP_JS)
        output_path = _safe_screenshot_path()
        _write_screenshot(output_path, png_data)
        result = {
            "operation": "screenshot",
            "status": "ok",
            "path": output_path,
            "media": f"MEDIA:{output_path}",
            "url": _sanitize_url(url),
            "page_title": title,
            "full_page": bool(full_page) and capture_method == "cdp" and not policy["redaction_required"],
            "capture_method": capture_method,
            "screenshot_mode": policy["mode"],
            "safety_boundary": "Captured only the persistent secure browser page as a local PNG artifact. No raw CDP endpoint, cookies, local storage, request headers, vault contents, passwords, passkeys, 2FA/CAPTCHA data, or account/payment/address secrets were returned as structured text.",
        }
        if policy["redaction_required"]:
            result["redaction"] = {
                "status": "applied",
                "overlay_count": int(redaction.get("redaction_overlay_count") or 0),
                "redaction_rects_hash": _redaction_hash(redaction),
                "policy": "Redacted screenshot uses browser-side opaque overlays for address, payment, account/contact, order-reference, gift/promo-code, and security-prompt regions before capture. Full-page capture is disabled for redacted checkout/post-purchase evidence so off-viewport secrets are not captured without overlays.",
            }
            if checkout_review is not None:
                result["checkout_review"] = checkout_review
                result["material_summary_binding"] = checkout_review.get("material_summary_binding")
        if capture_method == "kasm_x11":
            result["fallback_reason"] = cdp_error
            result["full_page_note"] = "Kasm X11 fallback captures the visible browser display only."
        if policy["redaction_required"] and full_page:
            result["full_page_note"] = "Full-page capture was downgraded to the visible viewport because checkout-prep redaction is viewport-bound."
        _audit("screenshot", {"url": result["url"], "page_title": title, "path": output_path, "full_page": result["full_page"], "capture_method": capture_method, "screenshot_mode": result["screenshot_mode"], "checkout_binding": result.get("material_summary_binding"), "redaction_rects_hash": (result.get("redaction") or {}).get("redaction_rects_hash")})
        return result

    with CdpBridge() as cdp_url:
        browser = CdpSession(_browser_ws_url(cdp_url), cdp_url=cdp_url)
        try:
            return run(browser)
        finally:
            browser.close()


def _capture_cdp_png(browser: CdpSession, session_id: str, full_page: bool) -> bytes:
    params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full_page)}
    captured = browser.call("Page.captureScreenshot", params, session_id=session_id)
    encoded = str(captured.get("data") or "")
    if not encoded:
        raise RuntimeError("secure browser did not return screenshot data")
    return base64.b64decode(encoded, validate=True)


def _capture_owner_visual_artifacts(browser: CdpSession, session_id: str, review_id: str, retain_local: bool, caption_builder: Any) -> tuple[str, list[dict[str, Any]], list[str], int]:
    artifacts: list[tuple[str, bytes, str]] = []
    capture_mode = "full-page"
    try:
        artifacts.append(("full-page", _capture_cdp_png(browser, session_id, full_page=True), "full-page"))
    except Exception:
        capture_mode = "viewport-sequence"
        layout = _evaluate(browser, session_id, "(() => ({width: Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0, window.innerWidth), height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0, window.innerHeight), viewport_width: window.innerWidth, viewport_height: window.innerHeight, original_x: window.scrollX, original_y: window.scrollY}))()") or {}
        viewport_height = max(1, int(layout.get("viewport_height") or 900))
        document_height = max(viewport_height, int(layout.get("height") or viewport_height))
        positions = list(range(0, document_height, viewport_height))[:MAX_OWNER_REVIEW_VIEWPORTS]
        if positions and positions[-1] + viewport_height < document_height:
            positions.append(max(0, document_height - viewport_height))
        for seq, y in enumerate(positions[:MAX_OWNER_REVIEW_VIEWPORTS], 1):
            _evaluate(browser, session_id, f"window.scrollTo(0, {int(y)})")
            time.sleep(0.2)
            artifacts.append((f"viewport-{seq:02d}", _capture_cdp_png(browser, session_id, full_page=False), "viewport"))
        _evaluate(browser, session_id, f"window.scrollTo({int(layout.get('original_x') or 0)}, {int(layout.get('original_y') or 0)})")
    if not artifacts:
        raise RuntimeError("owner-only review captured no visual evidence")

    deliveries: list[dict[str, Any]] = []
    artifact_hashes: list[str] = []
    paths_to_remove: list[str] = []
    try:
        for index, (name, png_data, mode) in enumerate(artifacts, 1):
            artifact_hashes.append(hashlib.sha256(png_data).hexdigest())
            output_path = _safe_owner_review_path(f"{review_id}-{name}")
            _write_screenshot(output_path, png_data)
            if not retain_local:
                paths_to_remove.append(output_path)
            caption = caption_builder(index, len(artifacts), mode)
            deliveries.append(_telegram_send_document(output_path, caption))
    finally:
        if not retain_local:
            for path in paths_to_remove:
                with contextlib.suppress(OSError):
                    os.remove(path)
    return capture_mode, deliveries, artifact_hashes, len(artifacts)


def _owner_post_purchase_review_caption(review_id: str, index: int, count: int, binding: str, mode: str, post_purchase: dict[str, Any]) -> str:
    facts = _minimal_post_purchase_facts(post_purchase)
    delivery_note = ""
    if facts.get("delivery_status"):
        delivery_note = f"\nSanitized delivery clue: {str(facts['delivery_status'][0])[:160]}"
    return (
        "🔐 Owner-only post-purchase proof\n"
        f"Review: {review_id} ({index}/{count}, {mode})\n"
        f"Post-purchase summary binding: {binding}\n"
        f"State: {facts.get('post_purchase_state')}\n"
        "Inspect thank-you/order-confirmation or Your Orders evidence, including expected delivery information when visible.\n"
        "Star received only a redacted acknowledgement/summary; raw order numbers, full address/payment/account details, and screenshots stay owner-only."
        f"{delivery_note}"
    )


def _owner_post_purchase_review_from_attached(browser: CdpSession, session_id: str, url: str, title: str, retain_local: bool = False) -> dict[str, Any]:
    post_purchase = _post_purchase_summary_from_browser(browser, session_id)
    binding = str(post_purchase.get("post_purchase_summary_binding") or "")
    if not binding:
        raise RuntimeError("post-purchase review did not produce a summary binding")
    review_id = hashlib.sha256(f"post-purchase:{binding}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]

    def caption_builder(index: int, count: int, mode: str) -> str:
        return _owner_post_purchase_review_caption(review_id, index, count, binding, mode, post_purchase)

    capture_mode, deliveries, artifact_hashes, artifact_count = _capture_owner_visual_artifacts(browser, session_id, review_id, retain_local, caption_builder)
    evidence_binding = hashlib.sha256(json.dumps({"post_purchase_summary_binding": binding, "artifact_hashes": artifact_hashes}, sort_keys=True).encode("utf-8")).hexdigest()
    result = {
        "operation": "owner_post_purchase_review",
        "status": "sent_owner_only",
        "review_id": review_id,
        "url": _sanitize_url(url),
        "page_title": _sanitize_shopping_text(title),
        "post_purchase_summary_binding": binding,
        "owner_visual_evidence_binding": evidence_binding,
        "capture_mode": capture_mode,
        "artifact_count": artifact_count,
        "telegram_message_ids": [item.get("message_id") for item in deliveries],
        "post_purchase_review": post_purchase,
        "retention": "sensitive PNG artifacts were deleted locally after Telegram delivery" if not retain_local else "sensitive PNG artifacts retained locally with 0600 files under owner review directory",
        "safety_boundary": "Complete post-purchase screenshots were sent directly to Joy's configured Telegram destination and are not returned as MEDIA handles, file paths, raw DOM, cookies, storage, request headers, CDP endpoints, order numbers, or full address/payment/account/contact details to Star.",
    }
    try:
        result["shopping_order_tracking"] = _order_entry_from_post_purchase_review_result(result)
    except Exception as exc:
        result["shopping_order_tracking"] = {
            "status": "ledger_entry_failed",
            "message": str(exc)[:500],
            "safety_boundary": "Post-purchase owner proof was captured; order-ledger ingestion failed without exposing raw order/address/payment/browser evidence to Star.",
        }
    _audit("owner_post_purchase_review", {"review_id": review_id, "url": result["url"], "page_title": title, "post_purchase_summary_binding": binding, "owner_visual_evidence_binding": evidence_binding, "capture_mode": capture_mode, "artifact_count": artifact_count, "retained_local": retain_local, "order_tracking_status": (result.get("shopping_order_tracking") or {}).get("status")})
    return _compact_owner_checkout_review_result(result)


def _owner_checkout_review_caption(review_id: str, index: int, count: int, binding: str, mode: str, checkout_review: dict[str, Any]) -> str:
    total_note = ""
    totals = checkout_review.get("totals") or []
    if totals:
        total_note = f"\nSanitized totals clue: {str(totals[-1])[:160]}"
    return (
        "🔐 Sensitive owner-only checkout review\n"
        f"Review: {review_id} ({index}/{count}, {mode})\n"
        f"Material summary binding: {binding}\n"
        "Inspect shipping address, payment label/details, items, delivery, taxes/total, discounts, and final Place Order state.\n"
        "Star received only the redacted acknowledgement/summary; final purchase remains blocked until trusted approval."
        f"{total_note}"
    )


def _owner_checkout_review(send_to_telegram: bool = True, retain_local: bool = False) -> dict[str, Any]:
    if not send_to_telegram:
        raise ValueError("owner-only checkout review currently requires send_to_telegram=true so sensitive evidence is not returned to Star")
    if not _env_or_dotenv("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("owner-only checkout review requires TELEGRAM_BOT_TOKEN")
    _telegram_owner_destination()

    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owned_page_info(browser)
        url = str(page_info.get("url") or "")
        title = str(page_info.get("title") or "")
        parsed = urlparse(url)
        checkoutish = re.search(r"checkout|buy|payselect|ship|spc|review|ordering", " ".join([parsed.path, parsed.query, title]), re.IGNORECASE)
        post_purchase = _is_amazon_post_purchase_page(url, title)
        if not (parsed.scheme == "https" and AMAZON_HOST_RE.search(parsed.netloc) and (checkoutish or post_purchase)):
            raise ValueError("owner-only checkout review currently requires an Amazon checkout/order-review or post-purchase confirmation/orders page")
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        if post_purchase and not checkoutish:
            return _owner_post_purchase_review_from_attached(browser, session_id, url, title, retain_local=retain_local)
        safety = _evaluate(browser, session_id, CHECKOUT_PAGE_SAFETY_JS) or {}
        if safety.get("blocked_reason"):
            raise ValueError(str(safety.get("blocked_reason")))
        checkout_review = _checkout_summary_from_browser(browser, session_id)
        binding = str(checkout_review.get("material_summary_binding") or "")
        if not binding:
            raise RuntimeError("checkout review did not produce a material summary binding")
        review_id = hashlib.sha256(f"{binding}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]
        def caption_builder(index: int, count: int, mode: str) -> str:
            return _owner_checkout_review_caption(review_id, index, count, binding, mode, checkout_review)

        capture_mode, deliveries, artifact_hashes, artifact_count = _capture_owner_visual_artifacts(browser, session_id, review_id, retain_local, caption_builder)
        evidence_binding = hashlib.sha256(json.dumps({"material_summary_binding": binding, "artifact_hashes": artifact_hashes}, sort_keys=True).encode("utf-8")).hexdigest()
        result = {
            "operation": "owner_checkout_review",
            "status": "sent_owner_only",
            "review_id": review_id,
            "url": _sanitize_url(url),
            "page_title": title,
            "material_summary_binding": binding,
            "owner_visual_evidence_binding": evidence_binding,
            "capture_mode": capture_mode,
            "artifact_count": artifact_count,
            "telegram_message_ids": [item.get("message_id") for item in deliveries],
            "checkout_review": checkout_review,
            "retention": "sensitive PNG artifacts were deleted locally after Telegram delivery" if not retain_local else "sensitive PNG artifacts retained locally with 0600 files under owner review directory",
            "safety_boundary": "Complete checkout screenshots were sent directly to Joy's configured Telegram destination and are not returned as MEDIA handles, file paths, raw DOM, cookies, storage, request headers, CDP endpoints, credentials, passkeys, 2FA/CAPTCHA, or structured address/payment text to Star. Final Place Order remains blocked from ordinary shopping tools.",
        }
        _audit("owner_checkout_review", {"review_id": review_id, "url": result["url"], "page_title": title, "material_summary_binding": binding, "owner_visual_evidence_binding": evidence_binding, "capture_mode": capture_mode, "artifact_count": artifact_count, "retained_local": retain_local})
        return _compact_owner_checkout_review_result(result)

    return _with_browser(run)


def _visual_regions(browser: CdpSession, session_id: str) -> dict[str, Any]:
    expression = VISUAL_REGIONS_JS.replace("__MAX_REGIONS__", str(MAX_VISUAL_REGIONS))
    result = _evaluate(browser, session_id, expression) or {}
    if result.get("url"):
        result["url"] = _sanitize_url(str(result["url"]))
    return result


def _rect_for_selector(browser: CdpSession, session_id: str, selector: str) -> dict[str, Any]:
    safe_selector = _selector_arg(selector)
    expression = f"""
(() => {{
  const node = document.querySelector({_json_literal(safe_selector)});
  if (!node) return null;
  const rect = node.getBoundingClientRect();
  if (!rect || rect.width < 1 || rect.height < 1) return null;
  return {{
    x: Math.max(0, Math.round(rect.left + window.scrollX)),
    y: Math.max(0, Math.round(rect.top + window.scrollY)),
    width: Math.round(rect.width),
    height: Math.round(rect.height)
  }};
}})()
"""
    rect = _evaluate(browser, session_id, expression)
    if not rect:
        raise ValueError("selector did not match a visible element for cropping")
    return rect


def _resolve_crop_rect(spec: dict[str, Any], regions: list[dict[str, Any]], browser: CdpSession, session_id: str) -> tuple[str, str, dict[str, Any]]:
    name = str(spec.get("name") or spec.get("region_id") or spec.get("category") or spec.get("selector") or "crop")[:MAX_CROP_NAME_CHARS]
    if isinstance(spec.get("rect"), dict):
        return name, "manual_rect", spec["rect"]
    if all(key in spec for key in ("x", "y", "width", "height")):
        return name, "manual_rect", {"x": spec["x"], "y": spec["y"], "width": spec["width"], "height": spec["height"]}
    selector = str(spec.get("selector") or "").strip()
    if selector:
        return name, "selector", _rect_for_selector(browser, session_id, selector)
    region_id = str(spec.get("region_id") or "").strip()
    category = str(spec.get("category") or "").strip()
    text_anchor = str(spec.get("text_anchor") or "").strip().lower()
    for region in regions:
        if region_id and region.get("region_id") != region_id:
            continue
        if category and region.get("category") != category:
            continue
        if text_anchor and text_anchor not in str(region.get("text_anchor") or "").lower():
            continue
        rect = region.get("rect")
        if isinstance(rect, dict):
            return name or str(region.get("label") or "crop"), "suggested_region", rect
    raise ValueError("crop spec did not match any suggested region; use region_id, category, selector, or explicit rect")


def _visual_evidence(full_page: bool, include_full_page: bool, crops: list[Any]) -> dict[str, Any]:
    if len(crops) > MAX_VISUAL_CROPS:
        raise ValueError(f"at most {MAX_VISUAL_CROPS} crops may be requested at once")

    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owned_page_info(browser)
        url = str(page_info.get("url") or "")
        title = str(page_info.get("title") or "")
        policy = _screenshot_policy(url, title)
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        regions = _visual_regions(browser, session_id)
        screenshot = _screenshot(full_page)
        image_width, image_height = _png_dimensions(str(screenshot["path"]))
        document = regions.get("document") or {}
        viewport = regions.get("viewport") or {}
        if screenshot.get("full_page"):
            basis_width = max(1, float(document.get("width") or viewport.get("width") or image_width))
            basis_height = max(1, float(document.get("height") or viewport.get("height") or image_height))
        else:
            basis_width = max(1, float(viewport.get("width") or image_width))
            basis_height = max(1, float(viewport.get("height") or image_height))
            offset_x = float(viewport.get("x") or 0)
            offset_y = float(viewport.get("y") or 0)
            adjusted = []
            for region in regions.get("regions") or []:
                rect = region.get("rect") or {}
                view_rect = dict(rect)
                view_rect["x"] = float(view_rect.get("x") or 0) - offset_x
                view_rect["y"] = float(view_rect.get("y") or 0) - offset_y
                if view_rect["x"] + float(view_rect.get("width") or 0) <= 0 or view_rect["y"] + float(view_rect.get("height") or 0) <= 0:
                    continue
                if view_rect["x"] >= basis_width or view_rect["y"] >= basis_height:
                    continue
                cloned = dict(region)
                cloned["rect"] = view_rect
                adjusted.append(cloned)
            regions["regions"] = adjusted
        scale_x = image_width / basis_width
        scale_y = image_height / basis_height
        crop_results = []
        for index, raw_spec in enumerate(crops, 1):
            if not isinstance(raw_spec, dict):
                raise ValueError("each crop spec must be an object")
            name, source, rect = _resolve_crop_rect(raw_spec, list(regions.get("regions") or []), browser, session_id)
            if not screenshot.get("full_page") and source != "suggested_region":
                rect = dict(rect)
                rect["x"] = float(rect.get("x") or 0) - float(viewport.get("x") or 0)
                rect["y"] = float(rect.get("y") or 0) - float(viewport.get("y") or 0)
            crop = _bounded_crop_rect(rect, image_width, image_height, scale_x, scale_y, int(raw_spec.get("padding", 24)))
            output_path = _safe_visual_path(f"crop-{index}-{name}")
            _crop_png(str(screenshot["path"]), output_path, crop, bool(raw_spec.get("highlight", True)))
            crop_results.append({
                "name": name,
                "source": source,
                "path": output_path,
                "media": f"MEDIA:{output_path}",
                "crop_rect_pixels": {key: crop[key] for key in ("x", "y", "width", "height")},
                "highlighted": bool(raw_spec.get("highlight", True)),
            })
        result = {
            "operation": "visual_evidence",
            "status": "ok",
            "url": screenshot.get("url"),
            "page_title": screenshot.get("page_title"),
            "screenshot_mode": screenshot.get("screenshot_mode"),
            "capture_method": screenshot.get("capture_method"),
            "full_page_captured": screenshot.get("full_page"),
            "full_page_path": screenshot.get("path"),
            "full_page_media": screenshot.get("media") if include_full_page else None,
            "full_page_note": screenshot.get("full_page_note"),
            "suggested_regions": regions.get("regions") or [],
            "crops": crop_results,
            "redaction": screenshot.get("redaction"),
            "checkout_review": screenshot.get("checkout_review"),
            "material_summary_binding": screenshot.get("material_summary_binding"),
            "safety_boundary": "Full-page/viewport image artifacts and crops are local PNGs from the secure browser only. Suggested regions expose sanitized labels, selectors, and bounding boxes, not raw DOM/HTML, cookies, local storage, request headers, CDP endpoints, credentials, or browser internals. Checkout-prep evidence is redacted and downgraded to viewport capture when necessary.",
        }
        _audit("visual_evidence", {"url": result["url"], "page_title": result["page_title"], "full_page_path": result["full_page_path"], "crop_count": len(crop_results), "full_page_captured": result["full_page_captured"], "screenshot_mode": result["screenshot_mode"], "checkout_binding": result.get("material_summary_binding")})
        return result

    return _with_browser(run)


def _click(selector: str, reason: str, approved_effect: str) -> dict[str, Any]:
    safe_selector = _selector_arg(selector)
    effect = str(approved_effect or "browse").strip().lower()
    if effect not in APPROVED_CLICK_EFFECTS:
        raise ValueError(f"approved_effect must be {', '.join(APPROVED_CLICK_EFFECTS)}")
    if effect in ("add_to_cart", "remove_from_cart") and not str(reason or "").strip():
        raise ValueError(f"{effect} clicks require a reason/approval reference")

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        label_expr = f"(() => {{ const n = document.querySelector({_json_literal(safe_selector)}); return n ? ((n.innerText || n.value || n.getAttribute('aria-label') || n.textContent || '').replace(/\\s+/g, ' ').trim()) : ''; }})()"
        label = str(_evaluate(browser, session_id, label_expr) or "")
        if effect == "remove_from_cart":
            remove_metadata = _evaluate(browser, session_id, CART_REMOVE_CONTROL_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
            _assert_cart_remove_click_allowed(remove_metadata, reason)
        elif effect in CHECKOUT_APPROVED_EFFECTS:
            checkout_metadata = _evaluate(browser, session_id, CHECKOUT_CONTROL_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
            _assert_checkout_click_allowed(checkout_metadata, effect, reason)
        elif effect != "add_to_cart":
            _check_human_takeover_text(label)
        result = _evaluate(browser, session_id, CLICK_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
        time.sleep(1.0)
        result["operation"] = "click"
        result["approved_effect"] = effect
        result["url"] = _sanitize_url(str(result.get("url") or _evaluate(browser, session_id, "location.href") or ""))
        if effect in CHECKOUT_APPROVED_EFFECTS:
            result["checkout_review"] = _checkout_summary_from_browser(browser, session_id)
        _audit("click", {"selector": safe_selector, "effect": effect, "reason": str(reason or "")[:300], "element_text": result.get("element_text"), "url": result.get("url"), "checkout_binding": (result.get("checkout_review") or {}).get("material_summary_binding")})
        return result

    return _with_browser(run)


def _type(selector: str, text: str, reason: str, approved_effect: str = "type") -> dict[str, Any]:
    safe_selector = _selector_arg(selector)
    safe_text = _bounded_text(text)
    effect = str(approved_effect or "type").strip().lower()
    if effect not in APPROVED_TYPE_EFFECTS:
        raise ValueError(f"approved_effect must be {', '.join(APPROVED_TYPE_EFFECTS)}")
    selector_lower = safe_selector.lower()
    if SENSITIVE_FIELD_RE.search(selector_lower):
        raise ValueError("selector appears to target a sensitive credential/contact/payment/address field; Joy must take over")
    if SENSITIVE_FIELD_RE.search(str(reason or "")):
        raise ValueError("reason describes sensitive credential/contact/payment/address input; Joy must take over")

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        field_expr = f"(() => {{ const n = document.querySelector({_json_literal(safe_selector)}); return n ? [n.type || '', n.name || '', n.id || '', n.getAttribute('aria-label') || '', n.placeholder || ''].join(' ') : ''; }})()"
        field_text = str(_evaluate(browser, session_id, field_expr) or "")
        if effect == "type" and SENSITIVE_FIELD_RE.search(field_text):
            raise ValueError("matched field appears sensitive; Joy must take over")
        if effect != "type":
            checkout_metadata = _evaluate(browser, session_id, CHECKOUT_CONTROL_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
            _assert_checkout_type_allowed(checkout_metadata, effect, reason, safe_text)
        result = _evaluate(browser, session_id, TYPE_JS.replace("__SELECTOR__", _json_literal(safe_selector)).replace("__VALUE__", _json_literal(safe_text))) or {}
        time.sleep(1.0)
        result["operation"] = "type"
        result["approved_effect"] = effect
        result["typed_chars"] = len(safe_text)
        result["url"] = _sanitize_url(str(result.get("url") or _evaluate(browser, session_id, "location.href") or ""))
        if effect != "type":
            result["checkout_review"] = _checkout_summary_from_browser(browser, session_id)
        _audit("type", {"selector": safe_selector, "effect": effect, "typed_chars": len(safe_text), "reason": str(reason or "")[:300], "url": result.get("url"), "checkout_binding": (result.get("checkout_review") or {}).get("material_summary_binding")})
        return result

    return _with_browser(run)


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
        url = str(_evaluate(browser, session_id, "location.href") or "")
        title = str(_evaluate(browser, session_id, "document.title") or "")
        if _is_amazon_post_purchase_page(url, title):
            result = _post_purchase_summary_from_browser(browser, session_id)
            result["operation"] = "post_purchase_current_page_summary"
            result["secure_browser_owner"] = BROWSER_OWNER
            result["summary_note"] = "Post-purchase confirmation/order-verification pages return sanitized proof fields, not checkout-prep or final-purchase approval state."
            return result
        if re.search(r"checkout|buy|payselect|ship|spc|review|ordering", " ".join([url, title]), re.IGNORECASE):
            result = _checkout_summary_from_browser(browser, session_id)
            result["operation"] = "checkout_prep_current_page_summary"
            result["secure_browser_owner"] = BROWSER_OWNER
            result["summary_note"] = "Checkout-prep pages return isolated sanitized fields instead of generic current-page summary blobs. Final purchase controls are confined to blocked_metadata."
            return result
        result = _evaluate(browser, session_id, SUMMARY_EXTRACT_JS) or {}
        if url:
            result["url"] = _sanitize_url(url)
        result["operation"] = "current_page_summary"
        result["secure_browser_owner"] = BROWSER_OWNER
        return _sanitize_shopping_value(result)

    return _with_browser(run)


def secure_browser_status_tool(args: dict[str, Any], **_kw: Any) -> str:
    status = {
        "toolset": TOOLSET,
        "namespace": NAMESPACE,
        "workload": WORKLOAD,
        "kubectl_available": shutil.which("kubectl") is not None,
        "cdp_endpoint_configured": bool(CDP_ENDPOINT_URL),
        "cdp_access_mode": "service_endpoint" if CDP_ENDPOINT_URL else "kubectl_port_forward",
        "remote_debug_port": REMOTE_DEBUG_PORT,
        "secure_browser_owner": BROWSER_OWNER,
        "ownership_state_path": OWNERSHIP_STATE_PATH,
        "browser_operations": ["navigate", "page_snapshot", "query", "click", "type", "screenshot", "visual_evidence", "current_page_summary", "owner_checkout_review", "order_list", "order_read", "order_upsert", "order_close", "order_notification_preview", "order_mark_notified", "order_refresh_plan", "order_refresh_run", "consumable_list", "consumable_upsert"],
        "trusted_assistant_access": {
            "status": "broad_browsing_available",
            "message": "Star may navigate and inspect ordinary shopping, account research surfaces, including Amazon order history, Buy Again, past-order details, and product links. The bridge gates capabilities and sanitizes outputs instead of blanket-blocking account/order-history URLs.",
            "human_takeover_boundaries": ["login", "Bitwarden", "passkeys", "2FA/OTP", "CAPTCHA", "suspicious security prompts", "payment/address/account edits", "final purchase submission"],
        },
        "supervised_checkout_prep": {
            "status": "available",
            "approved_click_effects": list(CHECKOUT_APPROVED_EFFECTS),
            "approved_type_effects": ["apply_checkout_option", "cart_line_adjustment"],
            "boundary": "Star may inspect sanitized checkout-prep controls and click/type into ordinary review-page controls under Joy's live supervision with explicit approved_effect values. Star must pause for login, Bitwarden, passkeys, 2FA, CAPTCHA, suspicious security prompts, payment/address/account edits, or sensitive-information prompts.",
            "sanitization": "Checkout-prep snapshots/current-page summaries return isolated structured item/totals/delivery/surprise fields plus destination city-state/abstract label and payment labels. Mixed blobs, sensitive redaction-marker text, and final purchase controls are removed from ordinary summary fields.",
            "visual_confirmation": "secure_browser_visual_evidence returns a bounded visual proof bundle: a local PNG screenshot, sanitized suggested regions, and optional focused crops. Amazon checkout/order-review pages are allowed only as redacted checkout-prep viewport evidence; Amazon thank-you/post-purchase pages are labeled as post-purchase evidence; login/account/payment/address/security pages remain Joy-only.",
            "owner_only_confirmation": "secure_browser_owner_checkout_review can send complete unredacted checkout screenshots directly to Joy's configured Telegram destination without returning paths, MEDIA handles, raw DOM, cookies, storage, request headers, CDP endpoints, or address/payment text to Star.",
        },
        "approval_gated_operations": {
            "add_to_cart": "available only through the broad secure_browser_click flow with approved_effect='add_to_cart' and a human-readable approval reference",
            "remove_from_cart": "available only through secure_browser_click with approved_effect='remove_from_cart', a human-readable approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page",
            "request_final_purchase_approval": "Star-callable after owner_checkout_review; creates a trusted Agent Request Telegram approval proposal bound to material_summary_binding and owner_visual_evidence_binding",
            "place_order": "blocked from ordinary tool use; requires trusted Telegram approval plus secure_browser_execute_final_purchase live revalidation and exactly-once token consumption",
            "owner_checkout_review": "available only as owner-only Telegram delivery of complete checkout visual evidence tied to the same material_summary_binding; it does not expose sensitive evidence to Star",
        },
        "order_tracking": {
            "ledger": "profile-local SQLite",
            "ledger_path_hint": "SECURE_BROWSER_ORDER_LEDGER_PATH or ~/.hermes/profiles/star/secure-browser-order-ledger.sqlite3",
            "refresh_strategy": "Amazon Your Orders via secure browser first; read-only Gmail order/shipment emails fallback; carrier pages opportunistic and bot-blocking non-fatal",
            "notification_policy": "initial confirmation/ETA, material ETA or status changes, day-of/out-for-delivery/delivered; no repeated no-change spam",
        },
        "consumable_tracking": {
            "boundary": "Stable consumables are tracked separately from transient orders; explicit Joy statements may be durable, repeated purchases may suggest/tentatively learn, ambiguous one-offs stay tentative.",
        },
        "removed_legacy_helpers": ["secure_browser_inspect_product", "secure_browser_inspect_reviews", "secure_browser_inspect_cart", "secure_browser_add_to_cart"],
        "screenshot_dir": SCREENSHOT_DIR,
        "audit_log": AUDIT_LOG,
        "blocked_operations": sorted(UNSAFE_OPERATIONS | {"place_order"}),
        "secret_policy": "No raw CDP URLs, cookies, local storage, request headers, downloads, vault contents, passwords, passkeys, 2FA, CAPTCHA, full payment/account numbers, raw contact details, or full address details are returned as structured text. Ordinary page snapshots/queries redact sensitive visible-page text; sensitive visual evidence remains restricted or owner-only.",
    }
    return _json(status)



def secure_browser_navigate_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        url = str(args.get("url") or "").strip()
        new_page = bool(args.get("new_page", False))
        return _json(_navigate(url, new_page))
    except Exception as exc:
        return _json({"error": "NAVIGATE_FAILED", "message": str(exc)[:1000], "operation": "navigate"})


def secure_browser_page_snapshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_page_snapshot(int(args.get("max_text_chars") or MAX_TEXT_CHARS), int(args.get("max_interactive") or MAX_LINKS)))
    except Exception as exc:
        return _json({"error": "PAGE_SNAPSHOT_FAILED", "message": str(exc)[:1000], "operation": "page_snapshot"})


def secure_browser_query_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_query(str(args.get("expression") or "")))
    except Exception as exc:
        return _json({"error": "QUERY_FAILED", "message": str(exc)[:1000], "operation": "query"})


def secure_browser_screenshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_screenshot(bool(args.get("full_page", False))))
    except Exception as exc:
        return _json({"error": "SCREENSHOT_FAILED", "message": str(exc)[:1000], "operation": "screenshot"})


def secure_browser_visual_evidence_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        crops = args.get("crops") or []
        if not isinstance(crops, list):
            return _json({"error": "INVALID_CROPS", "message": "crops must be a list of crop spec objects", "operation": "visual_evidence"})
        return _json(_visual_evidence(bool(args.get("full_page", True)), bool(args.get("include_full_page", False)), crops))
    except Exception as exc:
        return _json({"error": "VISUAL_EVIDENCE_FAILED", "message": str(exc)[:1000], "operation": "visual_evidence"})


def secure_browser_click_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_click(str(args.get("selector") or ""), str(args.get("reason") or ""), str(args.get("approved_effect") or "browse")))
    except Exception as exc:
        return _json({"error": "CLICK_FAILED", "message": str(exc)[:1000], "operation": "click"})


def secure_browser_type_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_type(str(args.get("selector") or ""), str(args.get("text") or ""), str(args.get("reason") or ""), str(args.get("approved_effect") or "type")))
    except Exception as exc:
        return _json({"error": "TYPE_FAILED", "message": str(exc)[:1000], "operation": "type"})


def secure_browser_inspect_product_tool(args: dict[str, Any], **_kw: Any) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return _json({"error": "url is required"})
    try:
        return _json(_inspect_product(url))
    except Exception as exc:
        return _json({"error": "INSPECT_PRODUCT_FAILED", "message": str(exc)[:1000], "operation": "inspect_product"})


def secure_browser_inspect_reviews_tool(args: dict[str, Any], **_kw: Any) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return _json({"error": "url is required"})
    try:
        max_reviews = _bounded_max_reviews(args.get("max_reviews"))
        return _json(_inspect_reviews(url, max_reviews))
    except Exception as exc:
        return _json({"error": "INSPECT_REVIEWS_FAILED", "message": str(exc)[:1000], "operation": "inspect_reviews"})


def secure_browser_inspect_cart_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_inspect_cart())
    except Exception as exc:
        return _json({"error": "INSPECT_CART_FAILED", "message": str(exc)[:1000], "operation": "inspect_cart"})



def secure_browser_add_to_cart_tool(args: dict[str, Any], **_kw: Any) -> str:
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


def secure_browser_current_page_summary_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_current_page_summary())
    except Exception as exc:
        return _json({"error": "CURRENT_PAGE_SUMMARY_FAILED", "message": str(exc)[:1000], "operation": "current_page_summary"})


def secure_browser_owner_checkout_review_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_owner_checkout_review(bool(args.get("send_to_telegram", True)), bool(args.get("retain_local", False))))
    except Exception as exc:
        return _json({"error": "OWNER_CHECKOUT_REVIEW_FAILED", "message": str(exc)[:1000], "operation": "owner_checkout_review"})


def secure_browser_request_final_purchase_approval_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_request_final_purchase_approval(
            str(args.get("material_summary_binding") or ""),
            str(args.get("owner_visual_evidence_binding") or ""),
            str(args.get("owner_review_id") or ""),
            str(args.get("note") or ""),
        ))
    except Exception as exc:
        return _json({"error": "FINAL_PURCHASE_APPROVAL_REQUEST_FAILED", "message": str(exc)[:1000], "operation": "request_final_purchase_approval"})


def secure_browser_execute_final_purchase_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_execute_final_purchase(
            str(args.get("approval_request_id") or ""),
            str(args.get("material_summary_binding") or ""),
            str(args.get("owner_visual_evidence_binding") or ""),
        ))
    except Exception as exc:
        return _json({"error": "FINAL_PURCHASE_EXECUTION_FAILED", "message": str(exc)[:1000], "operation": "execute_final_purchase"})


def secure_browser_order_list_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_list_orders(bool(args.get("include_archived", False)), str(args.get("status") or "")))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_LIST_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_list"})


def secure_browser_order_read_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_read_order(str(args.get("handle") or args.get("order_handle") or "")))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_READ_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_read"})


def secure_browser_order_upsert_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_upsert_order_entry(args))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_UPSERT_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_upsert"})


def secure_browser_order_close_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_close_order(
            str(args.get("handle") or args.get("order_handle") or ""),
            str(args.get("status") or "delivered"),
            bool(args.get("archive", True)),
            args.get("safe_delivery_facts"),
            str(args.get("notes") or ""),
        ))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_CLOSE_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_close"})


def secure_browser_order_notification_preview_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_preview_order_update(args))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_NOTIFICATION_PREVIEW_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_notification_preview"})


def secure_browser_order_mark_notified_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_mark_order_notified(str(args.get("handle") or args.get("order_handle") or ""), str(args.get("event_type") or "")))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_MARK_NOTIFIED_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_mark_notified"})


def secure_browser_order_refresh_plan_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_refresh_plan())
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_REFRESH_PLAN_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_refresh_plan"})


def secure_browser_order_refresh_run_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_refresh_due_orders(
            send_notifications=bool(args.get("send_notifications", True)),
            limit=int(args.get("limit") or 20),
        ))
    except Exception as exc:
        return _json({"error": "SECURE_BROWSER_ORDER_REFRESH_RUN_FAILED", "message": str(exc)[:1000], "operation": "shopping_order_refresh_run"})


def secure_browser_consumable_list_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_list_consumables(bool(args.get("include_archived", False))))
    except Exception as exc:
        return _json({"error": "SHOPPING_CONSUMABLE_LIST_FAILED", "message": str(exc)[:1000], "operation": "shopping_consumable_list"})


def secure_browser_consumable_upsert_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_upsert_consumable(args))
    except Exception as exc:
        return _json({"error": "SHOPPING_CONSUMABLE_UPSERT_FAILED", "message": str(exc)[:1000], "operation": "shopping_consumable_upsert"})


def secure_browser_consumable_suggest_from_order_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_suggest_consumable_from_order(str(args.get("handle") or args.get("order_handle") or "")))
    except Exception as exc:
        return _json({"error": "SHOPPING_CONSUMABLE_SUGGEST_FAILED", "message": str(exc)[:1000], "operation": "shopping_consumable_suggest_from_order"})


def secure_browser_guardrail_check_tool(args: dict[str, Any], **_kw: Any) -> str:
    operation = str(args.get("operation") or "").strip()
    if not operation:
        return _json({"error": "operation is required"})
    return _json(_reject_unsafe_operation(operation))


STATUS_SCHEMA = {
    "name": "secure_browser_status",
    "description": "Show the secure browser bridge status and safety boundary.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

NAVIGATE_SCHEMA = {
    "name": "secure_browser_navigate",
    "description": "Navigate the persistent Star secure browser to an http(s) URL. Allows ordinary shopping and account research pages such as Amazon order history/Buy Again, while blocking checkout/final purchase, payment/address/wallet edits, login, passkeys, 2FA/CAPTCHA, and other credential/security challenge targets. Logs sanitized navigation metadata in the secure browser audit log.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL to open in the secure browser"},
            "new_page": {"type": "boolean", "description": "Open in a fresh page/tab instead of reusing the current page", "default": False},
        },
        "required": ["url"],
    },
}

PAGE_SNAPSHOT_SCHEMA = {
    "name": "secure_browser_page_snapshot",
    "description": "Inspect the current secure browser page as sanitized visible text plus a bounded list of interactive elements and suggested CSS selectors, including ordinary shopping, account research pages such as order history. Redacts emails, phone numbers, street/zip address details, long payment/account numbers, and order references; does not return raw HTML, cookies, local storage, request headers, screenshots, or CDP handles.",
    "parameters": {
        "type": "object",
        "properties": {
            "max_text_chars": {"type": "integer", "description": "Maximum visible text characters to return", "minimum": 500, "maximum": MAX_TEXT_CHARS, "default": MAX_TEXT_CHARS},
            "max_interactive": {"type": "integer", "description": "Maximum interactive elements/selectors to return", "minimum": 0, "maximum": MAX_LINKS, "default": MAX_LINKS},
        },
        "required": [],
    },
}

QUERY_SCHEMA = {
    "name": "secure_browser_query",
    "description": "Evaluate a limited read-only JavaScript expression on the current shopping page for structured visible-page facts, including ordinary shopping, account research pages such as order history. Runtime guardrails reject obvious mutation, network, storage, cookie, and navigation tokens, and returned string values are sanitized. On checkout/order-review pages this tool does not return the raw query result; it returns only the sanitized checkout-prep summary and non-secret controls, while complete checkout evidence remains Joy-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Read-only JavaScript expression, e.g. document.title or Array.from(document.querySelectorAll('button')).map(b => b.innerText)"},
        },
        "required": ["expression"],
    },
}

SCREENSHOT_SCHEMA = {
    "name": "secure_browser_screenshot",
    "description": "Capture the current visible persistent secure browser page as a local PNG media artifact for delivery. Refuses obvious login, account, payment, address, order, passkey, CAPTCHA, and verification URLs; Amazon checkout-prep pages are captured only with browser-side redaction and viewport bounds. Logs the high-level capture in the audit log. Returns only a local file path/media handle plus sanitized page metadata, not raw CDP data, cookies, storage, headers, or secrets.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when Chromium supports it. Redacted checkout-prep evidence is always downgraded to viewport capture.", "default": False},
        },
        "required": [],
    },
}

VISUAL_EVIDENCE_SCHEMA = {
    "name": "secure_browser_visual_evidence",
    "description": "Capture retailer-agnostic visual evidence from the current secure browser page: a local PNG screenshot, sanitized suggested regions, and optional focused crops. Crops may reference a suggested region_id/category/text_anchor, a safe CSS selector, or an explicit bounding rect. Amazon checkout-prep pages are captured only with redaction and viewport bounds; login/account/payment/address/security pages remain Joy-only. Returns PNG paths/media handles plus sanitized metadata, never raw DOM, cookies, storage, request headers, credentials, CDP endpoints, payment/address secrets, or browser internals.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when safe and supported. Redacted checkout-prep evidence is always downgraded to viewport capture.", "default": True},
            "include_full_page": {"type": "boolean", "description": "Include a MEDIA handle for the full screenshot in addition to the local path. Crop media handles are always returned.", "default": False},
            "crops": {
                "type": "array",
                "description": "Optional focused crop requests. First call with no crops to inspect suggested_regions, then request crops by region_id/category/text_anchor/selector/rect. Limited to six crops.",
                "maxItems": MAX_VISUAL_CROPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short artifact label"},
                        "region_id": {"type": "string", "description": "Suggested region_id returned by this tool"},
                        "category": {"type": "string", "description": "Suggested region category such as product_title, price, buy_box, cart_item, checkout_total, or order_summary"},
                        "text_anchor": {"type": "string", "description": "Sanitized text fragment to match within suggested regions"},
                        "selector": {"type": "string", "description": "Safe CSS selector for a visible page element"},
                        "rect": {"type": "object", "description": "Explicit CSS-pixel rect with x, y, width, height"},
                        "padding": {"type": "integer", "description": "Crop padding in CSS pixels, capped internally", "minimum": 0, "maximum": MAX_CROP_PADDING, "default": 24},
                        "highlight": {"type": "boolean", "description": "Draw a small red border around the requested crop area", "default": True},
                    },
                },
                "default": [],
            },
        },
        "required": [],
    },
}

CLICK_SCHEMA = {
    "name": "secure_browser_click",
    "description": "Click a visible element in the persistent secure browser by CSS selector. Use for browsing, selecting variants/options, applying visible coupons, explicitly approved add-to-cart/removal, and supervised checkout-prep controls. Checkout prep requires an explicit checkout approved_effect such as checkout_prep, select_shipping_option, select_delivery_option, apply_checkout_option, fix_purchase_mode, or cart_line_adjustment plus Joy live supervision; it returns a refreshed sanitized order-review summary/material_summary_binding and refuses final purchase controls. Never use for Buy Now, Place Order, account/payment/address edits, login, passkeys, 2FA, or CAPTCHA.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector from secure_browser_page_snapshot or a carefully derived selector"},
            "approved_effect": {"type": "string", "description": "Expected effect of the click", "enum": list(APPROVED_CLICK_EFFECTS), "default": "browse"},
            "reason": {"type": "string", "description": "Short human-readable reason/approval reference for audit, required for add_to_cart and remove_from_cart"},
        },
        "required": ["selector", "approved_effect", "reason"],
    },
}

TYPE_SCHEMA = {
    "name": "secure_browser_type",
    "description": "Type bounded non-sensitive text into a visible field in the persistent secure browser. Intended for search boxes, quantity fields, and similar shopping UI. Refuses fields that look like password, passkey, OTP, card, contact, address, or payment inputs; Joy must take over those.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector for the input/select/textarea"},
            "text": {"type": "string", "description": "Non-sensitive text to type"},
            "reason": {"type": "string", "description": "Short human-readable reason for audit"},
            "approved_effect": {"type": "string", "description": "Expected effect of the typing; checkout-prep effects require Joy live supervision and return a refreshed sanitized checkout summary", "enum": list(APPROVED_TYPE_EFFECTS), "default": "type"},
        },
        "required": ["selector", "text", "reason", "approved_effect"],
    },
}

INSPECT_PRODUCT_SCHEMA = {
    "name": "secure_browser_inspect_product",
    "description": "Read-only Amazon product inspection through the Kasm secure browser session. Returns product title, logged-in price, delivery/Prime text, availability, seller, ship-from text, visible condition text when Amazon exposes it, and public Amazon product image URLs when visible. Does not expose cookies, local storage, request headers, raw CDP, screenshots, or browser handles.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTPS Amazon product URL to inspect"},
        },
        "required": ["url"],
    },
}

INSPECT_REVIEWS_SCHEMA = {
    "name": "secure_browser_inspect_reviews",
    "description": "Read-only Amazon review inspection through the Kasm secure browser session. Returns only bounded public review metadata and excerpts visible from the product/review page; max_reviews is capped at 10. Does not expose cookies, local storage, request headers, raw CDP, screenshots, or browser handles.",
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
    "name": "secure_browser_inspect_cart",
    "description": "Read-only Amazon cart inspection through the Kasm secure browser session. Returns cart line item names, quantities, prices, subtotal, and delivery estimate when visible. Does not add, remove, update, checkout, or expose secrets.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


ADD_TO_CART_SCHEMA = {
    "name": "secure_browser_add_to_cart",
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
    "name": "secure_browser_current_page_summary",
    "description": "Read-only summary of the current Kasm secure browser page using safe structured fields only. Amazon thank-you/order-confirmation and Your Orders pages are labeled as post-purchase confirmation/order-verification context, not checkout-prep/final-purchase approval state.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

OWNER_CHECKOUT_REVIEW_SCHEMA = {
    "name": "secure_browser_owner_checkout_review",
    "description": "Send complete sensitive checkout/order-review or post-purchase confirmation/order-verification visual evidence directly to Joy's configured Telegram destination for owner-only review. For pre-purchase checkout, intended for verification of address, payment, item, delivery, tax/total, discounts, and final controls. For post-purchase pages, intended for thank-you/confirmation and Your Orders delivery proof. Returns only a redacted acknowledgement, bindings, and sanitized summary to Star; it never returns image paths, MEDIA handles, raw DOM, cookies, storage, request headers, CDP endpoints, credentials, passkeys, 2FA/CAPTCHA data, raw order numbers, or structured address/payment details. Final Place Order remains blocked pending trusted approval before purchase.",
    "parameters": {
        "type": "object",
        "properties": {
            "send_to_telegram": {"type": "boolean", "description": "Must remain true; sensitive evidence is delivered directly to Joy instead of returned to Star", "default": True},
            "retain_local": {"type": "boolean", "description": "Retain temporary sensitive PNGs locally after Telegram delivery for operator debugging; default false deletes local files after successful send", "default": False},
        },
        "required": [],
    },
}


REQUEST_FINAL_PURCHASE_APPROVAL_SCHEMA = {
    "name": "secure_browser_request_final_purchase_approval",
    "description": "Request Joy's trusted Telegram-native final purchase approval after owner-only checkout review. Re-reads the live checkout page, verifies material_summary_binding still matches, then creates an Agent Request proposal with actionable Telegram buttons. It does not click Place Order and does not expose raw checkout evidence, cookies, storage, CDP handles, or full payment/address details.",
    "parameters": {
        "type": "object",
        "properties": {
            "material_summary_binding": {"type": "string", "description": "Current checkout material_summary_binding from secure_browser_owner_checkout_review/current checkout summary"},
            "owner_visual_evidence_binding": {"type": "string", "description": "Owner-only visual evidence binding returned by secure_browser_owner_checkout_review"},
            "owner_review_id": {"type": "string", "description": "Owner checkout review id returned by secure_browser_owner_checkout_review"},
            "note": {"type": "string", "description": "Optional concise Star note for Talon/Joy, without secrets"},
        },
        "required": ["material_summary_binding", "owner_visual_evidence_binding"],
    },
}

EXECUTE_FINAL_PURCHASE_SCHEMA = {
    "name": "secure_browser_execute_final_purchase",
    "description": "Trusted final purchase executor. Use only after Joy approved the bound Agent Request proposal. It verifies the current Agent Request approval, refuses reused approvals, re-reads the live checkout material summary, refuses if anything material changed or sensitive verification is visible, clicks exactly one final purchase control, then attempts owner-only post-purchase proof capture from the Amazon confirmation page. Not for ordinary Star browsing.",
    "parameters": {
        "type": "object",
        "properties": {
            "approval_request_id": {"type": "string", "description": "Agent Request id whose proposal Joy approved through the trusted Telegram path"},
            "material_summary_binding": {"type": "string", "description": "Approved material_summary_binding"},
            "owner_visual_evidence_binding": {"type": "string", "description": "Approved owner_visual_evidence_binding"},
        },
        "required": ["approval_request_id", "material_summary_binding", "owner_visual_evidence_binding"],
    },
}

ORDER_LIST_SCHEMA = {
    "name": "secure_browser_order_list",
    "description": "List active/in-flight Star secure browser orders from the safe profile-local order ledger. Returns only safe handles, item nicknames/categories, retailer, coarse ETA/status, safe evidence bindings, and sanitized delivery facts; never raw order numbers, address/payment data, cookies, DOM, or owner-only screenshots.",
    "parameters": {
        "type": "object",
        "properties": {
            "include_archived": {"type": "boolean", "description": "Include closed/archived order rows", "default": False},
            "status": {"type": "string", "description": "Optional status filter such as confirmed, shipped, out_for_delivery, delivered"},
        },
        "required": [],
    },
}

ORDER_READ_SCHEMA = {
    "name": "secure_browser_order_read",
    "description": "Read a safe order-ledger entry by human-friendly handle/nickname. The handle must not be a raw order number or payment/address identifier.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string", "description": "Safe order handle/nickname"}}, "required": ["handle"]},
}

ORDER_UPSERT_SCHEMA = {
    "name": "secure_browser_order_upsert",
    "description": "Add or update a safe Star secure-browser-order ledger entry from trusted final-purchase/post-purchase proof data or sanitized refresh facts. Use safe handles and item nicknames only; raw order numbers, full addresses, payment details, raw DOM, cookies, and screenshots are not accepted or persisted.",
    "parameters": {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "Safe human-friendly order handle/nickname, not a raw order number"},
            "retailer": {"type": "string", "description": "Retailer, e.g. amazon"},
            "item_nickname": {"type": "string", "description": "Safe item nickname/category text"},
            "item_category": {"type": "string", "description": "Safe category such as coffee filters or pipe screens"},
            "status": {"type": "string", "description": "pending_confirmation, confirmed, ordered, processing, shipped, out_for_delivery, delivered, cancelled, closed, or archived"},
            "eta_window": {"type": "string", "description": "Coarse delivery day/window only; no address or precise sensitive data"},
            "safe_delivery_facts": {"type": "array", "items": {"type": "string"}, "description": "Sanitized delivery facts"},
            "evidence_bindings": {"type": "array", "items": {"type": "string"}, "description": "Safe evidence binding ids/hashes"},
            "source_refs": {"type": "array", "items": {"type": "string"}, "description": "Safe source labels such as owner_post_purchase_proof or gmail_order_email"},
            "refresh_sources": {"type": "array", "items": {"type": "string"}, "description": "Preferred refresh sources"},
            "notes": {"type": "string", "description": "Short sanitized note"},
        },
        "required": ["handle", "item_nickname"],
    },
}

ORDER_CLOSE_SCHEMA = {
    "name": "secure_browser_order_close",
    "description": "Mark a safe secure-browser-order ledger entry delivered/closed/archived. This does not modify, cancel, return, reorder, or contact the retailer/carrier.",
    "parameters": {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "Safe order handle/nickname"},
            "status": {"type": "string", "description": "Closed status; defaults to delivered"},
            "archive": {"type": "boolean", "description": "Archive/quiet the order after closing", "default": True},
            "safe_delivery_facts": {"type": "array", "items": {"type": "string"}, "description": "Optional sanitized delivery facts"},
            "notes": {"type": "string", "description": "Optional sanitized closeout note"},
        },
        "required": ["handle"],
    },
}

ORDER_NOTIFICATION_PREVIEW_SCHEMA = {
    "name": "secure_browser_order_notification_preview",
    "description": "Preview whether a proposed sanitized order status/ETA update is Joy-notifiable under the noise-limited policy. Does not send notifications.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "status": {"type": "string"}, "eta_window": {"type": "string"}, "safe_delivery_facts": {"type": "array", "items": {"type": "string"}}, "event_type": {"type": "string"}}, "required": ["handle"]},
}

ORDER_MARK_NOTIFIED_SCHEMA = {
    "name": "secure_browser_order_mark_notified",
    "description": "Record that Joy was notified for a material order event so scheduled refreshes do not spam repeated no-change updates. Does not send notifications.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "event_type": {"type": "string", "description": "initial_confirmation, eta_changed, status_changed, out_for_delivery, or delivered"}}, "required": ["handle", "event_type"]},
}

ORDER_REFRESH_PLAN_SCHEMA = {
    "name": "secure_browser_order_refresh_plan",
    "description": "Return active orders due for scheduled refresh and the safe refresh strategy: Amazon Your Orders via secure browser first, Gmail order/shipment email fallback, carrier pages only opportunistically; UPS bot blocking is non-fatal. Does not browse or send notifications.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

ORDER_REFRESH_RUN_SCHEMA = {
    "name": "secure_browser_order_refresh_run",
    "description": "Run the safe scheduled Star order refresh loop for due active orders: refresh sanitized status/ETA from Amazon Your Orders first, read-only Gmail snippets as fallback, carrier pages only opportunistically, update the ledger, and send Joy a Telegram notification only when secure_browser_order_notification_preview says the event is material. Does not place, cancel, reorder, return, or modify orders.",
    "parameters": {
        "type": "object",
        "properties": {
            "send_notifications": {"type": "boolean", "description": "Send Joy Telegram notifications for material events; defaults true", "default": True},
            "limit": {"type": "integer", "description": "Maximum due orders to refresh this run, 1-50", "default": 20},
        },
        "required": [],
    },
}

CONSUMABLE_LIST_SCHEMA = {
    "name": "secure_browser_consumable_list",
    "description": "List stable/tentative consumable items separately from transient order state. Returns safe item nicknames/categories, confidence/source, and last safe order handle only.",
    "parameters": {"type": "object", "properties": {"include_archived": {"type": "boolean", "default": False}}, "required": []},
}

CONSUMABLE_UPSERT_SCHEMA = {
    "name": "secure_browser_consumable_upsert",
    "description": "Create or update a safe consumable item. Use confidence='explicit' only for Joy's explicit durable statements; repeated purchases can be repeated_purchase; ambiguous one-offs should remain tentative/suggested.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "item_nickname": {"type": "string"}, "item_category": {"type": "string"}, "retailer": {"type": "string"}, "confidence": {"type": "string"}, "source": {"type": "string"}, "evidence_count": {"type": "integer"}, "last_order_handle": {"type": "string"}, "notes": {"type": "string"}, "archived": {"type": "boolean"}}, "required": ["item_nickname", "confidence"]},
}

CONSUMABLE_SUGGEST_FROM_ORDER_SCHEMA = {
    "name": "secure_browser_consumable_suggest_from_order",
    "description": "Create a tentative consumable suggestion from a safe order handle without promoting it to durable memory. Joy confirmation or repeated purchases are required before treating it as stable.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string", "description": "Safe order handle/nickname"}}, "required": ["handle"]},
}

GUARDRAIL_SCHEMA = {
    "name": "secure_browser_guardrail_check",
    "description": "Check whether a secure-browser operation is allowed. Ordinary trusted-assistant shopping, account research browsing is allowed with sanitized outputs. Checkout now means supervised checkout-prep only; final place_order remains blocked pending trusted Telegram approval bound to a material order-summary hash. Raw session, credential, payment/address edit, and secret operations are rejected.",
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
    handler=secure_browser_status_tool,
    check_fn=_check_secure_browser,
    description=STATUS_SCHEMA["description"],
    emoji="🛡️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=NAVIGATE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=NAVIGATE_SCHEMA,
    handler=secure_browser_navigate_tool,
    check_fn=_check_secure_browser,
    description=NAVIGATE_SCHEMA["description"],
    emoji="🧭",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=PAGE_SNAPSHOT_SCHEMA["name"],
    toolset=TOOLSET,
    schema=PAGE_SNAPSHOT_SCHEMA,
    handler=secure_browser_page_snapshot_tool,
    check_fn=_check_secure_browser,
    description=PAGE_SNAPSHOT_SCHEMA["description"],
    emoji="📄",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=QUERY_SCHEMA["name"],
    toolset=TOOLSET,
    schema=QUERY_SCHEMA,
    handler=secure_browser_query_tool,
    check_fn=_check_secure_browser,
    description=QUERY_SCHEMA["description"],
    emoji="🔎",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=SCREENSHOT_SCHEMA["name"],
    toolset=TOOLSET,
    schema=SCREENSHOT_SCHEMA,
    handler=secure_browser_screenshot_tool,
    check_fn=_check_secure_browser,
    description=SCREENSHOT_SCHEMA["description"],
    emoji="📸",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=VISUAL_EVIDENCE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=VISUAL_EVIDENCE_SCHEMA,
    handler=secure_browser_visual_evidence_tool,
    check_fn=_check_secure_browser,
    description=VISUAL_EVIDENCE_SCHEMA["description"],
    emoji="🖼️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=CLICK_SCHEMA["name"],
    toolset=TOOLSET,
    schema=CLICK_SCHEMA,
    handler=secure_browser_click_tool,
    check_fn=_check_secure_browser,
    description=CLICK_SCHEMA["description"],
    emoji="👆",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=TYPE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=TYPE_SCHEMA,
    handler=secure_browser_type_tool,
    check_fn=_check_secure_browser,
    description=TYPE_SCHEMA["description"],
    emoji="⌨️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=CURRENT_PAGE_SUMMARY_SCHEMA["name"],
    toolset=TOOLSET,
    schema=CURRENT_PAGE_SUMMARY_SCHEMA,
    handler=secure_browser_current_page_summary_tool,
    check_fn=_check_secure_browser,
    description=CURRENT_PAGE_SUMMARY_SCHEMA["description"],
    emoji="📄",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=OWNER_CHECKOUT_REVIEW_SCHEMA["name"],
    toolset=TOOLSET,
    schema=OWNER_CHECKOUT_REVIEW_SCHEMA,
    handler=secure_browser_owner_checkout_review_tool,
    check_fn=_check_secure_browser,
    description=OWNER_CHECKOUT_REVIEW_SCHEMA["description"],
    emoji="🔐",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=REQUEST_FINAL_PURCHASE_APPROVAL_SCHEMA["name"],
    toolset=TOOLSET,
    schema=REQUEST_FINAL_PURCHASE_APPROVAL_SCHEMA,
    handler=secure_browser_request_final_purchase_approval_tool,
    check_fn=_check_secure_browser,
    description=REQUEST_FINAL_PURCHASE_APPROVAL_SCHEMA["description"],
    emoji="✅",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=EXECUTE_FINAL_PURCHASE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=EXECUTE_FINAL_PURCHASE_SCHEMA,
    handler=secure_browser_execute_final_purchase_tool,
    check_fn=_check_secure_browser,
    description=EXECUTE_FINAL_PURCHASE_SCHEMA["description"],
    emoji="🛒",
    max_result_size_chars=MAX_RESULT_CHARS,
)
for _schema, _handler, _emoji in [
    (ORDER_LIST_SCHEMA, secure_browser_order_list_tool, "📦"),
    (ORDER_READ_SCHEMA, secure_browser_order_read_tool, "🔎"),
    (ORDER_UPSERT_SCHEMA, secure_browser_order_upsert_tool, "🧾"),
    (ORDER_CLOSE_SCHEMA, secure_browser_order_close_tool, "✅"),
    (ORDER_NOTIFICATION_PREVIEW_SCHEMA, secure_browser_order_notification_preview_tool, "🔕"),
    (ORDER_MARK_NOTIFIED_SCHEMA, secure_browser_order_mark_notified_tool, "📌"),
    (ORDER_REFRESH_PLAN_SCHEMA, secure_browser_order_refresh_plan_tool, "🔄"),
    (ORDER_REFRESH_RUN_SCHEMA, secure_browser_order_refresh_run_tool, "⏰"),
    (CONSUMABLE_LIST_SCHEMA, secure_browser_consumable_list_tool, "☕"),
    (CONSUMABLE_UPSERT_SCHEMA, secure_browser_consumable_upsert_tool, "📝"),
    (CONSUMABLE_SUGGEST_FROM_ORDER_SCHEMA, secure_browser_consumable_suggest_from_order_tool, "🌱"),
]:
    registry.register(
        name=_schema["name"],
        toolset=TOOLSET,
        schema=_schema,
        handler=_handler,
        check_fn=_check_secure_browser,
        description=_schema["description"],
        emoji=_emoji,
        max_result_size_chars=MAX_RESULT_CHARS,
    )

registry.register(
    name=GUARDRAIL_SCHEMA["name"],
    toolset=TOOLSET,
    schema=GUARDRAIL_SCHEMA,
    handler=secure_browser_guardrail_check_tool,
    check_fn=_check_secure_browser,
    description=GUARDRAIL_SCHEMA["description"],
    emoji="🚫",
    max_result_size_chars=MAX_RESULT_CHARS,
)


if __name__ == "__main__":
    assert _reject_unsafe_operation("add_to_cart")["allowed"] is True
    assert _reject_unsafe_operation("order_history")["boundary"] == "trusted_assistant_browsing_sanitized"
    assert _reject_unsafe_operation("checkout")["allowed"] is True
    assert _reject_unsafe_operation("checkout")["boundary"] == "checkout_prep_only"
    assert _reject_unsafe_operation("place_order")["allowed"] is False
    assert _safe_browser_url("https://www.amazon.com/dp/B01J01XGPK")
    assert _safe_browser_url("https://www.amazon.com/gp/your-account/order-history?search=Kalita")
    assert _safe_browser_url("https://www.amazon.com/gp/buyagain")
    try:
        _safe_browser_url("https://www.amazon.com/checkout")
        raise AssertionError("checkout URL should be blocked")
    except ValueError:
        pass
    try:
        _safe_browser_url("https://www.amazon.com/cpe/yourpayments/wallet")
        raise AssertionError("payment/wallet URL should be blocked")
    except ValueError:
        pass
    try:
        _safe_read_only_query("document.querySelector('button').click()")
        raise AssertionError("mutating query should be blocked")
    except ValueError:
        pass
    assert _reject_unsafe_operation("local_storage")["allowed"] is False
    assert _reject_unsafe_operation("screenshot")["allowed"] is True
    assert _reject_unsafe_operation("screenshot_sensitive_page")["allowed"] is False
    amazon_checkout_policy = _screenshot_policy("https://www.amazon.com/gp/buy/spc/handlers/display.html", "Review your order")
    assert amazon_checkout_policy["mode"] == "checkout_prep_redacted"
    assert amazon_checkout_policy["redaction_required"] is True
    assert _is_amazon_checkoutish_page("https://www.amazon.com/gp/buy/spc/handlers/display.html", "Review your order") is True
    assert _is_amazon_checkoutish_page("https://www.amazon.com/product-reviews/B01J01XGPK", "Customer reviews") is False
    assert _is_checkoutish_page("https://shop.example.test/checkout/payment", "Payment") is True
    try:
        _screenshot_policy("https://shop.example.test/checkout/payment", "Payment")
        raise AssertionError("non-Amazon checkout/payment screenshot should be blocked")
    except ValueError:
        pass
    try:
        _screenshot_policy("https://www.amazon.com/ap/signin", "Amazon Sign In")
        raise AssertionError("login screenshot should be blocked")
    except ValueError:
        pass
    assert _redaction_hash({"redaction_rects_sha256_material": "[]"}) == hashlib.sha256(b"[]").hexdigest()
    sensitive_checkout_blob = {
        "delivery": ["Arrives Monday at 123 Example Street Apt 4, Springfield, IL 62704, call 312-555-1212"],
        "items": [{"title": "Widget", "seller": "Example Seller", "shipper": "Amazon", "notes": "Ship to 123 Example Street"}],
        "payment_method_label_last_four_only": "Visa 4111 1111 1111 1234 CVV 987 account number 1234567890",
        "shipping_destination_label_or_city_state": "Joy, 123 Example Street Apt 4, Springfield, IL 62704",
        "nested": [["contact joy@example.test"], {"phone": "312-555-1212"}],
    }
    sanitized_checkout_blob = _sanitize_checkout_value(sensitive_checkout_blob)
    sanitized_json = json.dumps(sanitized_checkout_blob).lower()
    assert "example street" not in sanitized_json
    assert "62704" not in sanitized_json
    assert "312-555-1212" not in sanitized_json
    assert "joy@example.test" not in sanitized_json
    assert "1111 1111" not in sanitized_json
    assert "cvv 987" not in sanitized_json
    assert sanitized_checkout_blob["payment_method_label_last_four_only"] == "Visa ending in 1234"
    assert sanitized_checkout_blob["shipping_destination_label_or_city_state"] == "Springfield, IL"
    sanitized_order_history = _sanitize_shopping_value({"text": "Order #111-2222222-3333333 shipped to 123 Example Street Apt 4, Springfield, IL 62704 phone 312-555-1212 paid with 4111 1111 1111 1234"})
    sanitized_order_json = json.dumps(sanitized_order_history, ensure_ascii=False)
    assert "111-2222222-3333333" not in sanitized_order_json
    assert "Example Street" not in sanitized_order_json
    assert "62704" not in sanitized_order_json
    assert "312-555-1212" not in sanitized_order_json
    assert "4111" not in sanitized_order_json
    assert "checkout_prep" in APPROVED_CLICK_EFFECTS
    synthetic_checkout = {
        "items": ["Widget Qty: 1 Sold by Example Seller Ship to 123 Example Street Apt 4, Sampletown, NY 12345"],
        "delivery": ["Delivery Monday to 123 Example Street, Sampletown, NY 12345 phone 212-555-0100"],
        "shipping_destination_label_or_city_state": ["Ship to Example Recipient, 123 Example Street Apt 4, Sampletown, NY 12345"],
        "payment_method_label_last_four_only": ["Visa 4111 1111 1111 1234 ending in 1234 billing to 123 Example Street"],
        "nested": {"contact_blob": "email shopper@example.invalid phone 212-555-0100"},
    }
    sanitized_checkout = _sanitize_checkout_value(synthetic_checkout)
    flattened_checkout = json.dumps(sanitized_checkout, ensure_ascii=False)
    assert "Example Street" not in flattened_checkout
    assert "12345" not in flattened_checkout
    assert "212-555-0100" not in flattened_checkout
    assert "shopper@example.invalid" not in flattened_checkout
    assert "4111" not in flattened_checkout
    assert sanitized_checkout["shipping_destination_label_or_city_state"] == ["Sampletown, NY"]
    assert sanitized_checkout["payment_method_label_last_four_only"] == ["Visa ending in 1234"]
    mixed_checkout_summary = _sanitize_checkout_summary(
        {
            "items": [
                "Widget Qty: 1 Sold by Example Seller",
                "Gift card, promotion code, or voucher Change Return policy",
                "Order total $19.99",
            ],
            "delivery": [
                "Delivery Monday to 123 Example Street, Sampletown, NY 12345",
                "Payment method Visa ending in 1234 Change",
                "Return policy applies",
            ],
            "shipping_destination_label_or_city_state": [],
            "payment_method_label_last_four_only": [
                "Ship to Example Recipient Payment method Visa ending in 1234 Order total $19.99",
            ],
        },
        {"final_purchase_controls_visible": ["Place Order"], "checkout_prep_state": "checkout_prep_visible"},
    )
    mixed_json = json.dumps(mixed_checkout_summary, ensure_ascii=False)
    assert mixed_checkout_summary["items"] == ["Widget Qty: 1 Sold by Example Seller"]
    assert mixed_checkout_summary["delivery"] == ["[checkout detail redacted]"]
    assert mixed_checkout_summary["shipping_destination_city_state_or_label"] == ["Sampletown, NY"]
    assert mixed_checkout_summary["payment_method_label_last_four_only"] == ["Visa ending in 1234"]
    assert mixed_checkout_summary["blocked_metadata"]["final_purchase_controls_visible"] == ["Place Order"]
    assert "Gift card" not in mixed_json
    assert "Change" not in mixed_json
    assert "Return policy" not in mixed_json
    assert "Order total" not in mixed_json
    assert "Example Street" not in mixed_json
    generic_checkout_review = _sanitize_checkout_summary(
        {
            "items": ["Pipe screens Qty: 1 Sold by Gray Caravan"],
            "delivery": ["Arrives Monday to 123 Example Street Apt 4, Sampletown, NY 12345"],
            "shipping_destination_label_or_city_state": ["Ship to Joy, 123 Example Street Apt 4, Sampletown, NY 12345"],
            "payment_method_label_last_four_only": ["Visa 4111 1111 1111 1234 ending in 1234"],
        },
        {"final_purchase_controls_visible": ["Place Order"], "checkout_prep_state": "checkout_prep_visible"},
        {
            "safe_controls": [
                {
                    "selector": "#sns-item-v2-checkbox-0",
                    "label": "Subscribe & Save checkbox",
                    "role": "checkbox",
                    "tag": "input",
                    "input_type": "checkbox",
                    "region": "purchase_mode",
                    "approved_effect_hints": ["fix_purchase_mode"],
                    "checked": False,
                    "disabled": False,
                    "viewport_rect": {"x": 10, "y": 20, "width": 15, "height": 15},
                },
                {
                    "selector": "[data-secure-browser-checkout-control=\"sb-checkout-2\"]",
                    "label": "Paying with Visa ending in 5252 plus gift card balance Change",
                    "role": "link",
                    "tag": "A",
                    "input_type": "",
                    "region": "payment_gift_card",
                    "approved_effect_hints": ["apply_checkout_option"],
                    "checked": False,
                    "disabled": False,
                    "viewport_rect": {"x": 20, "y": 60, "width": 180, "height": 20},
                },
            ],
        },
    )

    class _FakeBrowser:
        port = 9222

    original_with_browser = _with_browser
    original_owned_page_info = _owned_page_info
    original_attach = _attach
    original_evaluate = _evaluate
    original_checkout_summary_from_browser = _checkout_summary_from_browser
    try:
        globals()["_with_browser"] = lambda fn: fn(_FakeBrowser())
        globals()["_owned_page_info"] = lambda _browser: {"id": "checkout-target", "url": "https://www.amazon.com/gp/buy/spc/handlers/display.html", "title": "Review your order"}
        globals()["_attach"] = lambda _browser, _target_id: "checkout-session"

        def _fake_evaluate(_browser, _session_id, expression):
            if expression == "location.href":
                return "https://www.amazon.com/gp/buy/spc/handlers/display.html?hasWorkingJavascript=1"
            if expression == "document.title":
                return "Review your order"
            raise AssertionError("checkout query should not evaluate the requested JavaScript expression")

        globals()["_evaluate"] = _fake_evaluate
        globals()["_checkout_summary_from_browser"] = lambda _browser, _session_id: generic_checkout_review
        query_result = _query("Array.from(document.querySelectorAll('button,input')).map((node) => node.textContent || node.value || node.getAttribute('aria-label'))")
        payment_query_result = _query("Find payment and gift card checkout controls")
    finally:
        globals()["_with_browser"] = original_with_browser
        globals()["_owned_page_info"] = original_owned_page_info
        globals()["_attach"] = original_attach
        globals()["_evaluate"] = original_evaluate
        globals()["_checkout_summary_from_browser"] = original_checkout_summary_from_browser

    query_json = json.dumps(query_result, ensure_ascii=False)
    assert query_result["operation"] == "checkout_query_summary"
    assert query_result["status"] == "ok"
    assert "value" not in query_result
    assert query_result["requested_expression_sha256"]
    assert query_result["checkout_prep_controls"][0]["selector"] == "#sns-item-v2-checkbox-0"
    assert query_result["checkout_prep_controls"][0]["checked"] is False
    assert query_result["checkout_prep_control_categories"]["regions"]["payment_gift_card"] == 1
    assert payment_query_result["checkout_prep_controls_filter"]["requested_region"] == "payment_gift_card"
    assert payment_query_result["checkout_prep_controls_filter"]["full_safe_control_count"] == 2
    assert payment_query_result["blocked_metadata"]["checkout_prep_safe_control_count_before_filter"] == 2
    assert len(payment_query_result["checkout_prep_controls"]) == 1
    assert payment_query_result["checkout_prep_controls"][0]["region"] == "payment_gift_card"
    assert payment_query_result["checkout_prep_controls"][0]["approved_effect_hints"] == ["apply_checkout_option"]
    assert "Example Street" not in query_json
    assert "12345" not in query_json
    assert "4111" not in query_json
    assert "Place Order" in query_json
    try:
        _check_human_takeover_text("Proceed to checkout")
        raise AssertionError("ordinary browse click should block checkout-prep controls")
    except ValueError:
        pass
    assert _safe_artifact_stem("Total Due / Buy Box!", "fallback") == "total-due-buy-box"
    crop = _bounded_crop_rect({"x": 10, "y": 10, "width": 40, "height": 20}, 100, 80, 1, 1, 5)
    assert crop["x"] == 5 and crop["y"] == 5 and crop["width"] == 50 and crop["height"] == 30
    try:
        _bounded_crop_rect({"x": -200, "y": -200, "width": 4, "height": 4}, 100, 80, 1, 1, 0)
        raise AssertionError("off-image crop should be blocked")
    except ValueError:
        pass
    assert json.loads(secure_browser_visual_evidence_tool({"crops": "not-a-list"}))["error"] == "INVALID_CROPS"
    assert _reject_unsafe_operation("request_final_purchase_approval")["trusted_approval_required"] is True
    assert _reject_unsafe_operation("execute_final_purchase")["allowed"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", _approval_token_key("ar-20260101-000000-deadbe", "ap-test", "a" * 64, "b" * 64))
    try:
        _assert_hex_binding("not-a-binding", "material_summary_binding")
        raise AssertionError("invalid binding should be blocked")
    except ValueError:
        pass
    disabled_owner_review = json.loads(secure_browser_owner_checkout_review_tool({"send_to_telegram": False}))
    assert disabled_owner_review["error"] == "OWNER_CHECKOUT_REVIEW_FAILED"
    assert disabled_owner_review["operation"] == "owner_checkout_review"
    huge_owner_review = {
        "operation": "owner_checkout_review",
        "status": "sent_owner_only",
        "review_id": "review-test",
        "url": "https://www.amazon.com/gp/buy/spc/handlers/display.html",
        "page_title": "Review your order",
        "material_summary_binding": "binding-test",
        "owner_visual_evidence_binding": "evidence-test",
        "capture_mode": "full-page",
        "artifact_count": 1,
        "telegram_message_ids": [12345],
        "checkout_review": {
            "items": ["Widget Qty: 1 Sold by Example Seller"] * 50,
            "totals": ["Order total $5.29"] * 50,
            "delivery": ["Delivery Monday"] * 50,
            "shipping_destination_city_state_or_label": ["Sampletown, NY"] * 10,
            "payment_method_label_last_four_only": ["Visa ending in 5252"] * 10,
            "purchase_mode": "subscription_offer_visible_only",
            "subscription_offer_visible": True,
            "subscription_selected": False,
            "subscription_control_visible": False,
            "one_time_selected": False,
            "informational_flags": ["Subscribe & Save Delivery every 2 months"] * 20,
            "surprise_flags": [],
            "checkout_prep_controls": [{"selector": "#control", "label": "Change payment"}] * 200,
            "blocked_metadata": {"final_purchase_controls_visible": ["Place Order"]},
        },
        "retention": "sensitive PNG artifacts were deleted locally after Telegram delivery",
    }
    compact_owner_review = json.loads(_json(huge_owner_review))
    compact_owner_json = json.dumps(compact_owner_review, ensure_ascii=False)
    assert compact_owner_review["status"] == "sent_owner_only"
    assert compact_owner_review["delivery"] == {"telegram": True, "telegram_message_count": 1, "status": "sent"}
    assert compact_owner_review["material_summary_binding"] == "binding-test"
    assert compact_owner_review["owner_visual_evidence_binding"] == "evidence-test"
    assert compact_owner_review["capture_mode"] == "full-page"
    assert compact_owner_review["artifact_count"] == 1
    assert compact_owner_review["minimal_order_facts"]["purchase_mode"] == "subscription_offer_visible_only"
    assert compact_owner_review["minimal_order_facts"]["subscription_offer_visible"] is True
    assert compact_owner_review["minimal_order_facts"]["subscription_selected"] is False
    assert compact_owner_review["minimal_order_facts"]["subscription_control_visible"] is False
    assert "checkout_review" not in compact_owner_review
    assert "checkout_prep_controls" not in compact_owner_json
    assert "selector" not in compact_owner_json
    assert "Place Order" not in compact_owner_json
    assert len(compact_owner_json) <= MAX_RESULT_CHARS
    import tempfile

    original_ledger_path = SECURE_BROWSER_ORDER_LEDGER_PATH
    with tempfile.TemporaryDirectory() as tmpdir:
        globals()["SECURE_BROWSER_ORDER_LEDGER_PATH"] = os.path.join(tmpdir, "secure-browser-order-ledger.sqlite3")
        order_result = json.loads(secure_browser_order_upsert_tool({
            "handle": "pipe-screens-coffee-filters",
            "retailer": "amazon",
            "item_nickname": "pipe screens and coffee filters",
            "item_category": "consumables",
            "status": "confirmed",
            "eta_window": "Tuesday",
            "safe_delivery_facts": ["Arriving Tuesday"],
            "material_summary_binding": "a" * 64,
            "owner_visual_evidence_binding": "b" * 64,
            "source_refs": ["owner_post_purchase_proof"],
        }))
        assert order_result["status"] == "stored"
        assert order_result["order"]["handle"] == "pipe-screens-coffee-filters"
        order_json = json.dumps(order_result, ensure_ascii=False)
        assert "111-2222222-3333333" not in order_json
        assert "Example Street" not in order_json
        assert json.loads(secure_browser_order_read_tool({"handle": "pipe-screens-coffee-filters"}))["order"]["status"] == "confirmed"
        preview_same = json.loads(secure_browser_order_notification_preview_tool({"handle": "pipe-screens-coffee-filters", "status": "confirmed", "eta_window": "Tuesday"}))
        assert preview_same["notification_decision"]["should_notify"] is False
        preview_eta = json.loads(secure_browser_order_notification_preview_tool({"handle": "pipe-screens-coffee-filters", "status": "confirmed", "eta_window": "Wednesday"}))
        assert preview_eta["notification_decision"]["should_notify"] is True
        assert preview_eta["notification_decision"]["event_type"] == "eta_changed"
        notified = json.loads(secure_browser_order_mark_notified_tool({"handle": "pipe-screens-coffee-filters", "event_type": "eta_changed"}))
        assert notified["status"] == "stored"
        consumable = json.loads(secure_browser_consumable_suggest_from_order_tool({"handle": "pipe-screens-coffee-filters"}))
        assert consumable["status"] == "stored"
        assert consumable["consumable"]["confidence"] == "suggested"
        explicit = json.loads(secure_browser_consumable_upsert_tool({"handle": "coffee-filters", "item_nickname": "coffee filters", "item_category": "coffee", "confidence": "explicit", "source": "joy_statement"}))
        assert explicit["consumable"]["confidence"] == "explicit"
        closed = json.loads(secure_browser_order_close_tool({"handle": "pipe-screens-coffee-filters", "status": "delivered", "safe_delivery_facts": ["Delivered Tuesday"]}))
        assert closed["order"]["status"] == "delivered"
        assert closed["order"]["archived"] is True
        assert json.loads(secure_browser_order_upsert_tool({"handle": "111-2222222-3333333", "item_nickname": "unsafe"}))["error"] == "SECURE_BROWSER_ORDER_UPSERT_FAILED"
        final_purchase_stub = {
            "request_id": "ar-20260101-000000-deadbe",
            "approval_id": "ap-test",
            "material_summary_binding": "c" * 64,
            "owner_visual_evidence_binding": "d" * 64,
            "final_url": "https://www.amazon.com/gp/buy/thankyou/handlers/display.html",
            "post_purchase_proof": {
                "status": "sent_owner_only",
                "review_id": "review-test",
                "post_purchase_summary_binding": "e" * 64,
                "post_purchase_review": {
                    "post_purchase_state": "post_purchase_confirmation_visible",
                    "confirmation_visible": True,
                    "orders_page_visible": False,
                    "item_clues": ["pipe screens and coffee filters"],
                    "delivery_status": ["Arriving Tuesday"],
                },
            },
        }
        tracking = _order_entry_from_final_purchase_result(final_purchase_stub, {"items": ["pipe screens and coffee filters"], "delivery": ["Arriving Tuesday"]})
        assert tracking["order"]["handle"].startswith("order-")
        assert tracking["order"]["status"] == "confirmed"
        assert tracking["order"]["refresh_sources"][:2] == ["amazon_your_orders", "gmail_order_email"]
        assert json.loads(secure_browser_order_refresh_plan_tool({}))["scheduled_refresh_spec"]["primary_source"] == "Amazon Your Orders via secure browser owner/post-purchase evidence path"
        with _ledger_connect() as conn:
            conn.execute("UPDATE shopping_orders SET status = 'shipped', updated_at = ? WHERE handle = ?", ((datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(), tracking["order"]["handle"]))
            conn.commit()
        original_refresh_observation = _refresh_observation_for_source
        original_send_order_notification = _send_order_notification
        try:
            globals()["_refresh_observation_for_source"] = lambda order, source: {
                "source": source,
                "status": "ok",
                "order_status": "delivered",
                "eta_window": "Delivered Tuesday",
                "safe_delivery_facts": ["Delivered Tuesday"],
                "source_refs": [source],
            }
            globals()["_send_order_notification"] = lambda message: {"status": "sent", "telegram_message_id": 4242, "message": message}
            refresh_run = json.loads(secure_browser_order_refresh_run_tool({"send_notifications": True, "limit": 5}))
        finally:
            globals()["_refresh_observation_for_source"] = original_refresh_observation
            globals()["_send_order_notification"] = original_send_order_notification
        assert refresh_run["status"] == "ok"
        assert refresh_run["notifications_sent"] == 1
        assert refresh_run["refreshed"][0]["applied"]["notification"]["status"] == "sent"
        refreshed_order = json.loads(secure_browser_order_read_tool({"handle": tracking["order"]["handle"]}))["order"]
        assert refreshed_order["status"] == "delivered"
        assert refreshed_order["notification_state"]["last_notified_delivered"]
    globals()["SECURE_BROWSER_ORDER_LEDGER_PATH"] = original_ledger_path

    body, content_type = _multipart_request({"chat_id": "123"}, {"document": ("review.png", b"png", "image/png")})
    assert b"review.png" in body and content_type.startswith("multipart/form-data")
    status = json.loads(secure_browser_status_tool({}))
    assert "screenshot" in status["browser_operations"]
    assert "visual_evidence" in status["browser_operations"]
    assert "owner_checkout_review" in status["browser_operations"]
    assert "order_list" in status["browser_operations"]
    assert "consumable_upsert" in status["browser_operations"]
    assert status["supervised_checkout_prep"]["status"] == "available"
    assert status["trusted_assistant_access"]["status"] == "broad_browsing_available"
    assert "owner_checkout_review" in status["approval_gated_operations"]
    assert "place_order" in status["approval_gated_operations"]
    assert "inspect_product" not in status["browser_operations"]
    assert _extract_asin("https://www.amazon.com/example/dp/B09JJNBB9C?x=1") == "B09JJNBB9C"
    assert _review_url("https://www.amazon.com/example/dp/B09JJNBB9C?x=1")[0] == "https://www.amazon.com/product-reviews/B09JJNBB9C"
    assert _bounded_max_reviews(99) == MAX_REVIEWS
    assert _product_url_from_url_or_asin("B01J01XGPK") == ("https://www.amazon.com/dp/B01J01XGPK", "B01J01XGPK")
    assert _approved_cart_addition("B01J01XGPK", 1, Decimal("7.95"), "one_time")["quantity"] == 1
    assert "text('#ppd')" not in ADD_TO_CART_PRECHECK_JS
    assert "condition_summary" in ADD_TO_CART_PRECHECK_JS
    assert "product_condition" in PRODUCT_EXTRACT_JS
    active_schema_names = [STATUS_SCHEMA["name"], NAVIGATE_SCHEMA["name"], PAGE_SNAPSHOT_SCHEMA["name"], QUERY_SCHEMA["name"], SCREENSHOT_SCHEMA["name"], VISUAL_EVIDENCE_SCHEMA["name"], CLICK_SCHEMA["name"], TYPE_SCHEMA["name"], CURRENT_PAGE_SUMMARY_SCHEMA["name"], OWNER_CHECKOUT_REVIEW_SCHEMA["name"], ORDER_LIST_SCHEMA["name"], ORDER_READ_SCHEMA["name"], ORDER_UPSERT_SCHEMA["name"], ORDER_CLOSE_SCHEMA["name"], ORDER_NOTIFICATION_PREVIEW_SCHEMA["name"], ORDER_MARK_NOTIFIED_SCHEMA["name"], ORDER_REFRESH_PLAN_SCHEMA["name"], ORDER_REFRESH_RUN_SCHEMA["name"], CONSUMABLE_LIST_SCHEMA["name"], CONSUMABLE_UPSERT_SCHEMA["name"], CONSUMABLE_SUGGEST_FROM_ORDER_SCHEMA["name"], GUARDRAIL_SCHEMA["name"]]
    assert "secure_browser_owner_checkout_review" in active_schema_names
    assert "secure_browser_order_upsert" in active_schema_names
    assert "secure_browser_consumable_upsert" in active_schema_names
    assert "secure_browser_inspect_product" not in active_schema_names
    assert "secure_browser_inspect_reviews" not in active_schema_names
    assert "secure_browser_inspect_cart" not in active_schema_names
    assert "secure_browser_add_to_cart" not in active_schema_names
    assert not any(word in json.dumps(STATUS_SCHEMA).lower() for word in ("cookie", "localstorage"))
    product = {"image_url_candidates": ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg?x=1", "https://example.com/not-amazon.jpg"]}
    _normalize_product_images(product)
    assert product["primary_image_url"] == "https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"
    assert product["image_urls"] == ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"]
    print("secure_browser_tool smoke ok")

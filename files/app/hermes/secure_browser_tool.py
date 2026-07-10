"""Broad secure browser bridge for Star.

This custom Hermes toolset exposes browser-like control of the Puppet/KubeCM
managed Kasm secure browser for Star.  Star is allowed to navigate, inspect,
query, click, type, screenshot, and otherwise operate the persistent browser UI
without policy refusals for shopping, returns, account-adjacent pages, checkout,
forms, order lookup, address/payment/contact fields, credential prompts, or
other visible browser state.  The tool still reports precise technical errors
from the browser/backend and records high-level audit events.
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
SECURE_BROWSER_TARGET = os.environ.get("SECURE_BROWSER_TARGET", "browser.eyrie-firefox")
WORKLOAD = os.environ.get("SECURE_BROWSER_WORKLOAD", "deployment/firefox")
EXPECTED_WORKLOAD = os.environ.get("SECURE_BROWSER_EXPECTED_WORKLOAD", "deployment/firefox")
EXPECTED_IMAGE_RE = os.environ.get("SECURE_BROWSER_EXPECTED_IMAGE_RE", r"nest/tools/firefox")
EXPECTED_APP_LABEL = os.environ.get("SECURE_BROWSER_EXPECTED_APP_LABEL", "firefox")
FORBIDDEN_WORKLOAD_RE = os.environ.get("SECURE_BROWSER_FORBIDDEN_WORKLOAD_RE", r"deployment/secure-browser")
FORBIDDEN_IMAGE_RE = os.environ.get("SECURE_BROWSER_FORBIDDEN_IMAGE_RE", r"kasmweb/chrome")
REMOTE_DEBUG_PORT = int(os.environ.get("SECURE_BROWSER_CDP_PORT", "9222"))
CDP_ENDPOINT_URL = os.environ.get("SECURE_BROWSER_CDP_URL", "").rstrip("/")
BROWSER_OWNER = os.environ.get("SECURE_BROWSER_OWNER", "shopping")
SECURE_BROWSER_MAX_AGENT_TABS = max(1, int(os.environ.get("SECURE_BROWSER_MAX_AGENT_TABS", "1")))
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
HUMAN_TAKEOVER_RE = re.compile(r"\b(sign\s*in|login|bitwarden|passkey|password|two[- ]?factor|2fa|otp|verification\s+code|captcha|security\s+check|suspicious|card|cvv|cvc)\b", re.IGNORECASE)
CART_URL_RE = re.compile(r"/(gp/)?cart(/|$)", re.IGNORECASE)
CART_REMOVE_TEXT_RE = re.compile(r"\b(delete|remove)\b", re.IGNORECASE)
CHECKOUT_APPROVED_EFFECTS = ("checkout_prep", "select_shipping_option", "select_delivery_option", "select_packaging_option", "apply_checkout_option", "fix_purchase_mode", "cart_line_adjustment")
APPROVED_CLICK_EFFECTS = ("browse", "select_option", "apply_visible_coupon", "add_to_cart", "remove_from_cart") + CHECKOUT_APPROVED_EFFECTS
APPROVED_TYPE_EFFECTS = ("type", "apply_checkout_option", "cart_line_adjustment")
SENSITIVE_FIELD_RE = re.compile(r"(password|passkey|otp|verification|card|cvv|cvc|security.?code)", re.IGNORECASE)
SENSITIVE_TYPED_TEXT_RE = re.compile(r"\b(?:cvv|cvc|security code|verification code|otp)\s*[:#-]?\s*\d+\b", re.IGNORECASE)
CHECKOUTISH_PAGE_RE = re.compile(r"checkout|buy|payselect|ship|spc|review|ordering", re.IGNORECASE)
CHECKOUT_QUERY_PAGE_RE = re.compile(r"checkout|payselect|spc|ordering|place[-\s]?order|review\s+your\s+order|order\s+review|/gp/buy|/buy|shipping\s+(address|option|speed|method)|delivery\s+(option|date|window)", re.IGNORECASE)
POST_PURCHASE_CONFIRMATION_RE = re.compile(r"thank\s*you|order\s+(?:confirmation|confirmed|placed|received)|purchase\s+(?:complete|completed|confirmed)|/gp/buy/thankyou|thankyou|order-confirmation", re.IGNORECASE)
AMAZON_ORDERS_RE = re.compile(r"/gp/(?:css/)?order-history|/gp/your-account/order|/your-orders|/order-details|orderID=", re.IGNORECASE)
SAFE_CHECKOUT_SENSITIVE_LABEL_RE = re.compile(r"shipping\s+(speed|option|method|packag(?:e|ing))|delivery\s+(option|date|window|packag(?:e|ing))|packag(?:e|ing)\s+(option|preference)|ship\s+in\s+(?:amazon|manufacturer|original)\s+packag(?:e|ing)|gift(?!\s*card\s*(number|code))|gift\s+card\s+balance|use\s+a\s+gift\s+card|coupon|promo|promotion|claim\s+code|payment\s+(summary|method|option)|paying\s+with|quantity|qty|delete|remove|one[-\s]?time|subscribe|subscription|cart", re.IGNORECASE)
MUTATING_QUERY_RE = re.compile(r"\b(click|submit|fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|cookie|setAttribute|removeAttribute|appendChild|removeChild|innerHTML\s*=|location\s*=|open\s*\()\b", re.IGNORECASE)
MUTATING_ASSIGNMENT_RE = re.compile(r"(?<![=!<>])(?:\+\+|--|[-+*/%&|^]?=(?![=>]))")


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
  // Star full-access mode: if more than one final-purchase-like control is visible, choose the first visible control after deterministic sorting.
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
  const redact = (value) => clean(value);
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const selectorMatchesElement = (selector, el) => {
    try { return document.querySelector(selector) === el; }
    catch (_) { return false; }
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
    const candidates = [];
    if (el.id) candidates.push(`#${CSS.escape(el.id)}`);
    const name = el.getAttribute('name');
    if (name && el.tagName) candidates.push(`${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`);
    const aria = el.getAttribute('aria-label');
    if (aria && el.tagName) candidates.push(`${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`);
    for (const candidate of candidates) {
      if (selectorMatchesElement(candidate, el)) return candidate;
    }
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
    sanitization: 'disabled; Star receives visible page text and interactive labels as returned by the browser, subject only to max_text_chars/max_interactive limits.'
  };
})()
"""

CLICK_JS = r"""
(() => {
  const selector = __SELECTOR__;
  const initialNode = document.querySelector(selector);
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return Boolean(style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0);
  };
  const nodeLabel = (el) => clean(el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || '');
  const equivalentVisibleNode = (node) => {
    if (!node || visible(node)) return node;
    const tag = clean(node.tagName || '').toLowerCase();
    const aria = node.getAttribute('aria-label') || '';
    const name = node.getAttribute('name') || '';
    const id = node.getAttribute('id') || '';
    const selectors = [];
    if (id) selectors.push(`#${CSS.escape(id)}`);
    if (name && tag) selectors.push(`${tag}[name="${CSS.escape(name)}"]`);
    if (aria && tag) selectors.push(`${tag}[aria-label="${CSS.escape(aria)}"]`);
    for (const candidateSelector of selectors) {
      for (const candidate of Array.from(document.querySelectorAll(candidateSelector))) {
        if (visible(candidate)) return candidate;
      }
    }
    return node;
  };
  const node = equivalentVisibleNode(initialNode);
  if (!node) return {clicked: false, reason: 'selector did not match any element'};
  if (node.disabled || node.getAttribute('aria-disabled') === 'true') return {clicked: false, reason: 'matched element is disabled'};
  node.scrollIntoView({block: 'center', inline: 'center'});
  const text = nodeLabel(node);
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
  const initialNode = document.querySelector(selector);
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return Boolean(style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0);
  };
  const nodeLabel = (el) => clean(el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || '');
  const equivalentVisibleNode = (node) => {
    if (!node || visible(node)) return node;
    const tag = clean(node.tagName || '').toLowerCase();
    const aria = node.getAttribute('aria-label') || '';
    const name = node.getAttribute('name') || '';
    const id = node.getAttribute('id') || '';
    const selectors = [];
    if (id) selectors.push(`#${CSS.escape(id)}`);
    if (name && tag) selectors.push(`${tag}[name="${CSS.escape(name)}"]`);
    if (aria && tag) selectors.push(`${tag}[aria-label="${CSS.escape(aria)}"]`);
    for (const candidateSelector of selectors) {
      for (const candidate of Array.from(document.querySelectorAll(candidateSelector))) {
        if (visible(candidate)) return candidate;
      }
    }
    return node;
  };
  const node = equivalentVisibleNode(initialNode);
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
  const blockedReason = '';
  const finalControls = Array.from(document.querySelectorAll('a, button, input, [role="button"], [role="link"]'))
    .map((el) => clean(el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || ''))
    .filter((label) => /place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|purchase\s+now|confirm\s+(purchase|order)/i.test(label))
    .slice(0, 8);
  return {
    page_title: document.title || '',
    url: location.href || '',
    blocked_reason: blockedReason,
    final_purchase_controls_visible: finalControls,
    checkout_prep_state: 'full_access_visible'
  };
})()
"""


CHECKOUT_PREP_CONTROLS_JS = r"""
(() => {
  const maxControls = __MAX_CONTROLS__;
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-secure-browser-checkout-control]').forEach((node) => node.removeAttribute('data-secure-browser-checkout-control'));
  const redact = (value) => clean(value);
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return Boolean(style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0);
  };
  const selectorFor = (el) => {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';
    if (el.id) return `#${CSS.escape(el.id)}`;
    const name = el.getAttribute('name');
    if (name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    const dataTestId = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '';
    if (dataTestId) return `${el.tagName.toLowerCase()}[data-testid="${CSS.escape(dataTestId)}"]`;
    const aria = el.getAttribute('aria-label') || '';
    if (aria && aria.length <= 90) return `${el.tagName.toLowerCase()}[aria-label="${CSS.escape(aria)}"]`;
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
    if (/shipping speed|shipping option|shipping method|shipping packaging|delivery option|delivery date|delivery day|delivery packaging|packaging option|ship in (amazon|manufacturer|original) packaging|arrives|ship/i.test(label)) return 'shipping_delivery';
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
    if (/packaging option|shipping packaging|delivery packaging|ship in (amazon|manufacturer|original) packaging/i.test(label)) hints.push('select_packaging_option');
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
    if (tag === 'INPUT' && ['hidden'].includes(type)) continue;
    const label = labelFor(el);
    const directBits = clean([el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '', el.id, el.getAttribute('name'), el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('autocomplete'), type, role].join(' '));
    const rawBits = clean([label, directBits].join(' '));
    if (!label && !rawBits) continue;
    if (finalControl.test(directBits)) {
      finalPurchaseControls.push(redact(label || rawBits).slice(0, 120));
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
    policy: 'Star full-access mode returns checkout/order-review controls without secure_browser policy suppression; final purchase and address/payment/account/security controls are included when visible.'
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
  const redactAddress = (value) => clean(value);
  const paymentLabels = pick([/ending in \d{4}/i, /\b(?:visa|mastercard|amex|american express|discover|gift card)\b/i], 4)
    .map((line) => clean(line));
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
    policy: 'Star full-access mode; secure_browser policy redaction/refusal is disabled for checkout/order-review summaries.'
  };
})()
"""

POST_PURCHASE_EXTRACT_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const redact = (value) => clean(value);
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
    policy: 'Star full-access mode; secure_browser policy redaction/refusal is disabled for post-purchase/order-verification summaries.'
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
  const redact = (value) => clean(value);
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
      final_purchase_control: 650,
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
  Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"], a')).filter((node) => /place\s+(your\s+)?order|buy\s+now|submit\s+order|complete\s+purchase|confirm\s+(purchase|order)/i.test(clean(node.innerText || node.value || node.getAttribute('aria-label') || node.textContent || ''))).slice(0, 6).forEach((node, index) => add('final_purchase_control', node, `final purchase control ${index + 1}`));

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
    access_note: 'Star full-access mode returns page-visible region labels and bounding boxes without secure_browser policy suppression.'
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


def _compact_checkout_review_for_tool_result(checkout_review: dict[str, Any], max_controls: int = 8) -> dict[str, Any]:
    """Return compact, safe checkout facts for Star-visible tool results.

    Full checkout summaries can include dozens of safe controls and long
    redacted text fragments.  Keep enough state for the next deterministic
    Star action while avoiding RESULT_TOO_LARGE fallbacks that hide whether a
    checkout-prep click actually advanced.
    """
    controls = checkout_review.get("checkout_prep_controls")
    control_count = len(controls) if isinstance(controls, list) else 0
    compact: dict[str, Any] = {
        "url": _bounded_checkout_scalar(checkout_review.get("url"), 500),
        "page_title": _bounded_checkout_scalar(checkout_review.get("page_title"), 200),
        "material_summary_binding": _bounded_checkout_scalar(checkout_review.get("material_summary_binding"), 128),
        "checkout_prep_state": _bounded_checkout_scalar(checkout_review.get("checkout_prep_state"), 100),
        "final_purchase_state": "full_access_available",
        "minimal_order_facts": _minimal_owner_checkout_facts(checkout_review),
        "checkout_prep_controls_returned": min(control_count, max_controls),
        "checkout_prep_controls_truncated_from": control_count,
        "checkout_prep_controls": controls[:max_controls] if isinstance(controls, list) else [],
        "next_read_back": "If navigation state is unclear, call secure_browser_current_page_summary or secure_browser_page_snapshot before clicking another checkout-prep control.",
    }
    blocked_metadata = checkout_review.get("blocked_metadata")
    if isinstance(blocked_metadata, dict):
        compact["blocked_metadata"] = {
            "final_purchase_controls_visible_count": len(blocked_metadata.get("final_purchase_controls_visible") or []),
            "sensitive_controls_skipped_count": len(blocked_metadata.get("sensitive_controls_skipped") or []),
            "checkout_prep_controls_total": blocked_metadata.get("checkout_prep_controls_total", control_count),
        }
    return compact


def _compact_large_result(data: dict[str, Any]) -> dict[str, Any]:
    compact = dict(data)
    if compact.get("operation") == "owner_checkout_review":
        compact = _compact_owner_checkout_review_result(compact)
    checkout_review = compact.get("checkout_review")
    if isinstance(checkout_review, dict) and compact.get("operation") in {"click", "type", "current_page_summary", "query"}:
        compact["checkout_review"] = _compact_checkout_review_for_tool_result(checkout_review)
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
        "final_purchase_state": "full_access_available",
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
        "checkout_handoff_default": "Star full-access mode is active; owner-review evidence is optional and does not gate browser operation.",
        "access_note": "Owner-review screenshots were sent to Joy via Telegram; Star full-access browser tools remain available separately.",
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
    _audit("retail_order_upserted", {"handle": payload["handle"], "status": payload["status"], "retailer": payload["retailer"]})
    return {
        "operation": "retail_order_upsert",
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
        "operation": "retail_order_list",
        "status": "ok",
        "orders": orders,
        "active_count": sum(1 for order in orders if order["status"] in ORDER_STATUSES_ACTIVE and not order["archived"]),
        "ledger_path_hint": "profile-local retail-order ledger",
    }


def _read_order(handle: str) -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
    if not order:
        return {"operation": "retail_order_read", "status": "not_found", "handle": safe_handle}
    return {"operation": "retail_order_read", "status": "ok", "order": order}


def _close_order(handle: str, status: str = "delivered", archive: bool = True, safe_delivery_facts: Any = None, notes: str = "") -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        existing = _get_order(conn, safe_handle)
        if not existing:
            return {"operation": "retail_order_close", "status": "not_found", "handle": safe_handle}
    args = {
        **existing,
        "handle": safe_handle,
        "status": _safe_order_status(status, "delivered"),
        "archive": archive,
        "safe_delivery_facts": safe_delivery_facts if safe_delivery_facts is not None else existing.get("safe_delivery_facts"),
        "notes": notes or existing.get("notes") or "",
    }
    result = _upsert_order_entry(args)
    result["operation"] = "retail_order_close"
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
    return {"operation": "retail_order_notification_preview", "status": "ok", "handle": handle, "notification_decision": decision, "candidate_order": candidate}


def _mark_order_notified(handle: str, event_type: str) -> dict[str, Any]:
    event_type = str(event_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if event_type not in ORDER_NOTIFY_EVENT_TYPES:
        raise ValueError("event_type must be one of initial_confirmation, eta_changed, status_changed, out_for_delivery, delivered")
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
        if not order:
            return {"operation": "retail_order_mark_notified", "status": "not_found", "handle": safe_handle}
        state = _coerce_json_dict(order.get("notification_state"))
        state[f"last_notified_{event_type}"] = _utc_now()
        conn.execute("UPDATE shopping_orders SET notification_state_json = ?, updated_at = ? WHERE handle = ?", (json.dumps(state, ensure_ascii=False, sort_keys=True), _utc_now(), safe_handle))
        conn.commit()
        order = _get_order(conn, safe_handle)
    return {"operation": "retail_order_mark_notified", "status": "stored", "order": order}


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
        "operation": "retail_order_refresh_plan",
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
    _audit("retail_order_refresh_run", {"due_count": len(due_orders), "refreshed_count": len(refreshed), "sent_count": sent_count})
    return {
        "operation": "retail_order_refresh_run",
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
        "operation": "consumable_upsert",
        "status": "stored",
        "consumable": _consumable_row_to_safe_dict(row),
        "learning_policy": "Explicit Joy statements may be durable; repeated purchases can be suggested/tentative; ambiguous one-offs should remain tentative or ask before durable memory.",
    }


def _list_consumables(include_archived: bool = False) -> dict[str, Any]:
    where = "" if include_archived else "WHERE archived = 0"
    with _ledger_connect() as conn:
        rows = conn.execute(f"SELECT * FROM consumable_items {where} ORDER BY updated_at DESC LIMIT 100").fetchall()
    return {"operation": "consumable_list", "status": "ok", "consumables": [_consumable_row_to_safe_dict(row) for row in rows]}


def _suggest_consumable_from_order(handle: str) -> dict[str, Any]:
    safe_handle = _safe_order_handle(handle)
    with _ledger_connect() as conn:
        order = _get_order(conn, safe_handle)
    if not order:
        return {"operation": "consumable_suggest_from_order", "status": "not_found", "handle": safe_handle}
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
    suggestion["operation"] = "consumable_suggest_from_order"
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
        "item_category": "retail order",
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
        "item_category": "retail order",
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


ACTIVE_FINAL_PURCHASE_APPROVAL_REQUEST_STATUSES = {"submitting", "approval_requested", "superseding", "supersede_failed"}
TERMINAL_AGENT_REQUEST_STATUSES = {"completed", "completed_with_followup", "cancelled", "denied", "failed_probe", "invalid_proposal", "superseded"}


def _valid_agent_request_id(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"ar-\d{8}-\d{6}-[0-9a-f]{6}", text):
        return ""
    return text


def _supersede_agent_request_disposition(request_id: str, replacement_request_id: str, reason: str) -> dict[str, Any]:
    request_id = _valid_agent_request_id(request_id)
    replacement_request_id = _valid_agent_request_id(replacement_request_id)
    if not request_id or not replacement_request_id or request_id == replacement_request_id:
        raise ValueError("valid distinct Agent Request ids are required to supersede stale final-purchase approvals")
    try:
        from agent_request_broker import kanban_backend
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime wiring
        raise RuntimeError(f"Agent Request maintenance backend is unavailable: {exc}") from exc
    with kanban_backend.scoped_board(_agent_request_board()):
        conn = kanban_backend.connect()
        try:
            result = kanban_backend.disposition({
                "request_id": request_id,
                "disposition": "superseded",
                "reason": reason,
                "superseded_by": replacement_request_id,
                "archive": True,
            }, actor="talon")
        finally:
            conn.close()
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result.get("error")))
    return result if isinstance(result, dict) else {"status": "ok"}


def _retire_prior_final_purchase_approval_requests(new_binding_key: str, new_request_id: str, reason: str) -> list[dict[str, Any]]:
    """Supersede older active Star final-purchase approval requests.

    The secure browser represents one supervised checkout lane.  When Star
    requests a fresh final-purchase binding, any older active prompt from this
    lane is stale: approving it would either fail live-binding validation or,
    worse, keep a completed purchase actionable in Telegram.  Retire the older
    Agent Requests through the broker maintenance path so inline actions are
    also resolved, while mirroring the disposition in the profile-local state
    file for exactly-once diagnostics.
    """
    new_request_id = _valid_agent_request_id(new_request_id)
    if not new_binding_key or not new_request_id:
        return []
    now = datetime.now(timezone.utc).isoformat()
    candidates: list[tuple[str, str]] = []
    with _final_purchase_state_lock() as handle:
        state = _load_final_purchase_state(handle)
        approval_requests = state.setdefault("approval_requests", {})
        for binding_key, existing in list(approval_requests.items()):
            if binding_key == new_binding_key or not isinstance(existing, dict):
                continue
            old_request_id = _valid_agent_request_id(existing.get("request_id"))
            if not old_request_id or old_request_id == new_request_id:
                continue
            if str(existing.get("status") or "") not in ACTIVE_FINAL_PURCHASE_APPROVAL_REQUEST_STATUSES:
                continue
            existing["status"] = "superseding"
            existing["superseded_by"] = new_request_id
            existing["supersede_reason"] = reason
            existing["updated_at"] = now
            candidates.append((str(binding_key), old_request_id))
        if candidates:
            _store_final_purchase_state(handle, state)
    retirements: list[dict[str, Any]] = []
    for binding_key, old_request_id in candidates:
        record: dict[str, Any] = {"request_id": old_request_id, "binding_key": binding_key, "superseded_by": new_request_id}
        try:
            disposition = _supersede_agent_request_disposition(old_request_id, new_request_id, reason)
            record["status"] = "superseded"
            request_obj = disposition.get("request") if isinstance(disposition, dict) else None
            if isinstance(request_obj, dict):
                record["request_status"] = request_obj.get("status")
                record["kanban_status"] = request_obj.get("kanban_status")
            action_resolution = disposition.get("action_resolution") if isinstance(disposition, dict) else None
            if isinstance(action_resolution, dict):
                record["action_resolution"] = {
                    "attempted": action_resolution.get("attempted"),
                    "edited": action_resolution.get("edited"),
                    "marked_resolved": action_resolution.get("marked_resolved"),
                }
        except Exception as exc:
            record["status"] = "supersede_failed"
            record["error"] = str(exc)[:500]
        retirements.append(record)
    if retirements:
        with _final_purchase_state_lock() as handle:
            state = _load_final_purchase_state(handle)
            approval_requests = state.setdefault("approval_requests", {})
            for retirement in retirements:
                existing = approval_requests.get(retirement["binding_key"])
                if not isinstance(existing, dict):
                    continue
                existing["status"] = retirement["status"]
                existing["superseded_by"] = new_request_id
                existing["supersede_reason"] = reason
                existing["superseded_at"] = datetime.now(timezone.utc).isoformat()
                if retirement.get("error"):
                    existing["supersede_error"] = retirement["error"]
                elif "supersede_error" in existing:
                    existing.pop("supersede_error", None)
            _store_final_purchase_state(handle, state)
        _audit("final_purchase_stale_approval_requests_retired", {"new_request_id": new_request_id, "retirements": retirements})
    return retirements


def _mark_final_purchase_request_executed(request_id: str, approval_id: str, material_summary_binding: str, owner_visual_evidence_binding: str, final_url: str, final_title: str) -> list[dict[str, Any]]:
    request_id = _valid_agent_request_id(request_id)
    if not request_id:
        return []
    executed_at = datetime.now(timezone.utc).isoformat()
    executed_binding_key = ""
    with _final_purchase_state_lock() as handle:
        state = _load_final_purchase_state(handle)
        approval_requests = state.setdefault("approval_requests", {})
        for binding_key, existing in approval_requests.items():
            if isinstance(existing, dict) and _valid_agent_request_id(existing.get("request_id")) == request_id:
                executed_binding_key = str(binding_key)
                existing["status"] = "executed"
                existing["approval_id"] = approval_id
                existing["material_summary_binding"] = material_summary_binding
                existing["owner_visual_evidence_binding"] = owner_visual_evidence_binding
                existing["final_url"] = final_url
                existing["final_title"] = final_title
                existing["executed_at"] = executed_at
                existing["updated_at"] = executed_at
                break
        _store_final_purchase_state(handle, state)
    reason = "Superseded by a refreshed final-purchase approval that was approved and executed exactly once; stale earlier checkout binding must not remain actionable."
    return _retire_prior_final_purchase_approval_requests(executed_binding_key, request_id, reason)


def _submit_final_purchase_approval_request(summary: dict[str, Any], material_summary_binding: str, owner_visual_evidence_binding: str, owner_review_id: str, note: str = "") -> dict[str, Any]:
    facts = _minimal_owner_checkout_facts(summary)
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    binding_key = _approval_request_binding_key(material_summary_binding, owner_visual_evidence_binding, owner_review_id)
    retailer = _checkout_retailer_label(str(summary.get("url") or ""))
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
        "subject": f"Joy approval to place the current {retailer} order",
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
            f"Approve exactly one final {retailer} order-submission action for the current Star secure-browser checkout.",
            f"Bound material_summary_binding: {material_summary_binding}",
            f"Bound owner_visual_evidence_binding: {owner_visual_evidence_binding}",
            f"Owner checkout review id: {owner_review_id or 'not supplied'}",
            f"Sanitized order facts: {facts_json}",
            "The executor must re-read the live checkout page immediately before clicking and refuse if any material field changed, if sensitive verification/login/account prompts appear, if final purchase controls are ambiguous/missing, or if this approval was already used.",
            "Approval does not grant ordinary Star final-click authority and does not authorize payment/address/account edits, subscriptions, add-ons, warranty/protection changes, login, passkeys, 2FA, CAPTCHA, or security prompts.",
        ])
        propose_result = json.loads(agent_request_propose_tool({
            "request_id": request_id,
            "summary": f"approval-required: place current {retailer} order exactly once if bound checkout summary still matches",
            "proposal": proposal_text,
            "subject": f"Final {retailer} order submission for current Star checkout",
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
    supersede_reason = "Superseded by a refreshed final-purchase approval request for the same Star secure-browser checkout lane; only the newest bound checkout approval should remain actionable."
    stale_retirements = _retire_prior_final_purchase_approval_requests(binding_key, request_id, supersede_reason)
    return {"status": "approval_requested", "submit_result": submit_result, "proposal_result": propose_result, "request_id": request_id, "binding_key": binding_key, "stale_approval_retirements": stale_retirements}


def _current_agent_request_approval(request_id: str) -> dict[str, Any]:
    try:
        from agent_request_broker import kanban_backend
    except Exception as exc:  # pragma: no cover - depends on Hermes runtime wiring
        raise RuntimeError(f"Agent Request approval backend is unavailable: {exc}") from exc
    with kanban_backend.scoped_board(_agent_request_board()):
        conn = kanban_backend.connect()
        try:
            item = kanban_backend.index_for_request(conn, request_id)
            approval = kanban_backend.current_approval(conn, request_id)
            proposal = kanban_backend.latest_proposal(conn, request_id)
        finally:
            conn.close()
    if not item:
        raise ValueError("approval_request_id is not a known Agent Request")
    request_status = str(getattr(item, "status", "") or "").strip().lower()
    if request_status in TERMINAL_AGENT_REQUEST_STATUSES:
        raise ValueError(f"approval_request_id is {request_status}; final-purchase request is terminal")
    if not proposal:
        raise ValueError("approval_request_id has no current final-purchase proposal")
    if not approval:
        raise ValueError("approval_request_id is not approved through the trusted Agent Request path")
    return approval


def _request_final_purchase_approval(material_summary_binding: str, owner_visual_evidence_binding: str, owner_review_id: str = "", note: str = "") -> dict[str, Any]:
    return {
        "operation": "request_final_purchase_approval",
        "status": "not_required",
        "approval_required": False,
        "trusted_approval_required": False,
        "message": "Star full-access mode is active; secure_browser no longer requires a final-purchase approval gate for browser UI operation.",
    }


def _execute_final_purchase(approval_request_id: str, material_summary_binding: str, owner_visual_evidence_binding: str) -> dict[str, Any]:
    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        click_result = _evaluate(browser, session_id, FINAL_PURCHASE_CLICK_JS) or {}
        if not click_result.get("clicked"):
            raise RuntimeError(str(click_result.get("reason") or "no visible enabled final purchase control matched"))
        time.sleep(2.0)
        final_url = str(_evaluate(browser, session_id, "location.href") or "")
        final_title = str(_evaluate(browser, session_id, "document.title") or "")
        result = {
            "operation": "execute_final_purchase",
            "status": "clicked",
            "approval_required": False,
            "trusted_approval_required": False,
            "final_url": final_url,
            "final_page_title": final_title,
            "control_label": str(click_result.get("control_label") or "")[:120],
            "access_note": "Star full-access mode clicked the visible final-purchase control without secure_browser approval-gate policy checks.",
        }
        _audit("final_purchase_executed_full_access", {"final_url": final_url, "final_title": final_title, "control_label": result.get("control_label")})
        return result
    return _with_browser(run)


def _safe_browser_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("secure browser navigation only accepts http(s) URLs")
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
    return bool(parsed.scheme == "https" and CHECKOUT_QUERY_PAGE_RE.search(page_material))


def _is_checkout_upsell_interstitial_page(url: str, title: str = "") -> bool:
    parsed = urlparse(str(url or ""))
    page_material = " ".join([parsed.path, parsed.query, str(title or "")])
    return bool(
        parsed.scheme == "https"
        and AMAZON_HOST_RE.search(parsed.netloc)
        and re.search(r"/checkout/byg|need\s+anything\s+else|continue\s+to\s+checkout", page_material, re.IGNORECASE)
    )


def _checkout_review_page_rank(page: dict[str, Any]) -> tuple[int, str]:
    url = str(page.get("url") or "")
    title = str(page.get("title") or "")
    # Checkout-review/order-entry pages should win over Amazon's "Need
    # anything else?" upsell interstitial when both are live after a click.
    return (0 if _is_checkout_upsell_interstitial_page(url, title) else 1, url)


def _is_owner_checkout_review_page(url: str, title: str = "") -> bool:
    """Return whether owner-only review can capture this page.

    Generic non-Amazon support is intentionally limited to HTTPS checkout or
    order-review pages.  Post-purchase/order-history proof remains Amazon-only
    until those retailer-specific sanitizers exist, but owner-only checkout
    evidence can be captured because the screenshots go directly to Joy and the
    model-visible return is the existing sanitized checkout summary.
    """
    return _is_checkoutish_page(url, title) or _is_amazon_post_purchase_page(url, title)


def _checkout_retailer_label(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if AMAZON_HOST_RE.search(parsed.netloc):
        return "Amazon"
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or "retailer"


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
        "Star full-access mode is active; checkout query policy redirection is disabled on the main secure_browser_query path."
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
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
    return value


def _sanitize_checkout_summary(summary: dict[str, Any], safety: dict[str, Any], controls: dict[str, Any] | None = None) -> dict[str, Any]:
    controls = controls or {}
    checkout_controls = controls.get("safe_controls") or []
    final_purchase_controls = controls.get("final_purchase_controls_visible") or safety.get("final_purchase_controls_visible") or summary.get("final_purchase_controls_visible") or []
    result: dict[str, Any] = {
        "operation": "checkout_review_summary",
        "page_title": str(summary.get("page_title") or safety.get("page_title") or ""),
        "url": _sanitize_url(str(summary.get("url") or safety.get("url") or "")),
        "checkout_prep_state": "full_access_visible",
        "human_takeover_required": False,
        "items": _as_checkout_list(summary.get("items"))[:10],
        "totals": _as_checkout_list(summary.get("totals"))[:8],
        "delivery": _as_checkout_list(summary.get("delivery"))[:8],
        "shipping_destination_city_state_or_label": _as_checkout_list(summary.get("shipping_destination_label_or_city_state"))[:8],
        "payment_method_label_last_four_only": _as_checkout_list(summary.get("payment_method_label_last_four_only"))[:8],
        "purchase_mode": str(summary.get("purchase_mode") or "not_detected"),
        "subscription_offer_visible": bool(summary.get("subscription_offer_visible")),
        "subscription_selected": bool(summary.get("subscription_selected")),
        "subscription_control_visible": bool(summary.get("subscription_control_visible")),
        "one_time_selected": bool(summary.get("one_time_selected")),
        "purchase_mode_controls": summary.get("purchase_mode_controls") or [],
        "informational_flags": _as_checkout_list(summary.get("informational_flags"))[:10],
        "surprise_flags": _as_checkout_list(summary.get("surprise_flags"))[:10],
        "checkout_prep_controls": checkout_controls,
        "full_access_metadata": {
            "final_purchase_controls_present": bool(final_purchase_controls),
            "final_purchase_control_count": len(final_purchase_controls) if isinstance(final_purchase_controls, list) else 0,
            "final_purchase_controls_visible": final_purchase_controls,
            "checkout_control_count": len(checkout_controls) if isinstance(checkout_controls, list) else 0,
            "secure_browser_policy_refusals": "disabled",
        },
        "policy": "Star full-access mode; secure_browser checkout/order-review summary redaction, human-takeover, and final-purchase blocking are disabled.",
    }
    binding_material = {
        "items": result["items"],
        "totals": result["totals"],
        "delivery": result["delivery"],
        "shipping_destination_city_state_or_label": result["shipping_destination_city_state_or_label"],
        "payment_method_label_last_four_only": result["payment_method_label_last_four_only"],
        "purchase_mode": result["purchase_mode"],
        "subscription_offer_visible": result["subscription_offer_visible"],
        "subscription_selected": result["subscription_selected"],
        "informational_flags": result["informational_flags"],
        "surprise_flags": result["surprise_flags"],
        "url": result["url"],
        "final_purchase_controls_present": result["full_access_metadata"]["final_purchase_controls_present"],
    }
    result["material_summary_binding"] = hashlib.sha256(json.dumps(binding_material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return result


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


def _post_purchase_summary_is_meaningful(summary: dict[str, Any]) -> bool:
    if summary.get("confirmation_visible") or summary.get("orders_page_visible"):
        return True
    for key in ("order_presence", "delivery_status", "item_clues"):
        if summary.get(key):
            return True
    state = str(summary.get("post_purchase_state") or "")
    return state in {"post_purchase_confirmation_visible", "post_purchase_orders_visible"}


def _wait_for_post_purchase_readiness(browser: CdpSession, session_id: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Wait until post-purchase pages expose non-blank proof content."""
    deadline = time.time() + max(0.0, float(timeout_seconds))
    last_summary: dict[str, Any] = {}
    while True:
        ready_state = str(_evaluate(browser, session_id, "document.readyState") or "")
        last_summary = _post_purchase_summary_from_browser(browser, session_id)
        if ready_state in {"interactive", "complete"} and _post_purchase_summary_is_meaningful(last_summary):
            return last_summary
        if time.time() >= deadline:
            details = {
                "ready_state": ready_state,
                "post_purchase_state": last_summary.get("post_purchase_state"),
                "confirmation_visible": bool(last_summary.get("confirmation_visible")),
                "orders_page_visible": bool(last_summary.get("orders_page_visible")),
                "order_presence_count": len(last_summary.get("order_presence") or []),
                "delivery_status_count": len(last_summary.get("delivery_status") or []),
                "item_clue_count": len(last_summary.get("item_clues") or []),
            }
            raise RuntimeError(f"post-purchase proof page did not expose meaningful loaded content before capture: {json.dumps(details, sort_keys=True)}")
        time.sleep(0.5)


def _check_human_takeover_text(text: str) -> None:
    return None


def _check_cart_remove_url(url: str, title: str) -> None:
    return None


def _assert_cart_remove_click_allowed(metadata: dict[str, Any], reason: str) -> None:
    return None



def _checkout_metadata_text(metadata: dict[str, Any]) -> str:
    return " ".join(str(metadata.get(key) or "") for key in ("text", "value", "aria_label", "name", "title", "id", "page_title", "url"))


def _checkout_control_identity_text(metadata: dict[str, Any]) -> str:
    return " ".join(str(metadata.get(key) or "") for key in ("text", "value", "aria_label", "name", "title", "id"))


def _checkoutish_page_text(metadata: dict[str, Any]) -> str:
    parsed = urlparse(str(metadata.get("url") or ""))
    return " ".join([parsed.path, parsed.query, str(metadata.get("page_title") or ""), _checkout_metadata_text(metadata)])


def _assert_checkout_page(metadata: dict[str, Any], effect: str) -> None:
    return None


def _assert_checkout_control_not_sensitive(control_text: str) -> None:
    return None


def _assert_checkout_click_allowed(metadata: dict[str, Any], effect: str, reason: str) -> None:
    return None


def _assert_checkout_type_allowed(metadata: dict[str, Any], effect: str, reason: str, typed_text: str) -> None:
    return None


def _checkout_summary_from_browser(browser: CdpSession, session_id: str, max_controls: int = MAX_LINKS) -> dict[str, Any]:
    safety = _evaluate(browser, session_id, CHECKOUT_PAGE_SAFETY_JS) or {}
    summary = _evaluate(browser, session_id, ORDER_REVIEW_EXTRACT_JS) or {}
    controls_expr = CHECKOUT_PREP_CONTROLS_JS.replace("__MAX_CONTROLS__", str(max(0, min(int(max_controls), MAX_LINKS))))
    controls = _evaluate(browser, session_id, controls_expr) or {}
    return _sanitize_checkout_summary(summary, safety, controls)

def _check_secure_browser() -> bool:
    return bool(CDP_ENDPOINT_URL) or shutil.which("kubectl") is not None


def _kubectl_get_json(resource: str) -> dict[str, Any]:
    cmd = ["kubectl", "-n", NAMESPACE, "get", resource, "-o", "json"]
    env = os.environ.copy()
    env.setdefault("HOME", "/home/joy")
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=10, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"kubectl identity check failed for {resource}: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def _backend_identity_from_deployment(data: dict[str, Any]) -> dict[str, Any]:
    template = data.get("spec", {}).get("template", {})
    metadata = template.get("metadata", {})
    pod_spec = template.get("spec", {})
    containers = pod_spec.get("containers") or []
    images = [str(container.get("image") or "") for container in containers if isinstance(container, dict)]
    return {
        "name": str(data.get("metadata", {}).get("name") or ""),
        "namespace": str(data.get("metadata", {}).get("namespace") or NAMESPACE),
        "workload": WORKLOAD,
        "images": images,
        "labels": metadata.get("labels") or {},
        "ready_replicas": data.get("status", {}).get("readyReplicas", 0),
        "replicas": data.get("status", {}).get("replicas", 0),
        "observed_generation": data.get("status", {}).get("observedGeneration"),
    }


def _backend_identity_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "target": SECURE_BROWSER_TARGET,
        "namespace": NAMESPACE,
        "workload": WORKLOAD,
        "expected_workload": EXPECTED_WORKLOAD,
        "expected_image_re": EXPECTED_IMAGE_RE,
        "expected_app_label": EXPECTED_APP_LABEL,
        "forbidden_workload_re": FORBIDDEN_WORKLOAD_RE,
        "forbidden_image_re": FORBIDDEN_IMAGE_RE,
        "cdp_endpoint_url_configured": bool(CDP_ENDPOINT_URL),
    }
    if "browser.eyrie" in SECURE_BROWSER_TARGET or "firefox" in SECURE_BROWSER_TARGET:
        if CDP_ENDPOINT_URL and re.search(r"secure-browser(?:-cdp)?\.eyrie", CDP_ENDPOINT_URL, re.IGNORECASE):
            status.update({"ok": False, "reason": "configured CDP endpoint points at legacy secure-browser ingress"})
            return status
        if re.search(FORBIDDEN_WORKLOAD_RE, WORKLOAD, re.IGNORECASE):
            status.update({"ok": False, "reason": "configured workload matches forbidden legacy secure-browser workload"})
            return status
        if WORKLOAD != EXPECTED_WORKLOAD:
            status.update({"ok": False, "reason": "configured workload does not match requested browser.eyrie Firefox target"})
            return status
    if CDP_ENDPOINT_URL:
        status.update({"ok": True, "reason": "service endpoint configured; URL-level legacy guard passed"})
        return status
    if shutil.which("kubectl") is None:
        status.update({"ok": False, "reason": "kubectl is unavailable for backend identity check"})
        return status
    try:
        identity = _backend_identity_from_deployment(_kubectl_get_json(WORKLOAD))
    except Exception as exc:
        status.update({"ok": False, "reason": str(exc)[:500]})
        return status
    status["identity"] = identity
    image_text = " ".join(identity.get("images") or [])
    app_label = str((identity.get("labels") or {}).get("browser.joyfullee.me/app") or (identity.get("labels") or {}).get("app") or "")
    if re.search(FORBIDDEN_IMAGE_RE, image_text, re.IGNORECASE):
        status.update({"ok": False, "reason": "live workload image matches forbidden legacy Chrome/Kasm backend"})
    elif EXPECTED_IMAGE_RE and not re.search(EXPECTED_IMAGE_RE, image_text, re.IGNORECASE):
        status.update({"ok": False, "reason": "live workload image does not match expected Firefox/Kasm backend"})
    elif EXPECTED_APP_LABEL and app_label != EXPECTED_APP_LABEL:
        status.update({"ok": False, "reason": "live workload labels do not identify the expected Firefox browser app"})
    else:
        status.update({"ok": True, "reason": "backend identity matches requested browser.eyrie Firefox target"})
    return status


def _enforce_backend_identity() -> None:
    status = _backend_identity_status()
    if not status.get("ok"):
        raise RuntimeError(f"secure browser backend identity check failed: {status.get('reason')}; target={SECURE_BROWSER_TARGET}; workload={WORKLOAD}")


def _sanitize_url(value: str) -> str:
    return str(value or "")


_ORDER_REFERENCE_RE = re.compile(r"\b(?:order|confirmation)\s*(?:#|number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9-]{8,}\b", re.IGNORECASE)


def _sanitize_shopping_text(value: Any) -> str:
    raw = _ORDER_REFERENCE_RE.sub("[order reference redacted]", str(value or ""))
    text = _sanitize_checkout_text(raw)
    text = _ORDER_REFERENCE_RE.sub("[order reference redacted]", text)
    text = text.replace("[[order reference redacted] redacted]", "[order reference redacted]")
    return text


def _sanitize_shopping_value(value: Any) -> Any:
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
    return {"mode": "full_access", "redaction_required": False}


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


def _capture_layout_metrics(browser: Any, session_id: str) -> dict[str, float]:
    metrics = _evaluate(
        browser,
        session_id,
        "(() => ({"
        "width: Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0, window.innerWidth),"
        "height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0, window.innerHeight),"
        "viewport_width: window.innerWidth,"
        "viewport_height: window.innerHeight,"
        "device_scale_factor: window.devicePixelRatio || 1,"
        "original_x: window.scrollX,"
        "original_y: window.scrollY"
        "}))()",
    ) or {}
    result: dict[str, float] = {}
    for key in ("width", "height", "viewport_width", "viewport_height", "device_scale_factor", "original_x", "original_y"):
        try:
            result[key] = float(metrics.get(key) or 0)
        except (AttributeError, TypeError, ValueError):
            result[key] = 0.0
    result["viewport_width"] = max(1.0, result.get("viewport_width") or 1.0)
    result["viewport_height"] = max(1.0, result.get("viewport_height") or 1.0)
    result["width"] = max(result["viewport_width"], result.get("width") or result["viewport_width"])
    result["height"] = max(result["viewport_height"], result.get("height") or result["viewport_height"])
    result["device_scale_factor"] = max(0.1, result.get("device_scale_factor") or 1.0)
    return result


def _image_covers_document(image_width: int, image_height: int, layout: dict[str, float]) -> bool:
    document_height = float(layout.get("height") or 0)
    viewport_height = float(layout.get("viewport_height") or 0)
    if document_height <= 0 or viewport_height <= 0:
        return True
    if document_height <= viewport_height + 2:
        return True
    scale = float(layout.get("device_scale_factor") or 1.0)
    viewport_width = float(layout.get("viewport_width") or 0)
    if viewport_width > 0 and image_width > 0:
        scale = max(0.1, image_width / viewport_width)
    return image_height >= int(document_height * scale * 0.95)


def _owner_review_scroll_positions(layout: dict[str, float]) -> list[int]:
    viewport_height = max(1, int(layout.get("viewport_height") or 900))
    document_height = max(viewport_height, int(layout.get("height") or viewport_height))
    bottom = max(0, document_height - viewport_height)
    positions = list(range(0, bottom + 1, viewport_height))
    if bottom not in positions:
        positions.append(bottom)
    positions = sorted(set(positions))
    if len(positions) <= MAX_OWNER_REVIEW_VIEWPORTS:
        return positions
    if MAX_OWNER_REVIEW_VIEWPORTS <= 1:
        return [0]
    # Preserve top and bottom evidence when an unusually tall checkout/order
    # page exceeds the owner-only Telegram artifact cap. Interior positions are
    # spread through the document instead of silently omitting below-the-fold
    # material such as totals, delivery details, or confirmation sections.
    step = (len(positions) - 1) / float(MAX_OWNER_REVIEW_VIEWPORTS - 1)
    selected = [positions[round(index * step)] for index in range(MAX_OWNER_REVIEW_VIEWPORTS)]
    return sorted(set(selected))


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


def _is_blank_page_url(value: str) -> bool:
    url = str(value or "").strip().lower()
    return not url or url in ("about:blank", "about:srcdoc")


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
    return {
        "allowed": True,
        "operation": op,
        "approval_required": False,
        "trusted_approval_required": False,
        "boundary": "star_full_secure_browser_access",
        "message": "Allowed. Star secure_browser access has no tool-level policy blocks for browser UI operation; only precise technical/backend errors should fail.",
    }


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
        _enforce_backend_identity()
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
        endpoint = urlparse(cdp_url)
        version_url = f"{cdp_url}/json/version"
        last_error = ""
        while time.time() < deadline:
            if self.process and self.process.poll() is not None:
                stderr = (self.process.stderr.read() if self.process.stderr else "").strip()
                raise RuntimeError(f"kubectl port-forward failed: {stderr[:800]}")
            try:
                if "browser.eyrie" in SECURE_BROWSER_TARGET or "firefox" in SECURE_BROWSER_TARGET:
                    default_port = 443 if endpoint.scheme == "https" else REMOTE_DEBUG_PORT
                    with socket.create_connection((endpoint.hostname or "127.0.0.1", endpoint.port or default_port), timeout=1):
                        return
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
        self.next_id = 1
        self.cdp_url = cdp_url
        self.protocol = "bidi" if websocket_url.startswith("bidi+") else "cdp"
        self._bidi_session_created = False
        if self.protocol == "bidi":
            parsed = urlparse(websocket_url[len("bidi+") :])
            if parsed.hostname is None or parsed.port is None:
                raise RuntimeError("secure browser BiDi endpoint is missing host or port")
            if parsed.scheme == "wss":
                self.ws = websockets.sync.client.connect(parsed.geturl(), open_timeout=5, close_timeout=2, max_size=CDP_MAX_MESSAGE_BYTES, compression=None, proxy=None)
                self._bidi("session.new", {"capabilities": {"alwaysMatch": {}}})
                self._bidi_session_created = True
                return
            sock = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
            # Firefox validates the WebSocket Host header against its own
            # loopback listener.  Kubernetes port-forward uses an arbitrary
            # local port, so connect the TCP socket to that local port while
            # sending the browser's real loopback endpoint in the handshake.
            browser_ws_url = f"ws://127.0.0.1:{REMOTE_DEBUG_PORT}/session"
            self.ws = websockets.sync.client.connect(browser_ws_url, sock=sock, open_timeout=5, close_timeout=2, max_size=CDP_MAX_MESSAGE_BYTES, compression=None)
            self._bidi("session.new", {"capabilities": {"alwaysMatch": {}}})
            self._bidi_session_created = True
        else:
            self.ws = websockets.sync.client.connect(websocket_url, open_timeout=5, close_timeout=2, max_size=CDP_MAX_MESSAGE_BYTES)

    def close(self) -> None:
        if self.protocol == "bidi" and self._bidi_session_created:
            with contextlib.suppress(Exception):
                self._bidi("session.end", {})
        self.ws.close()

    def _bidi(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"id": self.next_id, "method": method, "params": params or {}}
        call_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv(timeout=10)
            data = json.loads(raw)
            if data.get("id") == call_id:
                if data.get("type") == "error" or "error" in data:
                    message = data.get("message") or data.get("error") or "unknown error"
                    raise RuntimeError(f"BiDi {method} failed: {message}")
                return data.get("result") or {}

    @staticmethod
    def _bidi_value(value: dict[str, Any]) -> Any:
        value_type = value.get("type")
        if "value" in value:
            raw = value.get("value")
            if value_type == "array" and isinstance(raw, list):
                return [CdpSession._bidi_value(item) if isinstance(item, dict) else item for item in raw]
            if value_type == "object" and isinstance(raw, list):
                return {str(item[0].get("value") if isinstance(item[0], dict) else item[0]): CdpSession._bidi_value(item[1]) if isinstance(item[1], dict) else item[1] for item in raw if isinstance(item, list) and len(item) == 2}
            return raw
        if value_type in ("undefined", "null"):
            return None
        return None

    def _bidi_contexts(self) -> list[dict[str, Any]]:
        # `browsingContext.getTree` returns top-level tabs with nested child
        # browsing contexts for iframes. Secure-browser ownership and
        # navigation must bind to visible tabs only: if a child iframe is saved
        # as the owner target, later top-level navigations can fail with Firefox
        # errors such as NS_ERROR_XFO_VIOLATION and snapshots inspect the wrong
        # frame. CDP `Target.getTargets` exposes page targets, not iframes, so
        # keep the BiDi compatibility layer at the same top-level-tab boundary.
        return [context for context in (self._bidi("browsingContext.getTree", {}).get("contexts") or []) if isinstance(context, dict)]

    def call(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> dict[str, Any]:
        params = params or {}
        if self.protocol == "bidi":
            if method == "Target.getTargets":
                return {"targetInfos": [{"targetId": str(context.get("context")), "type": "page", "url": str(context.get("url") or ""), "title": ""} for context in self._bidi_contexts() if context.get("context")]}
            if method == "Target.createTarget":
                result = self._bidi("browsingContext.create", {"type": "tab"})
                context_id = str(result.get("context") or "")
                url = str(params.get("url") or "")
                if url:
                    self._bidi("browsingContext.navigate", {"context": context_id, "url": url, "wait": "complete"})
                return {"targetId": context_id}
            if method == "Target.attachToTarget":
                return {"sessionId": str(params.get("targetId") or "")}
            if method in ("Runtime.enable", "Page.enable"):
                return {}
            if method == "Page.navigate":
                self._bidi("browsingContext.navigate", {"context": str(session_id or ""), "url": str(params.get("url") or "about:blank"), "wait": "complete"})
                return {}
            if method == "Runtime.evaluate":
                result = self._bidi(
                    "script.evaluate",
                    {
                        "expression": str(params.get("expression") or "undefined"),
                        "target": {"context": str(session_id or "")},
                        "awaitPromise": bool(params.get("awaitPromise", True)),
                        "resultOwnership": "none",
                    },
                )
                return {"result": {"value": self._bidi_value(result.get("result") or {})}}
            if method == "Page.captureScreenshot":
                origin = "document" if bool(params.get("captureBeyondViewport")) else "viewport"
                result = self._bidi("browsingContext.captureScreenshot", {"context": str(session_id or ""), "origin": origin})
                return {"data": str(result.get("data") or "")}
            if method == "Target.closeTarget":
                self._bidi("browsingContext.close", {"context": str(params.get("targetId") or ""), "promptUnload": False})
                return {}
            raise RuntimeError(f"Firefox BiDi bridge does not implement CDP method {method}")

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
    endpoint = urlparse(cdp_url)
    if "browser.eyrie" in SECURE_BROWSER_TARGET or "firefox" in SECURE_BROWSER_TARGET:
        scheme = "wss" if endpoint.scheme == "https" else "ws"
        default_port = 443 if scheme == "wss" else REMOTE_DEBUG_PORT
        return f"bidi+{scheme}://{endpoint.hostname or '127.0.0.1'}:{endpoint.port or default_port}/session"
    with urlopen(f"{cdp_url}/json/version", timeout=3) as response:
        version = json.loads(response.read().decode("utf-8"))
    url = str(version.get("webSocketDebuggerUrl") or "")
    if not url:
        raise RuntimeError("secure browser CDP endpoint did not report a browser websocket")
    parsed = urlparse(url)
    scheme = "wss" if endpoint.scheme == "https" else "ws"
    return urlunparse((scheme, endpoint.netloc, parsed.path, "", parsed.query, parsed.fragment))


def _page_candidates(browser: CdpSession) -> list[dict[str, str]]:
    pages: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_page(target_id: Any, url: Any = "", title: Any = "") -> None:
        page_id = str(target_id or "")
        if not page_id or page_id in seen:
            return
        seen.add(page_id)
        pages.append({"id": page_id, "url": str(url or ""), "title": str(title or "")})

    if getattr(browser, "protocol", "cdp") == "bidi":
        with contextlib.suppress(Exception):
            for context in browser._bidi_contexts():
                add_page(context.get("context"), context.get("url"), context.get("title"))
    if browser.cdp_url is not None:
        with contextlib.suppress(Exception):
            for target in _page_targets_from_http(browser.cdp_url):
                add_page(target.get("id"), target.get("url"), target.get("title"))
    with contextlib.suppress(Exception):
        targets = browser.call("Target.getTargets").get("targetInfos") or []
        for target in targets:
            if target.get("type") == "page":
                add_page(target.get("targetId"), target.get("url"), target.get("title"))
    return pages


def _current_page_ids(browser: CdpSession) -> set[str]:
    return {page["id"] for page in _page_candidates(browser) if page.get("id")}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    with contextlib.suppress(ValueError):
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _tab_age_seconds(entry: dict[str, Any], now: datetime | None = None) -> int | None:
    stamp = _parse_iso_timestamp(entry.get("updated_at") or entry.get("created_at"))
    if stamp is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - stamp).total_seconds()))


def _current_agent_tab_context() -> dict[str, str]:
    return {
        "owner": BROWSER_OWNER,
        "profile": os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_NAME") or "",
        "task_id": os.environ.get("HERMES_KANBAN_TASK") or os.environ.get("HERMES_TASK_ID") or "",
        "run_id": os.environ.get("HERMES_KANBAN_RUN_ID") or os.environ.get("HERMES_RUN_ID") or "",
    }


def _owner_tabs(state: dict[str, Any], owner: str = BROWSER_OWNER) -> dict[str, Any]:
    tabs_by_owner = state.setdefault("owner_tabs", {})
    if not isinstance(tabs_by_owner, dict):
        state["owner_tabs"] = tabs_by_owner = {}
    tabs = tabs_by_owner.setdefault(owner, {})
    if not isinstance(tabs, dict):
        tabs_by_owner[owner] = tabs = {}
    return tabs


def _merge_existing_keep_fields(entry: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(existing, dict):
        if existing.get("created_at"):
            entry["created_at"] = existing["created_at"]
        if existing.get("keep_open"):
            entry["keep_open"] = True
            if existing.get("keep_reason"):
                entry["keep_reason"] = _sanitize_shopping_text(existing.get("keep_reason"))[:240]
    return entry


def _known_agent_tab_entry(target_id: str, url: str = "", title: str = "", existing: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _iso_now()
    context = _current_agent_tab_context()
    entry: dict[str, Any] = {
        "target_id": target_id,
        "toolset": TOOLSET,
        "owner": context["owner"],
        "profile": context["profile"],
        "task_id": context["task_id"],
        "run_id": context["run_id"],
        "workload": WORKLOAD,
        "created_at": now,
        "updated_at": now,
        "keep_open": False,
    }
    if url:
        entry["url"] = _sanitize_url(url)
    if title:
        entry["title"] = _sanitize_shopping_text(title)[:240]
    return _merge_existing_keep_fields(entry, existing)


def _tab_public_summary(entry: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    summary = {
        "target_id": str(entry.get("target_id") or ""),
        "owner": str(entry.get("owner") or BROWSER_OWNER),
        "profile": str(entry.get("profile") or ""),
        "task_id": str(entry.get("task_id") or ""),
        "run_id": str(entry.get("run_id") or ""),
        "url": _sanitize_url(str(entry.get("url") or "")) if entry.get("url") else "",
        "title": _sanitize_shopping_text(entry.get("title") or "")[:240],
        "created_at": str(entry.get("created_at") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
        "age_seconds": _tab_age_seconds(entry),
        "keep_open": bool(entry.get("keep_open")),
    }
    if entry.get("keep_reason"):
        summary["keep_reason"] = _sanitize_shopping_text(entry.get("keep_reason"))[:240]
    if reason:
        summary["reason"] = reason
    return summary


def _sync_known_agent_tabs(browser: CdpSession, state: dict[str, Any], owner: str = BROWSER_OWNER) -> dict[str, Any]:
    live = {page["id"]: page for page in _page_candidates(browser) if page.get("id")}
    live_pages = list(live.values())
    tabs = _owner_tabs(state, owner)
    owners = state.setdefault("owners", {})
    for target_id in list(tabs):
        if target_id not in live:
            entry = tabs.get(target_id)
            rematched = _page_matching_stored_tab(live_pages, entry) if isinstance(entry, dict) else None
            if rematched is not None and rematched.get("id") and isinstance(entry, dict):
                new_target_id = str(rematched["id"])
                existing = tabs.get(new_target_id) if isinstance(tabs.get(new_target_id), dict) else None
                refreshed = _known_agent_tab_entry(
                    new_target_id,
                    str(rematched.get("url") or entry.get("url") or ""),
                    str(rematched.get("title") or entry.get("title") or ""),
                    existing or entry,
                )
                tabs.pop(target_id, None)
                tabs[new_target_id] = refreshed
                current_owner = owners.get(owner) if isinstance(owners.get(owner), dict) else None
                if isinstance(current_owner, dict) and str(current_owner.get("target_id") or "") == str(target_id):
                    owners[owner] = refreshed
            else:
                tabs.pop(target_id, None)
    for target_id, entry in list(tabs.items()):
        page = live.get(target_id)
        if page and isinstance(entry, dict):
            refreshed = dict(entry)
            refreshed["target_id"] = target_id
            refreshed.setdefault("toolset", TOOLSET)
            refreshed.setdefault("owner", owner)
            refreshed.setdefault("workload", WORKLOAD)
            if page.get("url"):
                refreshed["url"] = _sanitize_url(str(page.get("url") or ""))
            if page.get("title"):
                refreshed["title"] = _sanitize_shopping_text(page.get("title") or "")[:240]
            tabs[target_id] = refreshed
    return live


def _cleanup_candidates_from_state(state: dict[str, Any], live_ids: set[str], max_age_seconds: int = 0, owner: str = BROWSER_OWNER) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for target_id, entry in _owner_tabs(state, owner).items():
        if target_id not in live_ids or not isinstance(entry, dict):
            continue
        if entry.get("keep_open"):
            continue
        age = _tab_age_seconds(entry, now)
        if max_age_seconds > 0 and (age is None or age < max_age_seconds):
            continue
        enriched = dict(entry)
        enriched["target_id"] = target_id
        candidates.append(enriched)
    candidates.sort(key=lambda item: (_parse_iso_timestamp(item.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc), str(item.get("target_id") or "")))
    return candidates


def _close_agent_owned_tabs(
    browser: CdpSession,
    state: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    dry_run: bool,
    reason: str,
    owner: str = BROWSER_OWNER,
) -> list[dict[str, Any]]:
    tabs = _owner_tabs(state, owner)
    closed: list[dict[str, Any]] = []
    for entry in candidates:
        target_id = str(entry.get("target_id") or "")
        if not target_id:
            continue
        public = _tab_public_summary(entry, reason=reason)
        if not dry_run:
            browser.call("Target.closeTarget", {"targetId": target_id})
            tabs.pop(target_id, None)
            owners = state.setdefault("owners", {})
            current = owners.get(owner) if isinstance(owners, dict) else None
            if isinstance(current, dict) and str(current.get("target_id") or "") == target_id:
                owners.pop(owner, None)
        closed.append(public)
    return closed


def _enforce_agent_tab_budget(browser: CdpSession, state: dict[str, Any], *, owner: str = BROWSER_OWNER, reason: str = "bounded_agent_tab_reuse") -> list[dict[str, Any]]:
    """Close oldest non-kept agent-owned tabs until this owner is within budget."""
    live_ids = _current_page_ids(browser)
    candidates = _cleanup_candidates_from_state(state, live_ids, owner=owner)
    overflow_count = max(0, len(candidates) - SECURE_BROWSER_MAX_AGENT_TABS)
    if overflow_count <= 0:
        return []
    return _close_agent_owned_tabs(
        browser,
        state,
        candidates[:overflow_count],
        dry_run=False,
        reason=reason,
        owner=owner,
    )


def _load_owner_state(handle: Any) -> dict[str, Any]:
    handle.seek(0)
    raw = handle.read()
    if not raw.strip():
        return {"owners": {}, "owner_tabs": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"owners": {}, "owner_tabs": {}}
    if not isinstance(data, dict):
        return {"owners": {}, "owner_tabs": {}}
    owners = data.get("owners")
    if not isinstance(owners, dict):
        data["owners"] = {}
    owner_tabs = data.get("owner_tabs")
    if not isinstance(owner_tabs, dict):
        data["owner_tabs"] = {}
    return data


def _store_owner_state(handle: Any, state: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())


def _owner_state_entry(target_id: str, url: str = "", title: str = "") -> dict[str, Any]:
    return _known_agent_tab_entry(target_id, url, title)


def _store_owner_target(target_id: str, url: str = "", title: str = "") -> None:
    os.makedirs(os.path.dirname(OWNERSHIP_STATE_PATH) or ".", exist_ok=True)
    with open(OWNERSHIP_STATE_PATH, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            state = _load_owner_state(handle)
            owners = state.setdefault("owners", {})
            tabs = _owner_tabs(state)
            existing = tabs.get(target_id) if isinstance(tabs.get(target_id), dict) else None
            entry = _known_agent_tab_entry(target_id, url, title, existing)
            owners[BROWSER_OWNER] = entry
            tabs[target_id] = entry
            _store_owner_state(handle, state)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _page_matching_stored_owner(pages: list[dict[str, str]], owner: dict[str, Any]) -> dict[str, str] | None:
    stored_url = str(owner.get("url") or "")
    if not stored_url or _is_blank_page_url(stored_url):
        return None
    for page in pages:
        if _sanitize_url(str(page.get("url") or "")) == stored_url:
            return page
    return None


def _page_matching_stored_tab(pages: list[dict[str, str]], entry: dict[str, Any]) -> dict[str, str] | None:
    stored_url = str(entry.get("url") or "")
    if not stored_url or _is_blank_page_url(stored_url):
        return None
    for page in pages:
        page_id = str(page.get("id") or "")
        page_url = _sanitize_url(str(page.get("url") or ""))
        if page_id and page_url == stored_url:
            return page
    return None


def _deterministic_current_page(pages: list[dict[str, str]]) -> dict[str, str] | None:
    # Firefox BiDi context ids can be session-scoped, so a target id saved by a
    # previous tool call is not always enough to find the visible tab again.
    # Prefer the last non-blank page in the deterministic browser enumeration;
    # this matches the tab most recently opened/navigated by secure_browser and
    # avoids manufacturing a fresh about:blank tab for read-only follow-up tools.
    non_blank = [page for page in pages if not _is_blank_page_url(str(page.get("url") or ""))]
    if non_blank:
        return non_blank[-1]
    return pages[-1] if pages else None


def _checkout_candidate_allowed_for_source(page: dict[str, Any], source_url: str) -> bool:
    """Return whether a checkout candidate can belong to a checkout-prep click.

    Amazon post-purchase/order-history pages are owner-review proof surfaces, not
    generic checkout-prep destinations for an unrelated retailer.  A non-Amazon
    cart click must not let a stale Amazon order-history tab win ownership just
    because it is also considered owner-review-capable.
    """
    source_host = urlparse(str(source_url or "")).netloc
    page_url = str(page.get("url") or "")
    page_title = str(page.get("title") or "")
    if _is_amazon_post_purchase_page(page_url, page_title) and not AMAZON_HOST_RE.search(source_host):
        return False
    return True


def _select_post_click_owner_page(
    browser: CdpSession,
    original_target_id: str,
    current_url: str = "",
    current_title: str = "",
    *,
    prefer_checkout: bool = False,
    source_url: str = "",
    pre_click_target_ids: set[str] | None = None,
) -> dict[str, str]:
    """Pick the page that should remain owned after an audited click.

    Some third-party checkout buttons replace or detach the original cart
    browsing context while opening the real checkout in a fresh context. If we
    keep the stale pre-click target id, the next secure_browser tool call may
    manufacture a new about:blank tab and lose the live checkout. Reconcile the
    owner to a live checkout/order-review page first, falling back to the most
    recent non-blank page when the click was ordinary browsing.

    Checkout-prep reconciliation is scoped to the click. Prefer checkout pages
    opened by the click, then the original tab if it navigated into checkout.
    Do not steal ownership from an older checkout/order-history tab belonging to
    another retailer, especially Amazon order-history proof pages.
    """
    original_target_id = str(original_target_id or "")
    pre_click_target_ids = {str(target_id) for target_id in pre_click_target_ids or set() if str(target_id)}
    deadline = time.time() + (5.0 if prefer_checkout else 0.0)
    while True:
        pages = _page_candidates(browser)
        if prefer_checkout:
            checkout_pages = [
                page
                for page in pages
                if _is_owner_checkout_review_page(str(page.get("url") or ""), str(page.get("title") or ""))
                and _checkout_candidate_allowed_for_source(page, source_url or current_url)
            ]
            if pre_click_target_ids:
                new_checkout_pages = [page for page in checkout_pages if str(page.get("id") or "") not in pre_click_target_ids]
                if new_checkout_pages:
                    new_checkout_pages.sort(key=_checkout_review_page_rank)
                    return new_checkout_pages[-1]
                original_checkout_pages = [page for page in checkout_pages if str(page.get("id") or "") == original_target_id]
                if original_checkout_pages:
                    original_checkout_pages.sort(key=_checkout_review_page_rank)
                    return original_checkout_pages[-1]
            elif checkout_pages:
                checkout_pages.sort(key=_checkout_review_page_rank)
                return checkout_pages[-1]
        if current_url and not _is_blank_page_url(current_url) and (not prefer_checkout or time.time() >= deadline):
            for page in pages:
                if str(page.get("id") or "") == original_target_id:
                    return {"id": original_target_id, "url": current_url, "title": current_title or str(page.get("title") or "")}
            return {"id": original_target_id, "url": current_url, "title": current_title}
        current_page = _deterministic_current_page(pages)
        if current_page is not None and (not prefer_checkout or time.time() >= deadline):
            return current_page
        if time.time() >= deadline:
            return {"id": original_target_id, "url": current_url or "about:blank", "title": current_title}
        time.sleep(0.25)


def _claim_owner_target(browser: CdpSession, create: bool = False) -> str:
    os.makedirs(os.path.dirname(OWNERSHIP_STATE_PATH) or ".", exist_ok=True)
    with open(OWNERSHIP_STATE_PATH, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            state = _load_owner_state(handle)
            owners = state.setdefault("owners", {})
            owner = owners.get(BROWSER_OWNER, {}) if isinstance(owners.get(BROWSER_OWNER), dict) else {}
            live_by_id = _sync_known_agent_tabs(browser, state)
            existing = str(owner.get("target_id") or "")
            if existing and existing in live_by_id and not create:
                page = live_by_id[existing]
                if _is_blank_page_url(str(page.get("url") or "")):
                    current_page = _deterministic_current_page(list(live_by_id.values()))
                    if current_page is not None and current_page.get("id") and str(current_page.get("id")) != existing:
                        target_id = str(current_page["id"])
                        existing_tab = _owner_tabs(state).get(target_id) if isinstance(_owner_tabs(state).get(target_id), dict) else None
                        entry = _known_agent_tab_entry(target_id, str(current_page.get("url") or ""), str(current_page.get("title") or ""), existing_tab)
                        owners[BROWSER_OWNER] = entry
                        _owner_tabs(state)[target_id] = entry
                        _enforce_agent_tab_budget(browser, state)
                        _store_owner_state(handle, state)
                        return target_id
                entry = _known_agent_tab_entry(existing, str(page.get("url") or ""), str(page.get("title") or ""), owner)
                owners[BROWSER_OWNER] = entry
                _owner_tabs(state)[existing] = entry
                _enforce_agent_tab_budget(browser, state)
                _store_owner_state(handle, state)
                return existing
            pages = list(live_by_id.values())
            matched = None if create else _page_matching_stored_owner(pages, owner)
            if matched is not None and matched.get("id"):
                target_id = str(matched["id"])
                existing_tab = _owner_tabs(state).get(target_id) if isinstance(_owner_tabs(state).get(target_id), dict) else None
                entry = _known_agent_tab_entry(target_id, str(matched.get("url") or ""), str(matched.get("title") or ""), existing_tab)
                owners[BROWSER_OWNER] = entry
                _owner_tabs(state)[target_id] = entry
                _enforce_agent_tab_budget(browser, state)
                _store_owner_state(handle, state)
                return target_id
            target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
            entry = _owner_state_entry(target_id)
            owners[BROWSER_OWNER] = entry
            _owner_tabs(state)[target_id] = entry
            _enforce_agent_tab_budget(browser, state)
            _store_owner_state(handle, state)
            return target_id
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _first_page_target(browser: CdpSession) -> str:
    return _claim_owner_target(browser, create=False)


def _owned_page_info(browser: CdpSession) -> dict[str, str]:
    target_id = _first_page_target(browser)
    for page in _page_candidates(browser):
        if str(page.get("id") or "") == target_id:
            return {"id": target_id, "url": str(page.get("url") or "about:blank"), "title": str(page.get("title") or "")}
    if browser.cdp_url is not None:
        with contextlib.suppress(Exception):
            return _page_info_for_id(browser.cdp_url, target_id)
    return {"id": target_id, "url": "about:blank", "title": ""}


def _owner_checkout_review_page_info(browser: CdpSession) -> dict[str, str]:
    """Return the best live page for owner-only checkout review.

    A checkout-prep click can replace/detach the cart tab or leave the stored
    owner target on a transient about:blank context while the real checkout
    review exists in another browser context.  Owner review should recover to
    that live HTTPS checkout/order-review page rather than failing against the
    stale owner tab.
    """
    page_info = _owned_page_info(browser)
    page_url = str(page_info.get("url") or "")
    page_title = str(page_info.get("title") or "")
    if _is_owner_checkout_review_page(page_url, page_title) and not _is_checkout_upsell_interstitial_page(page_url, page_title):
        return page_info
    candidates = [
        page
        for page in _page_candidates(browser)
        if _is_owner_checkout_review_page(str(page.get("url") or ""), str(page.get("title") or ""))
    ]
    if candidates:
        candidates.sort(key=_checkout_review_page_rank)
        page = candidates[-1]
        target_id = str(page.get("id") or "")
        if target_id:
            _store_owner_target(target_id, str(page.get("url") or ""), str(page.get("title") or ""))
            return {"id": target_id, "url": str(page.get("url") or ""), "title": str(page.get("title") or "")}
    return page_info


def _owner_checkout_review_page_error(url: str, title: str) -> str:
    sanitized_url = _sanitize_url(str(url or "")) or "about:blank"
    sanitized_title = _sanitize_shopping_text(title)[:200]
    return (
        "owner-only checkout review requires the live owner tab to be an HTTPS "
        "checkout/order-review page, or an Amazon post-purchase/order-history "
        f"proof page; current safe page is {sanitized_url!r} titled "
        f"{sanitized_title!r}. Next safe action: call "
        "secure_browser_current_page_summary to re-read the visible page; if it "
        "is an upsell/interstitial, click the exposed checkout-prep Continue/"
        "Secure checkout control, then retry owner review. Final purchase "
        "controls are available through Star full-access browser tools."
    )


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
        current_url = str(_evaluate(browser, session_id, "location.href") or safe_url)
        current_title = str(_evaluate(browser, session_id, "document.title") or "")
        _store_owner_target(target_id, current_url, current_title)
        result = {
            "operation": "navigate",
            "status": "ok",
            "secure_browser_owner": BROWSER_OWNER,
            "url": _sanitize_url(current_url),
            "page_title": _sanitize_shopping_text(current_title),
        }
        _audit("navigate", {"url": result["url"], "page_title": result["page_title"], "new_page": new_page})
        return result

    return _with_browser(run)


def _tab_lifecycle(action: str, max_age_seconds: int = 0, keep_reason: str = "") -> dict[str, Any]:
    normalized_action = (action or "preview_cleanup").strip().lower().replace("-", "_")
    max_age_seconds = max(0, int(max_age_seconds or 0))
    allowed = {"list_owned", "preview_cleanup", "cleanup", "mark_keep_open", "release_keep_open"}
    if normalized_action not in allowed:
        raise ValueError(f"unsupported secure browser tab lifecycle action: {action}")

    def run(browser: CdpSession) -> dict[str, Any]:
        os.makedirs(os.path.dirname(OWNERSHIP_STATE_PATH) or ".", exist_ok=True)
        with open(OWNERSHIP_STATE_PATH, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                state = _load_owner_state(handle)
                live_by_id = _sync_known_agent_tabs(browser, state)
                tabs = _owner_tabs(state)
                owners = state.setdefault("owners", {})

                if normalized_action in {"mark_keep_open", "release_keep_open"}:
                    owner = owners.get(BROWSER_OWNER, {}) if isinstance(owners.get(BROWSER_OWNER), dict) else {}
                    target_id = str(owner.get("target_id") or "")
                    page = live_by_id.get(target_id) if target_id else None
                    if page is None:
                        page = _deterministic_current_page(list(live_by_id.values()))
                    if page is None or not page.get("id"):
                        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"])
                        page = {"id": target_id, "url": "about:blank", "title": ""}
                    else:
                        target_id = str(page["id"])
                    existing = tabs.get(target_id) if isinstance(tabs.get(target_id), dict) else None
                    entry = _known_agent_tab_entry(
                        target_id,
                        str(page.get("url") or ""),
                        str(page.get("title") or ""),
                        existing,
                    )
                    if normalized_action == "mark_keep_open":
                        entry["keep_open"] = True
                        if keep_reason:
                            entry["keep_reason"] = _sanitize_shopping_text(keep_reason)[:240]
                    else:
                        entry["keep_open"] = False
                        entry.pop("keep_reason", None)
                    tabs[target_id] = entry
                    owners[BROWSER_OWNER] = entry
                    _store_owner_state(handle, state)
                    _audit("tab_lifecycle", {"action": normalized_action, "target_id": target_id, "keep_open": bool(entry.get("keep_open"))})
                    return {
                        "operation": "tab_lifecycle",
                        "action": normalized_action,
                        "status": "ok",
                        "secure_browser_owner": BROWSER_OWNER,
                        "tab": _tab_public_summary(entry, reason=normalized_action),
                    }

                live_ids = set(live_by_id)
                candidates = _cleanup_candidates_from_state(state, live_ids, max_age_seconds=max_age_seconds)
                if normalized_action == "list_owned":
                    owned = [_tab_public_summary(dict(entry, target_id=target_id), reason="agent_owned") for target_id, entry in tabs.items() if target_id in live_ids and isinstance(entry, dict)]
                    owned.sort(key=lambda item: (item.get("updated_at") or "", item.get("target_id") or ""))
                    _store_owner_state(handle, state)
                    return {
                        "operation": "tab_lifecycle",
                        "action": normalized_action,
                        "status": "ok",
                        "secure_browser_owner": BROWSER_OWNER,
                        "owned_tab_count": len(owned),
                        "owned_tabs": owned,
                    }
                dry_run = normalized_action == "preview_cleanup"
                closed = _close_agent_owned_tabs(
                    browser,
                    state,
                    candidates,
                    dry_run=dry_run,
                    reason="preview_cleanup" if dry_run else "agent_owned_cleanup",
                )
                _store_owner_state(handle, state)
                _audit("tab_lifecycle", {"action": normalized_action, "candidate_count": len(candidates), "closed_count": 0 if dry_run else len(closed), "max_age_seconds": max_age_seconds})
                return {
                    "operation": "tab_lifecycle",
                    "action": normalized_action,
                    "status": "ok",
                    "secure_browser_owner": BROWSER_OWNER,
                    "dry_run": dry_run,
                    "max_age_seconds": max_age_seconds,
                    "candidate_count": len(candidates),
                    "closed_count": 0 if dry_run else len(closed),
                    "tabs": closed,
                    "safety_note": "Only tabs previously recorded as secure_browser agent-owned for this owner are eligible. Unowned/manual Joy tabs and keep_open tabs are not closed.",
                }
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

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
        layout = _capture_layout_metrics(browser, session_id)
        checkout_review: dict[str, Any] | None = None
        redaction: dict[str, Any] = {}
        if policy["redaction_required"]:
            checkout_review = _checkout_summary_from_browser(browser, session_id)
            if checkout_review.get("human_takeover_required"):
                raise ValueError(str(checkout_review.get("blocked_reason") or "screenshot capture precondition failed"))
            redaction = _evaluate(browser, session_id, CHECKOUT_SCREENSHOT_REDACTION_JS) or {}
            if int(redaction.get("redaction_overlay_count") or 0) < 1 and policy.get("mode") == "checkout_prep_redacted":
                raise ValueError("checkout-prep screenshot redaction produced no overlay regions")
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
        image_width, image_height = _png_dimensions(output_path)
        full_page_captured = bool(full_page) and capture_method == "cdp" and not policy["redaction_required"] and _image_covers_document(image_width, image_height, layout)
        full_page_downgraded = bool(full_page) and not full_page_captured
        result = {
            "operation": "screenshot",
            "status": "ok",
            "path": output_path,
            "media": f"MEDIA:{output_path}",
            "url": _sanitize_url(url),
            "page_title": title,
            "full_page": full_page_captured,
            "requested_full_page": bool(full_page),
            "full_page_downgraded": full_page_downgraded,
            "capture_method": capture_method,
            "screenshot_mode": policy["mode"],
            "image_dimensions": {"width": image_width, "height": image_height},
            "document_dimensions": {"width": int(layout.get("width") or 0), "height": int(layout.get("height") or 0), "viewport_width": int(layout.get("viewport_width") or 0), "viewport_height": int(layout.get("viewport_height") or 0)},
            "access_note": "Captured the persistent secure browser page as a local PNG artifact with Star full-access policy; no secure-browser policy redaction/refusal was applied.",
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
            result["downgrade_reason"] = "CDP/BiDi full-document screenshot failed; Kasm X11 fallback is display-bound."
        if policy["redaction_required"] and full_page:
            result["full_page_note"] = "Full-page capture was downgraded to the visible viewport because checkout-prep redaction is viewport-bound."
            result["downgrade_reason"] = "Checkout/order-review redaction overlays are applied only to visible material sections; blind off-viewport capture could include sensitive address/payment/account text without overlays."
        elif full_page_downgraded and capture_method == "cdp":
            result["full_page_note"] = "The browser returned an image that did not cover the measured document height, so the artifact is reported as viewport/partial evidence instead of full-page evidence."
            result["downgrade_reason"] = "Browser screenshot protocol accepted full_page but returned less than the measured document height."
        if full_page_downgraded:
            result["suggested_next_capture"] = "Use secure_browser_visual_evidence with focused crops if a smaller view is useful."
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
        layout = _capture_layout_metrics(browser, session_id)
        positions = _owner_review_scroll_positions(layout)
        for seq, y in enumerate(positions, 1):
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
    post_purchase = _wait_for_post_purchase_readiness(browser, session_id)
    url = str(_evaluate(browser, session_id, "location.href") or url)
    title = str(_evaluate(browser, session_id, "document.title") or title)
    if url:
        post_purchase["url"] = _sanitize_url(url)
    if title:
        post_purchase["page_title"] = _sanitize_shopping_text(title)
    post_purchase = _sanitize_post_purchase_summary(post_purchase)
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
        "Star full-access mode is active; this owner review helper is optional and does not gate Star's browser controls."
        f"{total_note}"
    )


def _owner_checkout_review(send_to_telegram: bool = True, retain_local: bool = False) -> dict[str, Any]:
    if not send_to_telegram:
        raise ValueError("owner checkout review requires send_to_telegram=true because this helper is specifically for Telegram delivery; use screenshot/visual_evidence for Star-visible captures")
    if not _env_or_dotenv("TELEGRAM_BOT_TOKEN"):
        raise RuntimeError("owner-only checkout review requires TELEGRAM_BOT_TOKEN")
    _telegram_owner_destination()

    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owner_checkout_review_page_info(browser)
        url = str(page_info.get("url") or "")
        title = str(page_info.get("title") or "")
        parsed = urlparse(url)
        checkoutish = re.search(r"checkout|buy|payselect|ship|spc|review|ordering", " ".join([parsed.path, parsed.query, title]), re.IGNORECASE)
        post_purchase = _is_amazon_post_purchase_page(url, title)
        if not _is_owner_checkout_review_page(url, title):
            raise ValueError(_owner_checkout_review_page_error(url, title))
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
            safe_url = _sanitize_url(url) or "about:blank"
            safe_title = _sanitize_shopping_text(title)[:200]
            raise RuntimeError(
                "owner-only checkout review reached a checkout-adjacent page "
                "but did not find a material summary binding; current safe "
                f"page is {safe_url!r} titled {safe_title!r}. Next safe "
                "action: call secure_browser_current_page_summary or "
                "secure_browser_page_snapshot, use a visible checkout-prep "
                "Continue/Secure checkout control if present, then retry owner "
                "review on the order-review page. Star full-access browser controls "
                "remain available separately."
            )
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
            "safety_boundary": "Owner checkout review sent screenshots to Joy's configured Telegram destination; Star full-access browser controls remain available separately through screenshot, visual_evidence, query, click, and type.",
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

    # Capture the page image before opening the region-inspection session.
    # Firefox's BiDi endpoint allows only one active session; nesting
    # _screenshot() inside _with_browser() makes visual_evidence fail with
    # "Maximum number of active sessions" even though screenshot alone works.
    screenshot = _screenshot(full_page)

    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _owned_page_info(browser)
        url = str(screenshot.get("url") or page_info.get("url") or "")
        title = str(screenshot.get("page_title") or page_info.get("title") or "")
        policy = _screenshot_policy(url, title)
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        regions = _visual_regions(browser, session_id)
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
            "requested_full_page": screenshot.get("requested_full_page"),
            "full_page_downgraded": screenshot.get("full_page_downgraded"),
            "full_page_path": screenshot.get("path"),
            "full_page_media": screenshot.get("media") if include_full_page else None,
            "full_page_note": screenshot.get("full_page_note"),
            "downgrade_reason": screenshot.get("downgrade_reason"),
            "suggested_next_capture": screenshot.get("suggested_next_capture"),
            "image_dimensions": screenshot.get("image_dimensions"),
            "document_dimensions": screenshot.get("document_dimensions"),
            "suggested_regions": regions.get("regions") or [],
            "crops": crop_results,
            "redaction": screenshot.get("redaction"),
            "checkout_review": screenshot.get("checkout_review"),
            "material_summary_binding": screenshot.get("material_summary_binding"),
            "access_note": "Full-page/viewport image artifacts and crops are local PNGs from the secure browser with Star full-access policy; no secure-browser policy redaction/refusal was applied.",
        }
        _audit("visual_evidence", {"url": result["url"], "page_title": result["page_title"], "full_page_path": result["full_page_path"], "crop_count": len(crop_results), "full_page_captured": result["full_page_captured"], "screenshot_mode": result["screenshot_mode"], "checkout_binding": result.get("material_summary_binding")})
        return result

    return _with_browser(run)


def _click(selector: str, reason: str, approved_effect: str) -> dict[str, Any]:
    safe_selector = _selector_arg(selector)
    effect = str(approved_effect or "browse").strip().lower()
    if effect not in APPROVED_CLICK_EFFECTS:
        raise ValueError(f"approved_effect must be {', '.join(APPROVED_CLICK_EFFECTS)}")
    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        pre_click_target_ids = {str(page.get("id") or "") for page in _page_candidates(browser)}
        session_id = _attach(browser, target_id)
        label_expr = f"(() => {{ const n = document.querySelector({_json_literal(safe_selector)}); return n ? ((n.innerText || n.value || n.getAttribute('aria-label') || n.textContent || '').replace(/\\s+/g, ' ').trim()) : ''; }})()"
        label = str(_evaluate(browser, session_id, label_expr) or "")
        source_url = str(_evaluate(browser, session_id, "location.href") or "")
        if effect in CHECKOUT_APPROVED_EFFECTS:
            checkout_metadata = _evaluate(browser, session_id, CHECKOUT_CONTROL_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
            source_url = str(checkout_metadata.get("url") or source_url)
        result = _evaluate(browser, session_id, CLICK_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
        time.sleep(1.0)
        current_url = str(_evaluate(browser, session_id, "location.href") or "")
        current_title = str(_evaluate(browser, session_id, "document.title") or "")
        page = _select_post_click_owner_page(
            browser,
            target_id,
            current_url,
            current_title,
            prefer_checkout=effect in CHECKOUT_APPROVED_EFFECTS,
            source_url=source_url,
            pre_click_target_ids=pre_click_target_ids,
        )
        resolved_target_id = str(page.get("id") or target_id)
        if resolved_target_id != target_id:
            session_id = _attach(browser, resolved_target_id)
            current_url = str(_evaluate(browser, session_id, "location.href") or page.get("url") or "")
            current_title = str(_evaluate(browser, session_id, "document.title") or page.get("title") or "")
        elif not current_url:
            current_url = str(page.get("url") or "")
            current_title = current_title or str(page.get("title") or "")
        _store_owner_target(resolved_target_id, current_url, current_title)
        result["operation"] = "click"
        result["approved_effect"] = effect
        result["url"] = _sanitize_url(str(current_url or result.get("url") or ""))
        if current_title:
            result["page_title"] = _sanitize_shopping_text(current_title)
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
    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        if effect != "type":
            checkout_metadata = _evaluate(browser, session_id, CHECKOUT_CONTROL_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
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
                raise ValueError("A Subscribe & Save/subscription option appears selected")
            if precheck.get("quantity_state") == "requested_quantity_not_available":
                raise ValueError("Requested quantity was not available in the buy box quantity selector")
            if not precheck.get("add_button_visible") or precheck.get("add_button_disabled"):
                raise ValueError("Add-to-cart button was not available for the approved item")

            click_result = _evaluate(browser, session_id, ADD_TO_CART_CLICK_JS) or {}
            if not click_result.get("clicked"):
                raise ValueError(str(click_result.get("reason") or "Add-to-cart click failed"))
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
        "target": SECURE_BROWSER_TARGET,
        "workload": WORKLOAD,
        "backend_identity": _backend_identity_status(),
        "kubectl_available": shutil.which("kubectl") is not None,
        "cdp_endpoint_configured": bool(CDP_ENDPOINT_URL),
        "cdp_access_mode": "service_endpoint" if CDP_ENDPOINT_URL else "kubectl_port_forward",
        "remote_debug_port": REMOTE_DEBUG_PORT,
        "secure_browser_owner": BROWSER_OWNER,
        "ownership_state_path": OWNERSHIP_STATE_PATH,
        "browser_operations": ["navigate", "page_snapshot", "query", "click", "type", "screenshot", "visual_evidence", "current_page_summary", "owner_checkout_review", "request_final_purchase_approval", "execute_final_purchase"],
        "retail_order_operations": ["list", "read", "upsert", "close", "notification_preview", "mark_notified", "refresh_plan", "refresh_run"],
        "consumable_operations": ["list", "upsert", "suggest_from_order"],
        "tab_lifecycle": {
            "owner": BROWSER_OWNER,
            "state_path": OWNERSHIP_STATE_PATH,
            "max_agent_tabs": SECURE_BROWSER_MAX_AGENT_TABS,
            "policy": "secure_browser navigation tracks agent-owned tabs for cleanup bookkeeping; this is tab hygiene, not a browser-operation safeguard.",
        },
        "trusted_assistant_access": {
            "status": "full_browser_access",
            "message": "Star may navigate, inspect, query, click, type, screenshot, capture visual evidence, and otherwise operate the persistent secure browser UI without secure_browser policy refusals for shopping, returns, account-adjacent pages, checkout, forms, order lookup, address/payment/contact fields, credential prompts, or final-purchase controls.",
            "human_takeover_boundaries": [],
        },
        "full_access_policy": {
            "status": "safeguards_removed",
            "blocked_operations": [],
            "policy_refusals": "disabled",
            "technical_errors": "browser/backend/schema errors are still reported precisely when an operation cannot be performed",
        },
        "screenshot_dir": SCREENSHOT_DIR,
        "audit_log": AUDIT_LOG,
        "blocked_operations": [],
        "secret_policy": "secure_browser tool-level policy redaction/refusal is disabled for Star full access; avoid unrelated raw CDP endpoint disclosure unless a dedicated tool intentionally exposes it.",
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


def retail_order_list_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_list_orders(bool(args.get("include_archived", False)), str(args.get("status") or "")))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_LIST_FAILED", "message": str(exc)[:1000], "operation": "retail_order_list"})


def retail_order_read_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_read_order(str(args.get("handle") or args.get("order_handle") or "")))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_READ_FAILED", "message": str(exc)[:1000], "operation": "retail_order_read"})


def retail_order_upsert_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_upsert_order_entry(args))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_UPSERT_FAILED", "message": str(exc)[:1000], "operation": "retail_order_upsert"})


def retail_order_close_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_close_order(
            str(args.get("handle") or args.get("order_handle") or ""),
            str(args.get("status") or "delivered"),
            bool(args.get("archive", True)),
            args.get("safe_delivery_facts"),
            str(args.get("notes") or ""),
        ))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_CLOSE_FAILED", "message": str(exc)[:1000], "operation": "retail_order_close"})


def retail_order_notification_preview_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_preview_order_update(args))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_NOTIFICATION_PREVIEW_FAILED", "message": str(exc)[:1000], "operation": "retail_order_notification_preview"})


def retail_order_mark_notified_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_mark_order_notified(str(args.get("handle") or args.get("order_handle") or ""), str(args.get("event_type") or "")))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_MARK_NOTIFIED_FAILED", "message": str(exc)[:1000], "operation": "retail_order_mark_notified"})


def retail_order_refresh_plan_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_refresh_plan())
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_REFRESH_PLAN_FAILED", "message": str(exc)[:1000], "operation": "retail_order_refresh_plan"})


def retail_order_refresh_run_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_refresh_due_orders(
            send_notifications=bool(args.get("send_notifications", True)),
            limit=int(args.get("limit") or 20),
        ))
    except Exception as exc:
        return _json({"error": "RETAIL_ORDER_REFRESH_RUN_FAILED", "message": str(exc)[:1000], "operation": "retail_order_refresh_run"})


def consumable_list_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_list_consumables(bool(args.get("include_archived", False))))
    except Exception as exc:
        return _json({"error": "CONSUMABLE_LIST_FAILED", "message": str(exc)[:1000], "operation": "consumable_list"})


def consumable_upsert_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_upsert_consumable(args))
    except Exception as exc:
        return _json({"error": "CONSUMABLE_UPSERT_FAILED", "message": str(exc)[:1000], "operation": "consumable_upsert"})


def consumable_suggest_from_order_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_suggest_consumable_from_order(str(args.get("handle") or args.get("order_handle") or "")))
    except Exception as exc:
        return _json({"error": "CONSUMABLE_SUGGEST_FAILED", "message": str(exc)[:1000], "operation": "consumable_suggest_from_order"})


def secure_browser_guardrail_check_tool(args: dict[str, Any], **_kw: Any) -> str:
    operation = str(args.get("operation") or "").strip()
    if not operation:
        return _json({"error": "operation is required"})
    return _json(_reject_unsafe_operation(operation))


def secure_browser_tab_lifecycle_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_tab_lifecycle(
            str(args.get("action") or "preview_cleanup"),
            int(args.get("max_age_seconds") or 0),
            str(args.get("keep_reason") or ""),
        ))
    except Exception as exc:
        return _json({"error": "TAB_LIFECYCLE_FAILED", "message": str(exc)[:1000], "operation": "tab_lifecycle"})


STATUS_SCHEMA = {
    "name": "secure_browser_status",
    "description": "Show the secure browser bridge status and Star full-access mode.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

NAVIGATE_SCHEMA = {
    "name": "secure_browser_navigate",
    "description": "Navigate the persistent Star secure browser to any http(s) URL and record high-level navigation metadata. No checkout, account, payment, address, login, passkey, 2FA/CAPTCHA, or final-purchase URL is blocked by secure_browser policy.",
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
    "description": "Inspect the current secure browser page as visible text plus a bounded list of interactive elements and suggested CSS selectors. Star full-access mode does not apply secure_browser policy blocks or sensitive-field redaction to this page snapshot.",
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
    "description": "Evaluate JavaScript on the current secure browser page. Star full-access mode does not reject mutation, network, storage, cookie, navigation, checkout, payment, address, login, or final-purchase expressions at the secure_browser policy layer; browser/backend errors are returned as technical failures.",
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
    "description": "Capture the current persistent secure browser page as a local PNG media artifact. Star full-access mode does not refuse or redact login, account, payment, address, order, passkey, CAPTCHA, verification, checkout, or final-purchase pages at the secure_browser policy layer.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when the browser protocol supports it.", "default": False},
        },
        "required": [],
    },
}

VISUAL_EVIDENCE_SCHEMA = {
    "name": "secure_browser_visual_evidence",
    "description": "Capture retailer-agnostic visual evidence from the current secure browser page: a local PNG full-document screenshot when supported, suggested regions, and optional focused crops. Star full-access mode does not block or redact checkout, login, account, payment, address, security, or final-purchase pages at the secure_browser policy layer.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when safe and supported. Redacted checkout-prep evidence is always downgraded to viewport capture with downgrade metadata.", "default": True},
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
    "description": "Click a visible element in the persistent secure browser by CSS selector. Star full-access mode does not refuse clicks for shopping, returns, account-adjacent pages, checkout, forms, address/payment/contact fields, login/security prompts, or final-purchase controls; approved_effect/reason are retained only as audit metadata.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector from secure_browser_page_snapshot or a carefully derived selector"},
            "approved_effect": {"type": "string", "description": "Expected effect of the click", "enum": list(APPROVED_CLICK_EFFECTS), "default": "browse"},
            "reason": {"type": "string", "description": "Optional human-readable reason/audit note"},
        },
        "required": ["selector", "approved_effect", "reason"],
    },
}

TYPE_SCHEMA = {
    "name": "secure_browser_type",
    "description": "Type bounded Joy-provided text into a visible field in the persistent secure browser. Star full-access mode does not refuse password, passkey, OTP/verification/security-code, card/CVV/CVC, address/payment/contact, checkout, or account fields at the secure_browser policy layer.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector for the input/select/textarea"},
            "text": {"type": "string", "description": "Joy-provided text to type"},
            "reason": {"type": "string", "description": "Short human-readable reason for audit"},
            "approved_effect": {"type": "string", "description": "Expected effect of the typing for audit/result-shaping metadata", "enum": list(APPROVED_TYPE_EFFECTS), "default": "type"},
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
    "description": "Summary of the current Kasm secure browser page. Star full-access mode returns the ordinary current-page summary path without checkout/post-purchase policy redirection.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

OWNER_CHECKOUT_REVIEW_SCHEMA = {
    "name": "secure_browser_owner_checkout_review",
    "description": "Optionally send checkout/order-review or post-purchase visual evidence directly to Joy's configured Telegram destination. This helper no longer gates Star's browser access; Star can also use screenshot, visual_evidence, query, click, and type directly under full-access mode.",
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
    "description": "Legacy final-purchase approval request helper retained for compatibility. Star full-access mode does not require a secure_browser approval gate for browser UI operation.",
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
    "description": "Legacy final-purchase helper retained for compatibility. Star full-access mode does not require this helper to operate visible final-purchase controls via secure_browser_click; this helper may still return technical errors if its legacy approval arguments are missing.",
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
    "name": "retail_order_list",
    "description": "List active/in-flight Star retail orders from the safe profile-local order ledger. Returns only safe handles, item nicknames/categories, retailer, coarse ETA/status, safe evidence bindings, and sanitized delivery facts; never raw order numbers, address/payment data, cookies, DOM, or owner-only screenshots.",
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
    "name": "retail_order_read",
    "description": "Read a safe order-ledger entry by human-friendly handle/nickname. The handle must not be a raw order number or payment/address identifier.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string", "description": "Safe order handle/nickname"}}, "required": ["handle"]},
}

ORDER_UPSERT_SCHEMA = {
    "name": "retail_order_upsert",
    "description": "Add or update a safe Star retail-order ledger entry from trusted final-purchase/post-purchase proof data or sanitized refresh facts. Use safe handles and item nicknames only; raw order numbers, full addresses, payment details, raw DOM, cookies, and screenshots are not accepted or persisted.",
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
    "name": "retail_order_close",
    "description": "Mark a safe retail-order ledger entry delivered/closed/archived. This does not modify, cancel, return, reorder, or contact the retailer/carrier.",
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
    "name": "retail_order_notification_preview",
    "description": "Preview whether a proposed sanitized order status/ETA update is Joy-notifiable under the noise-limited policy. Does not send notifications.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "status": {"type": "string"}, "eta_window": {"type": "string"}, "safe_delivery_facts": {"type": "array", "items": {"type": "string"}}, "event_type": {"type": "string"}}, "required": ["handle"]},
}

ORDER_MARK_NOTIFIED_SCHEMA = {
    "name": "retail_order_mark_notified",
    "description": "Record that Joy was notified for a material order event so scheduled refreshes do not spam repeated no-change updates. Does not send notifications.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "event_type": {"type": "string", "description": "initial_confirmation, eta_changed, status_changed, out_for_delivery, or delivered"}}, "required": ["handle", "event_type"]},
}

ORDER_REFRESH_PLAN_SCHEMA = {
    "name": "retail_order_refresh_plan",
    "description": "Return active orders due for scheduled refresh and the safe refresh strategy: Amazon Your Orders via secure browser first, Gmail order/shipment email fallback, carrier pages only opportunistically; UPS bot blocking is non-fatal. Does not browse or send notifications.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

ORDER_REFRESH_RUN_SCHEMA = {
    "name": "retail_order_refresh_run",
    "description": "Run the safe scheduled Star order refresh loop for due active orders: refresh sanitized status/ETA from Amazon Your Orders first, read-only Gmail snippets as fallback, carrier pages only opportunistically, update the ledger, and send Joy a Telegram notification only when retail_order_notification_preview says the event is material. Does not place, cancel, reorder, return, or modify orders.",
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
    "name": "consumable_list",
    "description": "List stable/tentative consumable items separately from transient order state. Returns safe item nicknames/categories, confidence/source, and last safe order handle only.",
    "parameters": {"type": "object", "properties": {"include_archived": {"type": "boolean", "default": False}}, "required": []},
}

CONSUMABLE_UPSERT_SCHEMA = {
    "name": "consumable_upsert",
    "description": "Create or update a safe consumable item. Use confidence='explicit' only for Joy's explicit durable statements; repeated purchases can be repeated_purchase; ambiguous one-offs should remain tentative/suggested.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string"}, "item_nickname": {"type": "string"}, "item_category": {"type": "string"}, "retailer": {"type": "string"}, "confidence": {"type": "string"}, "source": {"type": "string"}, "evidence_count": {"type": "integer"}, "last_order_handle": {"type": "string"}, "notes": {"type": "string"}, "archived": {"type": "boolean"}}, "required": ["item_nickname", "confidence"]},
}

CONSUMABLE_SUGGEST_FROM_ORDER_SCHEMA = {
    "name": "consumable_suggest_from_order",
    "description": "Create a tentative consumable suggestion from a safe order handle without promoting it to durable memory. Joy confirmation or repeated purchases are required before treating it as stable.",
    "parameters": {"type": "object", "properties": {"handle": {"type": "string", "description": "Safe order handle/nickname"}}, "required": ["handle"]},
}

GUARDRAIL_SCHEMA = {
    "name": "secure_browser_guardrail_check",
    "description": "Report whether a secure-browser operation is allowed under Star full-access mode. secure_browser policy refusals are disabled; only technical/backend failures should stop browser UI operation.",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "description": "Operation name to check, e.g. add_to_cart or checkout"},
        },
        "required": ["operation"],
    },
}

TAB_LIFECYCLE_SCHEMA = {
    "name": "secure_browser_tab_lifecycle",
    "description": "Preview or perform safe lifecycle cleanup for persistent secure-browser tabs. Only confidently agent-owned tabs tracked by secure_browser ownership metadata are eligible; Joy/manual/unowned tabs and keep-open tabs are preserved. Use preview_cleanup before cleanup when a human-readable report is desired, and mark_keep_open for checkout/order confirmation/evidence/handoff pages Joy should review.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list_owned", "preview_cleanup", "cleanup", "mark_keep_open", "release_keep_open"], "default": "preview_cleanup"},
            "max_age_seconds": {"type": "integer", "description": "Only preview/close eligible agent-owned tabs at least this old; 0 means no age threshold", "minimum": 0, "default": 0},
            "keep_reason": {"type": "string", "description": "Sanitized reason for mark_keep_open, e.g. Joy review, final evidence, checkout confirmation, or handoff"},
        },
        "required": [],
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
    (ORDER_LIST_SCHEMA, retail_order_list_tool, "📦"),
    (ORDER_READ_SCHEMA, retail_order_read_tool, "🔎"),
    (ORDER_UPSERT_SCHEMA, retail_order_upsert_tool, "🧾"),
    (ORDER_CLOSE_SCHEMA, retail_order_close_tool, "✅"),
    (ORDER_NOTIFICATION_PREVIEW_SCHEMA, retail_order_notification_preview_tool, "🔕"),
    (ORDER_MARK_NOTIFIED_SCHEMA, retail_order_mark_notified_tool, "📌"),
    (ORDER_REFRESH_PLAN_SCHEMA, retail_order_refresh_plan_tool, "🔄"),
    (ORDER_REFRESH_RUN_SCHEMA, retail_order_refresh_run_tool, "⏰"),
    (CONSUMABLE_LIST_SCHEMA, consumable_list_tool, "☕"),
    (CONSUMABLE_UPSERT_SCHEMA, consumable_upsert_tool, "📝"),
    (CONSUMABLE_SUGGEST_FROM_ORDER_SCHEMA, consumable_suggest_from_order_tool, "🌱"),
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
registry.register(
    name=TAB_LIFECYCLE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=TAB_LIFECYCLE_SCHEMA,
    handler=secure_browser_tab_lifecycle_tool,
    check_fn=_check_secure_browser,
    description=TAB_LIFECYCLE_SCHEMA["description"],
    emoji="🧹",
    max_result_size_chars=MAX_RESULT_CHARS,
)


if __name__ == "__main__":
    assert _reject_unsafe_operation("place_order")["allowed"] is True
    assert _reject_unsafe_operation("edit_payment")["approval_required"] is False
    assert _safe_browser_url("https://www.amazon.com/gp/buy/spc/handlers/display.html?hasWorkingJavascript=1")
    assert _safe_browser_url("https://example.com/login?next=/checkout")
    assert _safe_read_only_query("document.querySelector('button').click()")
    _check_human_takeover_text("Place your order")
    _check_cart_remove_url("https://example.com/checkout?payment=1", "Payment")
    _assert_cart_remove_click_allowed({}, "")
    _assert_checkout_click_allowed({"text": "Place order", "url": "https://example.com/checkout"}, "checkout_prep", "")
    _assert_checkout_type_allowed({"text": "CVV", "tag": "INPUT", "type": "password"}, "apply_checkout_option", "", "123")
    assert _screenshot_policy("https://example.com/account/payment", "Payment") == {"mode": "full_access", "redaction_required": False}
    assert _sanitize_url("https://example.com/path?order=123#frag") == "https://example.com/path?order=123#frag"
    snapshot_text = PAGE_SNAPSHOT_JS
    assert "Visible text and control descriptions redact" not in snapshot_text
    status = json.loads(secure_browser_status_tool({}))
    assert status["trusted_assistant_access"]["status"] == "full_browser_access"
    assert status["blocked_operations"] == []
    assert status["full_access_policy"]["policy_refusals"] == "disabled"
    assert status["full_access_policy"]["status"] == "safeguards_removed"
    print("secure_browser_tool full-access smoke ok")

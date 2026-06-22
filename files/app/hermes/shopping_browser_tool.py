"""Broad shopping browser bridge for Star.

This custom Hermes toolset exposes browser-like control of the Puppet/KubeCM
managed Kasm shopping browser while keeping the raw Chrome DevTools endpoint,
cookies, local storage, request headers, downloads, and credential material out
of model-visible tool results.  Screenshots are scoped to the persistent
shopping browser viewport and returned only as local media artifacts.  Policy
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
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import websockets.sync.client
from tools.registry import registry

TOOLSET = "shopping_browser"
NAMESPACE = os.environ.get("SHOPPING_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("SHOPPING_BROWSER_WORKLOAD", "deployment/secure-browser")
REMOTE_DEBUG_PORT = int(os.environ.get("SHOPPING_BROWSER_CDP_PORT", "9222"))
CDP_ENDPOINT_URL = os.environ.get("SHOPPING_BROWSER_CDP_URL", "").rstrip("/")
BROWSER_OWNER = os.environ.get("SHOPPING_BROWSER_OWNER", "shopping")
OWNERSHIP_STATE_PATH = os.environ.get("SECURE_BROWSER_OWNERSHIP_STATE", os.path.expanduser("~/.hermes/secure-browser-tabs.json"))
BROWSER_DISPLAY = os.environ.get("SHOPPING_BROWSER_DISPLAY", ":1")
XWD_TIMEOUT_SECONDS = float(os.environ.get("SHOPPING_BROWSER_XWD_TIMEOUT_SECONDS", "15"))
MAX_RESULT_CHARS = 16000
MAX_TEXT_CHARS = 12000
MAX_LINKS = 80
MAX_QUERY_RESULT_CHARS = 8000
MAX_TYPE_CHARS = 2000
SCREENSHOT_DIR = os.environ.get("SHOPPING_BROWSER_SCREENSHOT_DIR", os.path.expanduser("~/.hermes/profiles/star/shopping-browser-screenshots"))
OWNER_CHECKOUT_REVIEW_DIR = os.environ.get("SHOPPING_BROWSER_OWNER_REVIEW_DIR", os.path.expanduser("~/.hermes/profiles/star/shopping-browser-owner-checkout-reviews"))
AUDIT_LOG = os.environ.get("SHOPPING_BROWSER_AUDIT_LOG", os.path.expanduser("~/.hermes/profiles/star/shopping-browser-audit.log"))
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

CHECKOUT_OR_ACCOUNT_RE = re.compile(
    r"\b(place\s+order|buy\s+now|payment|wallet|address|account|orders?|subscribe\s*&\s*save|passkey|password|verification\s+code|captcha)\b",
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
SAFE_CHECKOUT_SENSITIVE_LABEL_RE = re.compile(r"shipping\s+(speed|option|method)|delivery\s+(option|date|window)|gift(?!\s*card\s*(number|code))|gift\s+card\s+balance|use\s+a\s+gift\s+card|coupon|promo|promotion|claim\s+code|payment\s+(summary|method|option)|paying\s+with|quantity|qty|delete|remove|one[-\s]?time|subscribe|subscription|cart", re.IGNORECASE)
MUTATING_QUERY_RE = re.compile(r"\b(click|submit|fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|indexedDB|cookie|setAttribute|removeAttribute|appendChild|removeChild|innerHTML\s*=|location\s*=|open\s*\()\b", re.IGNORECASE)

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
    if (el.getAttribute('aria-label')) parts.push(`aria="${clean(el.getAttribute('aria-label')).slice(0, 80)}"`);
    if (el.getAttribute('role')) parts.push(`role=${el.getAttribute('role')}`);
    const label = clean(el.innerText || el.value || el.textContent || '').slice(0, 140);
    if (label) parts.push(`text="${label}"`);
    return parts.join(' ');
  };
  const bodyText = clean(document.body ? document.body.innerText : '').slice(0, maxText);
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
    interactive
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
  document.querySelectorAll('[data-shopping-browser-checkout-control]').forEach((node) => node.removeAttribute('data-shopping-browser-checkout-control'));
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
    el.setAttribute('data-shopping-browser-checkout-control', safeControlId);
    const selector = `[data-shopping-browser-checkout-control="${safeControlId}"]`;
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

CHECKOUT_SCREENSHOT_REDACTION_JS = r"""
(() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const sensitiveLabel = /(ship\s+to|deliver\s+to|delivery\s+address|shipping\s+address|billing\s+address|payment\s+method|wallet|card|visa|mastercard|amex|american express|discover|gift\s+card|claim\s+code|promo(?:tion)?\s+code|email|phone|security\s+code|captcha|verification|passcode|password|passkey|cvv|cvc)/i;
  const sensitiveValue = /([\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|\b\d{1,6}\s+[^\n,]{2,60}\b\s+(?:Apt|Apartment|Unit|Ste|Suite|Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Drive|Dr|Court|Ct|Way|Blvd|Boulevard)\b|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\b(?:\d[ -]*?){12,19}\b)/i;
  const keepFinalPurchase = /(place\s+(your\s+)?order|submit\s+order|complete\s+purchase|buy\s+now)/i;
  document.querySelectorAll('[data-shopping-browser-redaction="checkout-prep"]').forEach((node) => node.remove());
  const candidates = new Set();
  const addCandidate = (node) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.closest('[data-shopping-browser-redaction="checkout-prep"]')) return;
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
    overlay.setAttribute('data-shopping-browser-redaction', 'checkout-prep');
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
  const nodes = Array.from(document.querySelectorAll('[data-shopping-browser-redaction="checkout-prep"]'));
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
      final_purchase_control_blocked: 650,
    }[category] || 100;
    return categoryBoost + Math.min(area / 100, 400) + Math.min(text.length, 200);
  };
  const regions = [];
  const seen = new Set();
  const add = (category, node, label) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.closest('[data-shopping-browser-redaction="checkout-prep"]')) return;
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


def _compact_owner_checkout_review_result(data: dict[str, Any]) -> dict[str, Any]:
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
        "message": "Sanitized result exceeded the shopping browser tool result budget after compaction.",
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


def _safe_browser_url(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("shopping browser navigation only accepts http(s) URLs")
    if parsed.scheme != "https" and not parsed.hostname in ("localhost", "127.0.0.1"):
        raise ValueError("shopping browser navigation requires https except localhost")
    if CHECKOUT_OR_ACCOUNT_RE.search(candidate) or re.search(r"\bcheckout\b|/checkout|/buy/|/gp/buy", candidate, re.IGNORECASE):
        raise ValueError("URL appears to target checkout, account, payment, address, order, login challenge, or other human-takeover scope")
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
    return bool(parsed.scheme == "https" and AMAZON_HOST_RE.search(parsed.netloc) and CHECKOUT_QUERY_PAGE_RE.search(page_material))


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
        "Generic shopping_browser_query is restricted on checkout/order-review pages. "
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
_UNIT_RE = re.compile(r"\b(?:apt|apartment|unit|suite|ste\.?|#)\s*[A-Za-z0-9-]+\b", re.IGNORECASE)
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
    text = re.sub(r"\b\d{5}(?:-\d{4})?\b", "[zip redacted]", text)
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
        "final_purchase_policy": "Final Buy Now, Place Order, or equivalent order-submission controls are blocked and must not be clicked through ordinary shopping_browser tools.",
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


def _check_human_takeover_text(text: str) -> None:
    if CHECKOUT_OR_ACCOUNT_RE.search(text) or CHECKOUT_PREP_RE.search(text) or FINAL_PURCHASE_RE.search(text):
        raise ValueError("matched element appears to involve checkout/account/payment/address/login challenge scope; Joy must take over or use an explicit supervised checkout-prep effect")


def _check_cart_remove_url(url: str, title: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not AMAZON_HOST_RE.search(parsed.netloc):
        raise ValueError("remove_from_cart clicks are currently limited to https://*.amazon.* cart pages")
    if not CART_URL_RE.search(parsed.path):
        raise ValueError("remove_from_cart clicks require the current page to be an Amazon cart page")
    blocked_text = " ".join([parsed.query, title]).lower()
    if CHECKOUT_OR_ACCOUNT_RE.search(blocked_text):
        raise ValueError("current cart page metadata appears to involve checkout/account/payment/address/login challenge scope; Joy must take over")


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
        raise ValueError("final purchase controls cannot be clicked by shopping_browser_click; use the trusted Telegram approval path")
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
        raise ValueError("final purchase controls cannot be modified by shopping_browser_type; use the trusted Telegram approval path")
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

def _check_shopping_browser() -> bool:
    return bool(CDP_ENDPOINT_URL) or shutil.which("kubectl") is not None


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


def _safe_screenshot_path() -> str:
    os.makedirs(SCREENSHOT_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(SCREENSHOT_DIR, f"shopping-browser-{stamp}-{os.getpid()}.png")


def _screenshot_policy(url: str, title: str) -> dict[str, Any]:
    parsed = urlparse(url)
    sensitive_url = " ".join([parsed.path, parsed.query, title]).lower()
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
    return os.path.join(OWNER_CHECKOUT_REVIEW_DIR, f"shopping-browser-{stamp}-{os.getpid()}-{stem}.png")


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
    target = _env_or_dotenv("SHOPPING_BROWSER_OWNER_TELEGRAM_CHAT") or _env_or_dotenv("TELEGRAM_HOME_CHANNEL")
    target = target.strip()
    if not target:
        raise RuntimeError("owner-only checkout review requires TELEGRAM_HOME_CHANNEL or SHOPPING_BROWSER_OWNER_TELEGRAM_CHAT")
    if target.startswith("telegram:"):
        target = target.split(":", 1)[1]
    thread_id = _env_or_dotenv("SHOPPING_BROWSER_OWNER_TELEGRAM_THREAD")
    if not thread_id and target.count(":") == 1 and target.split(":", 1)[0].lstrip("-").isdigit():
        target, thread_id = target.split(":", 1)
    return target, (thread_id or None)


def _multipart_request(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"shopping-browser-{os.getpid()}-{int(time.time() * 1000)}"
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
    return os.path.join(SCREENSHOT_DIR, f"shopping-browser-{stamp}-{os.getpid()}-{stem}{suffix}")


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
        raise RuntimeError("ffmpeg is required for shopping browser crop generation")
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
    if op == "checkout":
        return {
            "allowed": True,
            "operation": op,
            "approval_required": False,
            "boundary": "checkout_prep_only",
            "message": "Checkout prep is allowed under Joy's live supervision only through broad shopping-browser clicks with approved_effect='checkout_prep', 'select_shipping_option', or 'apply_checkout_option'. Star must pause for login, Bitwarden, passkeys, 2FA, CAPTCHA, suspicious security prompts, payment/address/account edits, or sensitive-information prompts. Final Buy Now/Place Order remains blocked.",
        }
    if op in ("checkout_prep", "select_shipping_option", "apply_checkout_option"):
        return {
            "allowed": True,
            "operation": op,
            "approval_required": False,
            "boundary": "supervised_checkout_prep",
            "message": "Allowed only as an audited broad shopping_browser_click approved_effect on visible Amazon checkout-prep controls. Final order submission and sensitive account/payment/address/login scopes are refused.",
        }
    if op == "remove_from_cart":
        return {
            "allowed": True,
            "operation": op,
            "approval_required": True,
            "message": "Allowed only through shopping_browser_click with approved_effect='remove_from_cart', a human-readable reason/approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page.",
        }
    if op == "place_order":
        return {
            "allowed": False,
            "operation": op,
            "approval_required": True,
            "trusted_approval_required": True,
            "message": "Final purchase remains blocked from ordinary chat/tool execution. It requires a trusted Telegram approval action bound to the exact material checkout summary hash and must expire if item, quantity, seller, shipping, tax/total, delivery, address/payment label, subscription state, or other material fields change.",
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
            self._wait_for_endpoint(self.cdp_url, "shopping browser CDP endpoint")
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
        self._wait_for_endpoint(self.cdp_url, "shopping browser CDP bridge")
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
        raise RuntimeError("shopping browser CDP endpoint did not report a browser websocket")
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
            "page_title": str(_evaluate(browser, session_id, "document.title") or ""),
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
            raise ValueError("generic shopping_browser_query is unavailable on checkout/order-review pages outside the Amazon checkout-prep sanitizer boundary")
        value = _evaluate(browser, session_id, wrapped)
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
            if int(redaction.get("redaction_overlay_count") or 0) < 1:
                raise ValueError("checkout-prep screenshot redaction found no address/payment/contact regions to cover; refusing visual capture")
        params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full_page) and not policy["redaction_required"]}
        capture_method = "cdp"
        cdp_error = ""
        try:
            captured = browser.call("Page.captureScreenshot", params, session_id=session_id)
            encoded = str(captured.get("data") or "")
            if not encoded:
                raise RuntimeError("shopping browser did not return screenshot data")
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
            "safety_boundary": "Captured only the persistent shopping browser page as a local PNG artifact. No raw CDP endpoint, cookies, local storage, request headers, vault contents, passwords, passkeys, 2FA/CAPTCHA data, or account/payment/address secrets were returned as structured text.",
        }
        if policy["redaction_required"]:
            result["redaction"] = {
                "status": "applied",
                "overlay_count": int(redaction.get("redaction_overlay_count") or 0),
                "redaction_rects_hash": _redaction_hash(redaction),
                "policy": "Checkout-prep screenshot uses browser-side opaque overlays for address, payment, account/contact, gift/promo-code, and security-prompt regions before capture. Full-page capture is disabled for redacted checkout evidence so off-viewport secrets are not captured without overlays.",
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
        raise RuntimeError("shopping browser did not return screenshot data")
    return base64.b64decode(encoded, validate=True)


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
        if not (parsed.scheme == "https" and AMAZON_HOST_RE.search(parsed.netloc) and checkoutish):
            raise ValueError("owner-only checkout review currently requires an Amazon checkout/order-review page")
        target_id = page_info.get("id") or _first_page_target(browser)
        session_id = _attach(browser, str(target_id))
        safety = _evaluate(browser, session_id, CHECKOUT_PAGE_SAFETY_JS) or {}
        if safety.get("blocked_reason"):
            raise ValueError(str(safety.get("blocked_reason")))
        checkout_review = _checkout_summary_from_browser(browser, session_id)
        binding = str(checkout_review.get("material_summary_binding") or "")
        if not binding:
            raise RuntimeError("checkout review did not produce a material summary binding")
        review_id = hashlib.sha256(f"{binding}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]
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
            raise RuntimeError("owner-only checkout review captured no visual evidence")

        deliveries = []
        artifact_hashes = []
        paths_to_remove = []
        try:
            for index, (name, png_data, mode) in enumerate(artifacts, 1):
                artifact_hashes.append(hashlib.sha256(png_data).hexdigest())
                output_path = _safe_owner_review_path(f"{review_id}-{name}")
                _write_screenshot(output_path, png_data)
                if not retain_local:
                    paths_to_remove.append(output_path)
                caption = _owner_checkout_review_caption(review_id, index, len(artifacts), binding, mode, checkout_review)
                deliveries.append(_telegram_send_document(output_path, caption))
        finally:
            if not retain_local:
                for path in paths_to_remove:
                    with contextlib.suppress(OSError):
                        os.remove(path)
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
            "artifact_count": len(artifacts),
            "telegram_message_ids": [item.get("message_id") for item in deliveries],
            "checkout_review": checkout_review,
            "retention": "sensitive PNG artifacts were deleted locally after Telegram delivery" if not retain_local else "sensitive PNG artifacts retained locally with 0600 files under owner review directory",
            "safety_boundary": "Complete checkout screenshots were sent directly to Joy's configured Telegram destination and are not returned as MEDIA handles, file paths, raw DOM, cookies, storage, request headers, CDP endpoints, credentials, passkeys, 2FA/CAPTCHA, or structured address/payment text to Star. Final Place Order remains blocked from ordinary shopping tools.",
        }
        _audit("owner_checkout_review", {"review_id": review_id, "url": result["url"], "page_title": title, "material_summary_binding": binding, "owner_visual_evidence_binding": evidence_binding, "capture_mode": capture_mode, "artifact_count": len(artifacts), "retained_local": retain_local})
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
            "safety_boundary": "Full-page/viewport image artifacts and crops are local PNGs from the shopping browser only. Suggested regions expose sanitized labels, selectors, and bounding boxes, not raw DOM/HTML, cookies, local storage, request headers, CDP endpoints, credentials, or browser internals. Checkout-prep evidence is redacted and downgraded to viewport capture when necessary.",
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
        return result

    return _with_browser(run)


def shopping_browser_status_tool(args: dict[str, Any], **_kw: Any) -> str:
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
        "browser_operations": ["navigate", "page_snapshot", "query", "click", "type", "screenshot", "visual_evidence", "current_page_summary", "owner_checkout_review"],
        "supervised_checkout_prep": {
            "status": "available",
            "approved_click_effects": list(CHECKOUT_APPROVED_EFFECTS),
            "approved_type_effects": ["apply_checkout_option", "cart_line_adjustment"],
            "boundary": "Star may inspect sanitized checkout-prep controls and click/type into ordinary review-page controls under Joy's live supervision with explicit approved_effect values. Star must pause for login, Bitwarden, passkeys, 2FA, CAPTCHA, suspicious security prompts, payment/address/account edits, or sensitive-information prompts.",
            "sanitization": "Checkout-prep snapshots/current-page summaries return isolated structured item/totals/delivery/surprise fields plus destination city-state/abstract label and payment labels. Mixed blobs, sensitive redaction-marker text, and final purchase controls are removed from ordinary summary fields.",
            "visual_confirmation": "shopping_browser_visual_evidence returns a bounded visual proof bundle: a local PNG screenshot, sanitized suggested regions, and optional focused crops. Amazon checkout/order-review pages are allowed only as redacted checkout-prep viewport evidence; login/account/payment/address/security pages remain Joy-only.",
            "owner_only_confirmation": "shopping_browser_owner_checkout_review can send complete unredacted checkout screenshots directly to Joy's configured Telegram destination without returning paths, MEDIA handles, raw DOM, cookies, storage, request headers, CDP endpoints, or address/payment text to Star.",
        },
        "approval_gated_operations": {
            "add_to_cart": "available only through the broad shopping_browser_click flow with approved_effect='add_to_cart' and a human-readable approval reference",
            "remove_from_cart": "available only through shopping_browser_click with approved_effect='remove_from_cart', a human-readable approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page",
            "place_order": "blocked from ordinary tool use; requires a trusted Telegram action approval bound to the exact material_summary_binding from the current checkout review and expires on material changes",
            "owner_checkout_review": "available only as owner-only Telegram delivery of complete checkout visual evidence tied to the same material_summary_binding; it does not expose sensitive evidence to Star",
        },
        "removed_legacy_helpers": ["shopping_browser_inspect_product", "shopping_browser_inspect_reviews", "shopping_browser_inspect_cart", "shopping_browser_add_to_cart"],
        "screenshot_dir": SCREENSHOT_DIR,
        "audit_log": AUDIT_LOG,
        "blocked_operations": sorted(UNSAFE_OPERATIONS | {"place_order"}),
        "secret_policy": "No raw CDP URLs, cookies, local storage, request headers, downloads, vault contents, passwords, passkeys, 2FA, or CAPTCHA data are returned as structured text. Screenshots are local PNG artifacts from the persistent shopping browser and are refused on obvious account/payment/address/login/security URLs.",
    }
    return _json(status)



def shopping_browser_navigate_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        url = str(args.get("url") or "").strip()
        new_page = bool(args.get("new_page", False))
        return _json(_navigate(url, new_page))
    except Exception as exc:
        return _json({"error": "NAVIGATE_FAILED", "message": str(exc)[:1000], "operation": "navigate"})


def shopping_browser_page_snapshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_page_snapshot(int(args.get("max_text_chars") or MAX_TEXT_CHARS), int(args.get("max_interactive") or MAX_LINKS)))
    except Exception as exc:
        return _json({"error": "PAGE_SNAPSHOT_FAILED", "message": str(exc)[:1000], "operation": "page_snapshot"})


def shopping_browser_query_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_query(str(args.get("expression") or "")))
    except Exception as exc:
        return _json({"error": "QUERY_FAILED", "message": str(exc)[:1000], "operation": "query"})


def shopping_browser_screenshot_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_screenshot(bool(args.get("full_page", False))))
    except Exception as exc:
        return _json({"error": "SCREENSHOT_FAILED", "message": str(exc)[:1000], "operation": "screenshot"})


def shopping_browser_visual_evidence_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        crops = args.get("crops") or []
        if not isinstance(crops, list):
            return _json({"error": "INVALID_CROPS", "message": "crops must be a list of crop spec objects", "operation": "visual_evidence"})
        return _json(_visual_evidence(bool(args.get("full_page", True)), bool(args.get("include_full_page", False)), crops))
    except Exception as exc:
        return _json({"error": "VISUAL_EVIDENCE_FAILED", "message": str(exc)[:1000], "operation": "visual_evidence"})


def shopping_browser_click_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_click(str(args.get("selector") or ""), str(args.get("reason") or ""), str(args.get("approved_effect") or "browse")))
    except Exception as exc:
        return _json({"error": "CLICK_FAILED", "message": str(exc)[:1000], "operation": "click"})


def shopping_browser_type_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_type(str(args.get("selector") or ""), str(args.get("text") or ""), str(args.get("reason") or ""), str(args.get("approved_effect") or "type")))
    except Exception as exc:
        return _json({"error": "TYPE_FAILED", "message": str(exc)[:1000], "operation": "type"})


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


def shopping_browser_owner_checkout_review_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_owner_checkout_review(bool(args.get("send_to_telegram", True)), bool(args.get("retain_local", False))))
    except Exception as exc:
        return _json({"error": "OWNER_CHECKOUT_REVIEW_FAILED", "message": str(exc)[:1000], "operation": "owner_checkout_review"})


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

NAVIGATE_SCHEMA = {
    "name": "shopping_browser_navigate",
    "description": "Navigate the persistent Star shopping browser to an http(s) URL. Blocks obvious checkout, account, payment, address, order, CAPTCHA, passkey, and credential-challenge targets so Joy can take over those scopes. Logs the navigation in the shopping browser audit log.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL to open in the shopping browser"},
            "new_page": {"type": "boolean", "description": "Open in a fresh page/tab instead of reusing the current page", "default": False},
        },
        "required": ["url"],
    },
}

PAGE_SNAPSHOT_SCHEMA = {
    "name": "shopping_browser_page_snapshot",
    "description": "Inspect the current shopping browser page as visible text plus a bounded list of interactive elements and suggested CSS selectors. Does not return raw HTML, cookies, local storage, request headers, screenshots, or CDP handles.",
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
    "name": "shopping_browser_query",
    "description": "Evaluate a limited read-only JavaScript expression on the current shopping page for structured visible-page facts. Runtime guardrails reject obvious mutation, network, storage, cookie, and navigation tokens. On checkout/order-review pages this tool does not return the raw query result; it returns only the sanitized checkout-prep summary and non-secret controls, while complete checkout evidence remains Joy-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Read-only JavaScript expression, e.g. document.title or Array.from(document.querySelectorAll('button')).map(b => b.innerText)"},
        },
        "required": ["expression"],
    },
}

SCREENSHOT_SCHEMA = {
    "name": "shopping_browser_screenshot",
    "description": "Capture the current visible persistent shopping browser page as a local PNG media artifact for delivery. Refuses obvious login, account, payment, address, order, passkey, CAPTCHA, and verification URLs; Amazon checkout-prep pages are captured only with browser-side redaction and viewport bounds. Logs the high-level capture in the audit log. Returns only a local file path/media handle plus sanitized page metadata, not raw CDP data, cookies, storage, headers, or secrets.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when Chromium supports it. Redacted checkout-prep evidence is always downgraded to viewport capture.", "default": False},
        },
        "required": [],
    },
}

VISUAL_EVIDENCE_SCHEMA = {
    "name": "shopping_browser_visual_evidence",
    "description": "Capture retailer-agnostic visual evidence from the current shopping browser page: a local PNG screenshot, sanitized suggested regions, and optional focused crops. Crops may reference a suggested region_id/category/text_anchor, a safe CSS selector, or an explicit bounding rect. Amazon checkout-prep pages are captured only with redaction and viewport bounds; login/account/payment/address/security pages remain Joy-only. Returns PNG paths/media handles plus sanitized metadata, never raw DOM, cookies, storage, request headers, credentials, CDP endpoints, payment/address secrets, or browser internals.",
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
    "name": "shopping_browser_click",
    "description": "Click a visible element in the persistent shopping browser by CSS selector. Use for browsing, selecting variants/options, applying visible coupons, explicitly approved add-to-cart/removal, and supervised checkout-prep controls. Checkout prep requires an explicit checkout approved_effect such as checkout_prep, select_shipping_option, select_delivery_option, apply_checkout_option, fix_purchase_mode, or cart_line_adjustment plus Joy live supervision; it returns a refreshed sanitized order-review summary/material_summary_binding and refuses final purchase controls. Never use for Buy Now, Place Order, account/payment/address edits, login, passkeys, 2FA, or CAPTCHA.",
    "parameters": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector from shopping_browser_page_snapshot or a carefully derived selector"},
            "approved_effect": {"type": "string", "description": "Expected effect of the click", "enum": list(APPROVED_CLICK_EFFECTS), "default": "browse"},
            "reason": {"type": "string", "description": "Short human-readable reason/approval reference for audit, required for add_to_cart and remove_from_cart"},
        },
        "required": ["selector", "approved_effect", "reason"],
    },
}

TYPE_SCHEMA = {
    "name": "shopping_browser_type",
    "description": "Type bounded non-sensitive text into a visible field in the persistent shopping browser. Intended for search boxes, quantity fields, and similar shopping UI. Refuses fields that look like password, passkey, OTP, card, contact, address, or payment inputs; Joy must take over those.",
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
    "name": "shopping_browser_inspect_product",
    "description": "Read-only Amazon product inspection through the Kasm shopping session. Returns product title, logged-in price, delivery/Prime text, availability, seller, ship-from text, visible condition text when Amazon exposes it, and public Amazon product image URLs when visible. Does not expose cookies, local storage, request headers, raw CDP, screenshots, or browser handles.",
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

OWNER_CHECKOUT_REVIEW_SCHEMA = {
    "name": "shopping_browser_owner_checkout_review",
    "description": "Send complete sensitive checkout/order-review visual evidence directly to Joy's configured Telegram destination for owner-only review. Intended for final pre-purchase verification of address, payment, item, delivery, tax/total, discounts, and final controls. Returns only a redacted acknowledgement, material_summary_binding, owner visual-evidence binding, and sanitized checkout summary to Star; it never returns image paths, MEDIA handles, raw DOM, cookies, storage, request headers, CDP endpoints, credentials, passkeys, 2FA/CAPTCHA data, or structured address/payment details. Final Place Order remains blocked pending trusted approval.",
    "parameters": {
        "type": "object",
        "properties": {
            "send_to_telegram": {"type": "boolean", "description": "Must remain true; sensitive evidence is delivered directly to Joy instead of returned to Star", "default": True},
            "retain_local": {"type": "boolean", "description": "Retain temporary sensitive PNGs locally after Telegram delivery for operator debugging; default false deletes local files after successful send", "default": False},
        },
        "required": [],
    },
}

GUARDRAIL_SCHEMA = {
    "name": "shopping_browser_guardrail_check",
    "description": "Check whether a shopping-browser operation is allowed. Checkout now means supervised checkout-prep only; final place_order remains blocked pending trusted Telegram approval bound to a material order-summary hash. Raw session/account/payment/address/secret operations are rejected.",
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
    name=NAVIGATE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=NAVIGATE_SCHEMA,
    handler=shopping_browser_navigate_tool,
    check_fn=_check_shopping_browser,
    description=NAVIGATE_SCHEMA["description"],
    emoji="🧭",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=PAGE_SNAPSHOT_SCHEMA["name"],
    toolset=TOOLSET,
    schema=PAGE_SNAPSHOT_SCHEMA,
    handler=shopping_browser_page_snapshot_tool,
    check_fn=_check_shopping_browser,
    description=PAGE_SNAPSHOT_SCHEMA["description"],
    emoji="📄",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=QUERY_SCHEMA["name"],
    toolset=TOOLSET,
    schema=QUERY_SCHEMA,
    handler=shopping_browser_query_tool,
    check_fn=_check_shopping_browser,
    description=QUERY_SCHEMA["description"],
    emoji="🔎",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=SCREENSHOT_SCHEMA["name"],
    toolset=TOOLSET,
    schema=SCREENSHOT_SCHEMA,
    handler=shopping_browser_screenshot_tool,
    check_fn=_check_shopping_browser,
    description=SCREENSHOT_SCHEMA["description"],
    emoji="📸",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=VISUAL_EVIDENCE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=VISUAL_EVIDENCE_SCHEMA,
    handler=shopping_browser_visual_evidence_tool,
    check_fn=_check_shopping_browser,
    description=VISUAL_EVIDENCE_SCHEMA["description"],
    emoji="🖼️",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=CLICK_SCHEMA["name"],
    toolset=TOOLSET,
    schema=CLICK_SCHEMA,
    handler=shopping_browser_click_tool,
    check_fn=_check_shopping_browser,
    description=CLICK_SCHEMA["description"],
    emoji="👆",
    max_result_size_chars=MAX_RESULT_CHARS,
)
registry.register(
    name=TYPE_SCHEMA["name"],
    toolset=TOOLSET,
    schema=TYPE_SCHEMA,
    handler=shopping_browser_type_tool,
    check_fn=_check_shopping_browser,
    description=TYPE_SCHEMA["description"],
    emoji="⌨️",
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
    name=OWNER_CHECKOUT_REVIEW_SCHEMA["name"],
    toolset=TOOLSET,
    schema=OWNER_CHECKOUT_REVIEW_SCHEMA,
    handler=shopping_browser_owner_checkout_review_tool,
    check_fn=_check_shopping_browser,
    description=OWNER_CHECKOUT_REVIEW_SCHEMA["description"],
    emoji="🔐",
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
    assert _reject_unsafe_operation("checkout")["allowed"] is True
    assert _reject_unsafe_operation("checkout")["boundary"] == "checkout_prep_only"
    assert _reject_unsafe_operation("place_order")["allowed"] is False
    assert _safe_browser_url("https://www.amazon.com/dp/B01J01XGPK")
    try:
        _safe_browser_url("https://www.amazon.com/checkout")
        raise AssertionError("checkout URL should be blocked")
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
                    "selector": "[data-shopping-browser-checkout-control=\"sb-checkout-2\"]",
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
    original_target_page_info = _target_page_info
    original_attach = _attach
    original_evaluate = _evaluate
    original_checkout_summary_from_browser = _checkout_summary_from_browser
    try:
        globals()["_with_browser"] = lambda fn: fn(_FakeBrowser())
        globals()["_target_page_info"] = lambda _port: {"id": "checkout-target", "url": "https://www.amazon.com/gp/buy/spc/handlers/display.html", "title": "Review your order"}
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
        globals()["_target_page_info"] = original_target_page_info
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
    assert json.loads(shopping_browser_visual_evidence_tool({"crops": "not-a-list"}))["error"] == "INVALID_CROPS"
    disabled_owner_review = json.loads(shopping_browser_owner_checkout_review_tool({"send_to_telegram": False}))
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
    body, content_type = _multipart_request({"chat_id": "123"}, {"document": ("review.png", b"png", "image/png")})
    assert b"review.png" in body and content_type.startswith("multipart/form-data")
    status = json.loads(shopping_browser_status_tool({}))
    assert "screenshot" in status["browser_operations"]
    assert "visual_evidence" in status["browser_operations"]
    assert "owner_checkout_review" in status["browser_operations"]
    assert status["supervised_checkout_prep"]["status"] == "available"
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
    active_schema_names = [STATUS_SCHEMA["name"], NAVIGATE_SCHEMA["name"], PAGE_SNAPSHOT_SCHEMA["name"], QUERY_SCHEMA["name"], SCREENSHOT_SCHEMA["name"], VISUAL_EVIDENCE_SCHEMA["name"], CLICK_SCHEMA["name"], TYPE_SCHEMA["name"], CURRENT_PAGE_SUMMARY_SCHEMA["name"], OWNER_CHECKOUT_REVIEW_SCHEMA["name"], GUARDRAIL_SCHEMA["name"]]
    assert "shopping_browser_owner_checkout_review" in active_schema_names
    assert "shopping_browser_inspect_product" not in active_schema_names
    assert "shopping_browser_inspect_reviews" not in active_schema_names
    assert "shopping_browser_inspect_cart" not in active_schema_names
    assert "shopping_browser_add_to_cart" not in active_schema_names
    assert not any(word in json.dumps(STATUS_SCHEMA).lower() for word in ("cookie", "localstorage"))
    product = {"image_url_candidates": ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg?x=1", "https://example.com/not-amazon.jpg"]}
    _normalize_product_images(product)
    assert product["primary_image_url"] == "https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"
    assert product["image_urls"] == ["https://m.media-amazon.com/images/I/example._AC_SX679_.jpg"]
    print("shopping_browser_tool smoke ok")

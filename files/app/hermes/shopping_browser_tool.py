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
from urllib.request import urlopen

import websockets.sync.client
from tools.registry import registry

TOOLSET = "shopping_browser"
NAMESPACE = os.environ.get("SHOPPING_BROWSER_NAMESPACE", "ai")
WORKLOAD = os.environ.get("SHOPPING_BROWSER_WORKLOAD", "deployment/shopping")
REMOTE_DEBUG_PORT = int(os.environ.get("SHOPPING_BROWSER_CDP_PORT", "9222"))
BROWSER_DISPLAY = os.environ.get("SHOPPING_BROWSER_DISPLAY", ":1")
XWD_TIMEOUT_SECONDS = float(os.environ.get("SHOPPING_BROWSER_XWD_TIMEOUT_SECONDS", "15"))
MAX_RESULT_CHARS = 16000
MAX_TEXT_CHARS = 12000
MAX_LINKS = 80
MAX_QUERY_RESULT_CHARS = 8000
MAX_TYPE_CHARS = 2000
SCREENSHOT_DIR = os.environ.get("SHOPPING_BROWSER_SCREENSHOT_DIR", os.path.expanduser("~/.hermes/profiles/star/shopping-browser-screenshots"))
AUDIT_LOG = os.environ.get("SHOPPING_BROWSER_AUDIT_LOG", os.path.expanduser("~/.hermes/profiles/star/shopping-browser-audit.log"))
MAX_PRODUCT_IMAGES = 6
DEFAULT_MAX_REVIEWS = 5
MAX_REVIEWS = 10
REVIEW_EXCERPT_CHARS = 900
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
    "checkout",
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
    r"\b(place\s+order|buy\s+now|proceed\s+to\s+checkout|checkout|payment|wallet|address|account|orders?|subscribe\s*&\s*save|passkey|password|verification\s+code|captcha)\b",
    re.IGNORECASE,
)
CART_URL_RE = re.compile(r"/(gp/)?cart(/|$)", re.IGNORECASE)
CART_REMOVE_TEXT_RE = re.compile(r"\b(delete|remove)\b", re.IGNORECASE)
APPROVED_CLICK_EFFECTS = ("browse", "select_option", "apply_visible_coupon", "add_to_cart", "remove_from_cart")
SENSITIVE_FIELD_RE = re.compile(r"(password|passkey|otp|verification|card|cvv|cvc|security.?code|address|phone|email)", re.IGNORECASE)
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


def _json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if len(payload) > MAX_RESULT_CHARS:
        payload = payload[:MAX_RESULT_CHARS] + "… [truncated]"
    return payload


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
    if CHECKOUT_OR_ACCOUNT_RE.search(candidate):
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


def _json_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _check_human_takeover_text(text: str) -> None:
    if CHECKOUT_OR_ACCOUNT_RE.search(text):
        raise ValueError("matched element appears to involve checkout/account/payment/address/login challenge scope; Joy must take over")


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


def _safe_screenshot_path() -> str:
    os.makedirs(SCREENSHOT_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(SCREENSHOT_DIR, f"shopping-browser-{stamp}-{os.getpid()}.png")


def _assert_screenshot_allowed(url: str, title: str) -> None:
    parsed = urlparse(url)
    sensitive_url = " ".join([parsed.path, parsed.query, title]).lower()
    if re.search(r"(signin|login|ap/signin|checkout|buy|place-order|address|wallet|payment|account|orders|passkey|password|captcha|verification)", sensitive_url):
        raise ValueError("current page appears to be login, checkout, account, payment, address, order, CAPTCHA, or passkey scope; Joy must take over before screenshots")


def _write_screenshot(output_path: str, data: bytes) -> None:
    with open(output_path, "wb") as handle:
        handle.write(data)
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


def _page_targets_from_http(port: int) -> list[dict[str, str]]:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
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


def _target_page_info(port: int) -> dict[str, str]:
    pages = _page_targets_from_http(port)
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
    if op == "remove_from_cart":
        return {
            "allowed": True,
            "operation": op,
            "approval_required": True,
            "message": "Allowed only through shopping_browser_click with approved_effect='remove_from_cart', a human-readable reason/approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page.",
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
    def __init__(self, websocket_url: str, port: int | None = None) -> None:
        self.ws = websockets.sync.client.connect(websocket_url, open_timeout=5, close_timeout=2)
        self.next_id = 1
        self.port = port

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
    # Chrome's browser-level Target.getTargets order is not the same as the
    # visible /json/list order and can return stale Amazon page targets before
    # the active Kasm tab.  Prefer the HTTP target list when we have a forwarded
    # port so broad operations act on the same page screenshot/status reports.
    if browser.port is not None:
        with contextlib.suppress(Exception):
            for target in _page_targets_from_http(browser.port):
                if target.get("id"):
                    return str(target["id"])

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
        browser = CdpSession(_browser_ws_url(port), port=port)
        try:
            return fn(browser)
        finally:
            browser.close()



def _navigate(url: str, new_page: bool) -> dict[str, Any]:
    safe_url = _safe_browser_url(url)

    def run(browser: CdpSession) -> dict[str, Any]:
        target_id = str(browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]) if new_page else _first_page_target(browser)
        session_id = _attach(browser, target_id)
        _navigate_and_wait(browser, session_id, safe_url)
        result = {
            "operation": "navigate",
            "status": "ok",
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
        target_id = _first_page_target(browser)
        session_id = _attach(browser, target_id)
        value = _evaluate(browser, session_id, wrapped)
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(payload) > MAX_QUERY_RESULT_CHARS:
            value = payload[:MAX_QUERY_RESULT_CHARS] + "… [truncated]"
        return {"operation": "query", "status": "ok", "value": value}

    return _with_browser(run)


def _screenshot(full_page: bool = False) -> dict[str, Any]:
    def run(browser: CdpSession) -> dict[str, Any]:
        page_info = _target_page_info(browser.port) if browser.port is not None else {}
        url = str(page_info.get("url") or "")
        title = str(page_info.get("title") or "")
        _assert_screenshot_allowed(url, title)
        params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full_page)}
        capture_method = "cdp"
        cdp_error = ""
        try:
            target_id = page_info.get("id") or _first_page_target(browser)
            session_id = _attach(browser, str(target_id))
            captured = browser.call("Page.captureScreenshot", params, session_id=session_id)
            encoded = str(captured.get("data") or "")
            if not encoded:
                raise RuntimeError("shopping browser did not return screenshot data")
            png_data = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            # Amazon can leave the page target unresponsive to Page/Runtime CDP
            # calls while the Kasm display itself is still live.  Fall back to a
            # container-scoped X11 root capture after checking the target URL and
            # title from Chrome's /json/list metadata.
            capture_method = "kasm_x11"
            png_data = _x11_screenshot()
            cdp_error = str(exc)[:500]
        output_path = _safe_screenshot_path()
        _write_screenshot(output_path, png_data)
        result = {
            "operation": "screenshot",
            "status": "ok",
            "path": output_path,
            "media": f"MEDIA:{output_path}",
            "url": _sanitize_url(url),
            "page_title": title,
            "full_page": bool(full_page) and capture_method == "cdp",
            "capture_method": capture_method,
            "safety_boundary": "Captured only the persistent shopping browser page as a local PNG artifact. No raw CDP endpoint, cookies, local storage, request headers, vault contents, passwords, passkeys, 2FA/CAPTCHA data, or account/payment/address secrets were returned as structured text.",
        }
        if capture_method == "kasm_x11":
            result["fallback_reason"] = cdp_error
            result["full_page_note"] = "Kasm X11 fallback captures the visible browser display only."
        _audit("screenshot", {"url": result["url"], "page_title": title, "path": output_path, "full_page": result["full_page"], "capture_method": capture_method})
        return result

    with PortForward() as port:
        browser = CdpSession(_browser_ws_url(port), port=port)
        try:
            return run(browser)
        finally:
            browser.close()


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
        elif effect != "add_to_cart":
            _check_human_takeover_text(label)
        result = _evaluate(browser, session_id, CLICK_JS.replace("__SELECTOR__", _json_literal(safe_selector))) or {}
        time.sleep(1.0)
        result["operation"] = "click"
        result["approved_effect"] = effect
        result["url"] = _sanitize_url(str(result.get("url") or _evaluate(browser, session_id, "location.href") or ""))
        _audit("click", {"selector": safe_selector, "effect": effect, "reason": str(reason or "")[:300], "element_text": result.get("element_text"), "url": result.get("url")})
        return result

    return _with_browser(run)


def _type(selector: str, text: str, reason: str) -> dict[str, Any]:
    safe_selector = _selector_arg(selector)
    safe_text = _bounded_text(text)
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
        if SENSITIVE_FIELD_RE.search(field_text):
            raise ValueError("matched field appears sensitive; Joy must take over")
        result = _evaluate(browser, session_id, TYPE_JS.replace("__SELECTOR__", _json_literal(safe_selector)).replace("__VALUE__", _json_literal(safe_text))) or {}
        result["operation"] = "type"
        result["typed_chars"] = len(safe_text)
        result["url"] = _sanitize_url(str(result.get("url") or _evaluate(browser, session_id, "location.href") or ""))
        _audit("type", {"selector": safe_selector, "typed_chars": len(safe_text), "reason": str(reason or "")[:300], "url": result.get("url")})
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
        "browser_operations": ["navigate", "page_snapshot", "query", "click", "type", "screenshot", "current_page_summary"],
        "approval_gated_operations": {
            "add_to_cart": "available only through the broad shopping_browser_click flow with approved_effect='add_to_cart' and a human-readable approval reference",
            "remove_from_cart": "available only through shopping_browser_click with approved_effect='remove_from_cart', a human-readable approval reference, and a visible Delete/Remove cart line-item control on an Amazon cart page",
        },
        "removed_legacy_helpers": ["shopping_browser_inspect_product", "shopping_browser_inspect_reviews", "shopping_browser_inspect_cart", "shopping_browser_add_to_cart"],
        "screenshot_dir": SCREENSHOT_DIR,
        "audit_log": AUDIT_LOG,
        "blocked_operations": sorted(UNSAFE_OPERATIONS),
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


def shopping_browser_click_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_click(str(args.get("selector") or ""), str(args.get("reason") or ""), str(args.get("approved_effect") or "browse")))
    except Exception as exc:
        return _json({"error": "CLICK_FAILED", "message": str(exc)[:1000], "operation": "click"})


def shopping_browser_type_tool(args: dict[str, Any], **_kw: Any) -> str:
    try:
        return _json(_type(str(args.get("selector") or ""), str(args.get("text") or ""), str(args.get("reason") or "")))
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
    "description": "Evaluate a limited read-only JavaScript expression on the current shopping page for structured visible-page facts. Runtime guardrails reject obvious mutation, network, storage, cookie, and navigation tokens; do not use this for side effects or secrets.",
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
    "description": "Capture the current visible persistent shopping browser page as a local PNG media artifact for delivery. Refuses obvious login, checkout, account, payment, address, order, passkey, CAPTCHA, and verification URLs; logs the high-level capture in the audit log. Returns only a local file path/media handle plus sanitized page metadata, not raw CDP data, cookies, storage, headers, or secrets.",
    "parameters": {
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "description": "Capture beyond the current viewport when Chromium supports it. Prefer false for visible-page proof.", "default": False},
        },
        "required": [],
    },
}

CLICK_SCHEMA = {
    "name": "shopping_browser_click",
    "description": "Click a visible element in the persistent shopping browser by CSS selector. Use for browsing, selecting variants/options, applying visible coupons, explicitly approved add-to-cart, and explicitly approved visible cart line-item Delete/Remove controls only. Cart removal requires approved_effect='remove_from_cart', a human-readable approval reference, an Amazon cart page, and a visible button/input/link whose own label/name/aria/id indicates Delete or Remove. Blocks obvious checkout/account/payment/address/login-challenge text except for add_to_cart. Never use for Buy Now, Place Order, account/payment/address edits, login, passkeys, 2FA, CAPTCHA, or checkout.",
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
        },
        "required": ["selector", "text", "reason"],
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

GUARDRAIL_SCHEMA = {
    "name": "shopping_browser_guardrail_check",
    "description": "Check whether a shopping-browser operation is allowed. Arbitrary mutations/navigation/account/payment/order/raw-session operations are rejected; screenshot is allowed only through the shopping-browser-scoped media artifact tool, add_to_cart is available only as an approved broad click effect, and remove_from_cart is available only as an approved broad click effect for visible cart line-item Delete/Remove controls.",
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
    assert "shopping_browser_screenshot" == SCREENSHOT_SCHEMA["name"]
    status = json.loads(shopping_browser_status_tool({}))
    assert "screenshot" in status["browser_operations"]
    assert "inspect_product" not in status["browser_operations"]
    assert _extract_asin("https://www.amazon.com/example/dp/B09JJNBB9C?x=1") == "B09JJNBB9C"
    assert _review_url("https://www.amazon.com/example/dp/B09JJNBB9C?x=1")[0] == "https://www.amazon.com/product-reviews/B09JJNBB9C"
    assert _bounded_max_reviews(99) == MAX_REVIEWS
    assert _product_url_from_url_or_asin("B01J01XGPK") == ("https://www.amazon.com/dp/B01J01XGPK", "B01J01XGPK")
    assert _approved_cart_addition("B01J01XGPK", 1, Decimal("7.95"), "one_time")["quantity"] == 1
    assert "text('#ppd')" not in ADD_TO_CART_PRECHECK_JS
    assert "condition_summary" in ADD_TO_CART_PRECHECK_JS
    assert "product_condition" in PRODUCT_EXTRACT_JS
    active_schema_names = [STATUS_SCHEMA["name"], NAVIGATE_SCHEMA["name"], PAGE_SNAPSHOT_SCHEMA["name"], QUERY_SCHEMA["name"], SCREENSHOT_SCHEMA["name"], CLICK_SCHEMA["name"], TYPE_SCHEMA["name"], CURRENT_PAGE_SUMMARY_SCHEMA["name"], GUARDRAIL_SCHEMA["name"]]
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

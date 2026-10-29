// Larkspur Goods: a tiny hash-routed storefront. The "buggy" build carries seven seeded
// defects (marked BUG n below) for QAPilot to find; the "fixed" build is the control.
(() => {
  "use strict";

  const SEEDED = window.SHOP_BUILD !== "fixed";
  const CART_KEY = "larkspur-cart";
  const app = document.getElementById("app");

  const state = {
    products: [],
    cart: loadCart(),
    coupon: null,
    discountRate: 0,
    couponNote: null,
    query: "",
    form: { name: "", email: "", address: "", shipping: "standard" },
    errors: {},
    checkoutError: null,
    submitting: false,
  };

  // --- helpers ---------------------------------------------------------------------

  const money = (n) => "$" + n.toFixed(2);
  const round2 = (n) => Math.round(n * 100) / 100;
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const byId = (id) => state.products.find((p) => p.id === id);

  function loadCart() {
    try {
      return JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    } catch {
      return [];
    }
  }

  function saveCart() {
    localStorage.setItem(CART_KEY, JSON.stringify(state.cart));
    const count = state.cart.reduce((n, line) => n + line.qty, 0);
    document.querySelector('[data-testid="cart-count"]').textContent = String(count);
  }

  let toastTimer;
  function toast(message) {
    const el = document.getElementById("toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2500);
  }

  function cartLines() {
    return state.cart.map((line) => ({ ...line, product: byId(line.id) })).filter((line) => line.product);
  }

  function totals(shipping = 0) {
    const lines = cartLines();
    const subtotal = SEEDED
      ? lines.reduce((sum, line) => sum + line.product.price, 0) // BUG 2: quantity is ignored
      : lines.reduce((sum, line) => sum + line.product.price * line.qty, 0);
    const discount = round2(subtotal * state.discountRate);
    return { subtotal: round2(subtotal), discount, shipping, total: round2(subtotal - discount + shipping) };
  }

  function addToCart(id) {
    const line = state.cart.find((l) => l.id === id);
    if (line) line.qty += 1;
    else state.cart.push({ id, qty: 1 });
    saveCart();
    toast(`${byId(id).name} added to cart.`);
  }

  // --- views -----------------------------------------------------------------------

  function productCard(p) {
    return `
      <article class="product" data-testid="product-${p.id}">
        <div class="thumb" role="img" aria-label="${esc(p.name)}">${p.emoji}</div>
        <h3>${esc(p.name)}</h3>
        <p class="price">${money(p.price)}</p>
        <div class="actions">
          <button class="btn" data-action="details" data-id="${p.id}">Details</button>
          <button class="btn primary" data-action="add" data-id="${p.id}">Add to cart</button>
        </div>
      </article>`;
  }

  function matches(p, query) {
    if (!query) return true;
    // BUG 1: the seeded build compares case-sensitively, so "mug" misses "Ceramic Mug".
    return SEEDED ? p.name.includes(query) : p.name.toLowerCase().includes(query.toLowerCase());
  }

  function renderResults() {
    const q = state.query.trim();
    const found = state.products.filter((p) => matches(p, q));
    const results = document.getElementById("results");
    if (!results) return;
    document.querySelector('[data-testid="result-count"]').textContent =
      `${found.length} ${found.length === 1 ? "product" : "products"}`;
    results.innerHTML = found.length
      ? `<div class="grid">${found.map(productCard).join("")}</div>`
      : `<p class="empty" data-testid="empty-state">No products match “${esc(q)}”.</p>`;
  }

  function viewShop() {
    document.title = "Shop · Larkspur Goods";
    app.innerHTML = `
      <h1>Shop</h1>
      <p class="muted">Small-batch goods for slow mornings.</p>
      <div class="toolbar">
        <div class="search">
          <input type="search" placeholder="Search products" aria-label="Search products" value="${esc(state.query)}" data-input="search" />
        </div>
        <p class="muted" data-testid="result-count"></p>
      </div>
      <section aria-label="Products" id="results"></section>`;
    renderResults();
  }

  const TRASH =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>';

  function cartItem(line) {
    const p = line.product;
    // BUG 3: the seeded build's icon-only remove button has no accessible name.
    const removeLabel = SEEDED ? "" : ` aria-label="Remove ${esc(p.name)}"`;
    return `
      <li class="cart-item" data-testid="cart-item-${p.id}">
        <div class="thumb sm" role="img" aria-label="${esc(p.name)}">${p.emoji}</div>
        <div class="ci-main">
          <h3>${esc(p.name)}</h3>
          <p class="muted">${money(p.price)} each</p>
        </div>
        <div class="qty">
          <button data-action="dec" data-id="${p.id}" aria-label="Decrease quantity of ${esc(p.name)}">−</button>
          <span class="qty-value" data-testid="qty-${p.id}">${line.qty}</span>
          <button data-action="inc" data-id="${p.id}" aria-label="Increase quantity of ${esc(p.name)}">+</button>
        </div>
        <p class="line-total" data-testid="line-total-${p.id}">${money(p.price * line.qty)}</p>
        <button class="icon-btn" data-action="remove" data-id="${p.id}"${removeLabel}>${TRASH}</button>
      </li>`;
  }

  function summaryRows(t, withShipping) {
    return `
      <dl>
        <div class="row"><dt>Subtotal</dt><dd data-testid="subtotal">${money(t.subtotal)}</dd></div>
        <div class="row"><dt>Discount</dt><dd data-testid="discount">${t.discount ? "-" + money(t.discount) : money(0)}</dd></div>
        ${withShipping ? `<div class="row"><dt>Shipping</dt><dd data-testid="shipping">${t.shipping ? money(t.shipping) : "Free"}</dd></div>` : ""}
        <div class="row total"><dt>Total</dt><dd data-testid="total">${money(t.total)}</dd></div>
      </dl>`;
  }

  function viewCart() {
    document.title = "Cart · Larkspur Goods";
    const lines = cartLines();
    if (!lines.length) {
      app.innerHTML = `
        <h1>Your cart</h1>
        <div class="empty" style="margin-top:18px">
          <p>Your cart is empty.</p>
          <p style="margin-top:12px"><a class="btn" href="#/">Continue shopping</a></p>
        </div>`;
      return;
    }
    const t = totals();
    const note = state.couponNote
      ? `<p class="note ${state.couponNote.ok ? "ok" : "bad"}" role="status" data-testid="coupon-message">${esc(state.couponNote.text)}</p>`
      : "";
    app.innerHTML = `
      <h1>Your cart</h1>
      <div class="layout">
        <ul class="cart-list">${lines.map(cartItem).join("")}</ul>
        <aside class="panel" aria-label="Order summary">
          <h2>Order summary</h2>
          ${summaryRows(t, false)}
          <form class="coupon" data-form="coupon">
            <div class="field">
              <label for="coupon">Coupon code</label>
              <input id="coupon" name="coupon" autocomplete="off" />
            </div>
            <button class="btn" type="submit">Apply</button>
          </form>
          ${note}
          <a class="btn primary full" href="#/checkout">Checkout</a>
        </aside>
      </div>`;
  }

  function applyCoupon(raw) {
    const code = raw.trim().toUpperCase();
    if (code !== "SAVE10") {
      state.couponNote = { ok: false, text: code ? `Coupon “${code}” is not valid.` : "Enter a coupon code." };
    } else if (state.coupon && !SEEDED) {
      state.couponNote = { ok: false, text: "SAVE10 is already applied." };
    } else {
      state.coupon = code;
      // BUG 4: the seeded build adds another 10% every time the coupon is applied.
      state.discountRate = SEEDED ? state.discountRate + 0.1 : 0.1;
      state.couponNote = { ok: true, text: "SAVE10 applied: 10% off your order." };
    }
    viewCart();
  }

  const SHIPPING = { standard: { label: "Standard (free, 5–7 days)", price: 0 }, express: { label: "Express ($15.00, 1–2 days)", price: 15 } };

  function fieldError(key) {
    const message = state.errors[key];
    return message ? `<p class="error" role="alert" id="${key}-error" data-testid="${key}-error">${esc(message)}</p>` : "";
  }

  function invalid(key) {
    return state.errors[key] ? ` aria-invalid="true" aria-describedby="${key}-error"` : "";
  }

  function renderCheckoutSummary() {
    const el = document.getElementById("checkout-summary");
    if (!el) return;
    el.innerHTML = `<h2>Order summary</h2>${summaryRows(totals(SHIPPING[state.form.shipping].price), true)}`;
  }

  function viewCheckout() {
    document.title = "Checkout · Larkspur Goods";
    if (!cartLines().length) {
      app.innerHTML = `
        <h1>Checkout</h1>
        <div class="empty" style="margin-top:18px">
          <p>Your cart is empty.</p>
          <p style="margin-top:12px"><a class="btn" href="#/">Continue shopping</a></p>
        </div>`;
      return;
    }
    const f = state.form;
    const options = Object.entries(SHIPPING)
      .map(([value, s]) => `<option value="${value}"${f.shipping === value ? " selected" : ""}>${s.label}</option>`)
      .join("");
    app.innerHTML = `
      <h1>Checkout</h1>
      <div class="layout">
        <form class="panel" data-form="checkout" novalidate aria-label="Checkout">
          <h2>Contact and shipping</h2>
          <div class="field">
            <label for="name">Full name</label>
            <input id="name" autocomplete="off" value="${esc(f.name)}" data-input="name"${invalid("name")} />
            ${fieldError("name")}
          </div>
          <div class="field">
            <label for="email">Email</label>
            <input id="email" type="text" inputmode="email" autocomplete="off" value="${esc(f.email)}" data-input="email"${invalid("email")} />
            ${fieldError("email")}
          </div>
          <div class="field">
            <label for="address">Shipping address</label>
            <textarea id="address" rows="2" data-input="address"${invalid("address")}>${esc(f.address)}</textarea>
            ${fieldError("address")}
          </div>
          <div class="field">
            <label for="shipping">Shipping</label>
            <select id="shipping" data-input="shipping">${options}</select>
          </div>
          <button class="btn primary full" type="submit"${state.submitting ? " disabled" : ""}>${state.submitting ? "Placing order…" : "Place order"}</button>
          ${state.checkoutError ? `<div class="banner error" role="alert" data-testid="checkout-error">${esc(state.checkoutError)}</div>` : ""}
        </form>
        <aside class="panel" aria-label="Order summary" id="checkout-summary"></aside>
      </div>`;
    renderCheckoutSummary();
  }

  function validate() {
    const f = state.form;
    const errors = {};
    if (!f.name.trim()) errors.name = "Enter your full name.";
    // BUG 5: the seeded build only checks for "something@", so "test.shopper@" passes.
    const emailOk = SEEDED ? /.+@/.test(f.email) : /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(f.email.trim());
    if (!emailOk) errors.email = "Enter a valid email address.";
    if (!f.address.trim()) errors.address = "Enter a shipping address.";
    return errors;
  }

  async function placeOrder() {
    state.errors = validate();
    state.checkoutError = null;
    if (Object.keys(state.errors).length) {
      viewCheckout();
      return;
    }
    state.submitting = true;
    viewCheckout();
    const f = state.form;
    try {
      const res = await fetch("api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: f.name.trim(),
          email: f.email.trim(),
          address: f.address.trim(),
          shipping: f.shipping,
          coupon: state.coupon,
          items: state.cart.map(({ id, qty }) => ({ id, qty })),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        console.error(`Checkout failed: HTTP ${res.status}`, body.error || body.detail || "");
        state.checkoutError = "We couldn't place your order. Please try again.";
        return;
      }
      state.cart = [];
      state.coupon = null;
      state.discountRate = 0;
      state.couponNote = null;
      saveCart();
      location.hash = `#/order/${body.id}`;
    } catch (err) {
      console.error("Checkout failed:", err);
      state.checkoutError = "We couldn't reach the store. Check your connection.";
    } finally {
      state.submitting = false;
      if (location.hash.startsWith("#/checkout")) viewCheckout();
    }
  }

  async function viewOrder(id) {
    document.title = "Order confirmed · Larkspur Goods";
    app.innerHTML = `<p class="muted">Loading order…</p>`;
    const res = await fetch(`api/orders/${encodeURIComponent(id)}`);
    if (!res.ok) {
      app.innerHTML = `<div class="empty"><p>We couldn't find order ${esc(id)}.</p></div>`;
      return;
    }
    const order = await res.json();
    app.innerHTML = `
      <div class="confirm">
        <h1>Order confirmed</h1>
        <p class="muted">Thank you, ${esc(order.name)}! A confirmation is on its way to ${esc(order.email)}.</p>
        <div class="panel">
          <dl>
            <div class="row"><dt>Order number</dt><dd data-testid="order-number">${esc(order.id)}</dd></div>
            <div class="row"><dt>Items</dt><dd>${order.items.reduce((n, i) => n + i.qty, 0)}</dd></div>
            <div class="row total"><dt>Total paid</dt><dd data-testid="order-total">${money(order.total)}</dd></div>
          </dl>
          <a class="btn full" href="#/">Continue shopping</a>
        </div>
      </div>`;
  }

  // --- product details dialog -------------------------------------------------------

  function average(values) {
    return values.reduce((a, b) => a + b, 0) / values.length;
  }

  function openDetails(id) {
    const p = byId(id);
    // BUG 7: the seeded build assumes every product has reviews; Wool Socks has none (null).
    const reviews = SEEDED ? p.reviews : p.reviews || [];
    const rating = reviews.length ? `★ ${average(reviews).toFixed(1)} · ${reviews.length} reviews` : "No reviews yet";
    const overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="details-title" data-testid="product-dialog">
        <div class="thumb" role="img" aria-label="${esc(p.name)}">${p.emoji}</div>
        <h2 id="details-title">${esc(p.name)}</h2>
        <p>${esc(p.description)}</p>
        <p class="muted" data-testid="rating">${rating}</p>
        <p class="price">${money(p.price)}</p>
        <div class="actions">
          <button class="btn" data-action="close">Close</button>
          <button class="btn primary" data-action="add-close" data-id="${p.id}">Add to cart</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('[data-action="close"]').focus();
  }

  function closeDetails() {
    document.querySelectorAll(".overlay").forEach((el) => el.remove());
  }

  // --- events ----------------------------------------------------------------------

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) {
      if (event.target.classList.contains("overlay")) closeDetails();
      return;
    }
    const id = target.dataset.id;
    const line = state.cart.find((l) => l.id === id);
    switch (target.dataset.action) {
      case "add":
        addToCart(id);
        break;
      case "details":
        openDetails(id);
        break;
      case "close":
        closeDetails();
        break;
      case "add-close":
        addToCart(id);
        closeDetails();
        break;
      case "inc":
        line.qty = Math.min(99, line.qty + 1);
        saveCart();
        viewCart();
        break;
      case "dec":
        if (line.qty > 1) line.qty -= 1;
        else state.cart = state.cart.filter((l) => l.id !== id);
        saveCart();
        viewCart();
        break;
      case "remove":
        state.cart = state.cart.filter((l) => l.id !== id);
        saveCart();
        toast(`${byId(id).name} removed from cart.`);
        viewCart();
        break;
    }
  });

  document.addEventListener("input", (event) => {
    const key = event.target.dataset.input;
    if (!key) return;
    if (key === "search") {
      state.query = event.target.value;
      renderResults();
    } else {
      state.form[key] = event.target.value;
      if (key === "shipping") renderCheckoutSummary();
    }
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.dataset.form;
    if (!form) return;
    event.preventDefault();
    if (form === "coupon") applyCoupon(event.target.elements.coupon.value);
    if (form === "checkout") placeOrder();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDetails();
  });

  // --- routing ---------------------------------------------------------------------

  function route() {
    closeDetails();
    const hash = location.hash || "#/";
    const order = hash.match(/^#\/order\/([\w-]+)/);
    if (hash.startsWith("#/cart")) viewCart();
    else if (hash.startsWith("#/checkout")) viewCheckout();
    else if (order) viewOrder(order[1]);
    else viewShop();
    window.scrollTo(0, 0);
  }

  async function start() {
    app.innerHTML = `<p class="muted">Loading products…</p>`;
    const res = await fetch("api/products");
    state.products = await res.json();
    saveCart();
    window.addEventListener("hashchange", route);
    route();
  }

  start();
})();

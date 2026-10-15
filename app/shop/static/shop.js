/* ============================================================
   Socratic Shop — storefront behaviour

   Progressive enhancement: every action here has a working
   server-rendered fallback (plain form posts and links). The JS
   upgrades them to fetch calls so the cart, wishlist and assistant
   never cost a full page reload.

   Modules: theme, nav, cart drawer, add-to-cart, wishlist,
   live search, assistant chat, countdown, gallery, tabs,
   quantity steppers, filters, checkout totals, toasts.
   ============================================================ */

(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  var naira = function (value) {
    return '\u20a6' + Math.round(Number(value) || 0).toLocaleString('en-NG');
  };

  /* ---------- Toasts ---------- */

  function toast(message, kind) {
    var stack = $('[data-toast-stack]');
    if (!stack || !message) { return; }
    var el = document.createElement('div');
    el.className = 'toast toast-' + (kind || 'success');
    el.setAttribute('role', 'status');

    var icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('class', 'ico');
    icon.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', kind === 'error' ? '#i-info' : '#i-check');
    icon.appendChild(use);

    var span = document.createElement('span');
    span.textContent = message;
    el.appendChild(icon);
    el.appendChild(span);
    stack.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .25s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 260);
    }, 2600);
  }

  /* ---------- Theme ---------- */

  function initTheme() {
    var btn = $('[data-theme-toggle]');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('shop-theme', next); } catch (e) { /* ignore */ }
    });
  }

  /* ---------- Mobile category nav ---------- */

  function initNav() {
    var btn = $('[data-menu-toggle]');
    if (!btn) { return; }
    btn.addEventListener('click', function () {
      var open = document.body.classList.toggle('nav-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  /* ---------- Cart ---------- */

  var cartState = null;

  function setCartBadge(count) {
    $$('[data-cart-count]').forEach(function (el) {
      el.textContent = count;
      if (count > 0) { el.removeAttribute('hidden'); } else { el.setAttribute('hidden', ''); }
    });
  }

  function renderCart(cart) {
    cartState = cart;
    var body = $('[data-cart-body]');
    var foot = $('[data-cart-foot]');
    var drawerCount = $('[data-cart-drawer-count]');
    if (!body) { return; }

    setCartBadge(cart.item_count || 0);
    if (drawerCount) { drawerCount.textContent = cart.item_count ? '(' + cart.item_count + ')' : ''; }

    body.textContent = '';
    if (!cart.items || !cart.items.length) {
      var empty = document.createElement('p');
      empty.className = 'drawer-empty';
      empty.textContent = 'Your cart is empty.';
      body.appendChild(empty);
      if (foot) { foot.setAttribute('hidden', ''); }
      return;
    }

    cart.items.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'cart-line-mini';

      var img = document.createElement('img');
      img.src = item.image;
      img.alt = '';
      img.loading = 'lazy';
      img.width = 70;
      img.height = 70;

      var info = document.createElement('div');
      info.className = 'cart-line-mini-info';

      var link = document.createElement('a');
      link.href = '/shop/p/' + item.slug;
      link.textContent = item.title;

      var price = document.createElement('strong');
      price.textContent = naira(item.line_total);

      var controls = document.createElement('div');
      controls.className = 'cart-line-mini-controls';

      var minus = document.createElement('button');
      minus.type = 'button';
      minus.className = 'cart-mini-remove';
      minus.textContent = '\u2212';
      minus.setAttribute('aria-label', 'Decrease quantity');
      minus.addEventListener('click', function () {
        mutateCart({ action: 'set', product_id: item.id, qty: item.qty - 1 });
      });

      var qty = document.createElement('span');
      qty.textContent = 'Qty ' + item.qty;

      var plus = document.createElement('button');
      plus.type = 'button';
      plus.className = 'cart-mini-remove';
      plus.textContent = '+';
      plus.setAttribute('aria-label', 'Increase quantity');
      plus.addEventListener('click', function () {
        mutateCart({ action: 'set', product_id: item.id, qty: item.qty + 1 });
      });

      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'cart-mini-remove';
      remove.textContent = 'Remove';
      remove.addEventListener('click', function () {
        mutateCart({ action: 'remove', product_id: item.id });
      });

      controls.appendChild(minus);
      controls.appendChild(qty);
      controls.appendChild(plus);
      controls.appendChild(remove);

      info.appendChild(link);
      info.appendChild(price);
      info.appendChild(controls);

      row.appendChild(img);
      row.appendChild(info);
      body.appendChild(row);
    });

    if (foot) {
      foot.removeAttribute('hidden');
      var sub = $('[data-cart-subtotal]', foot);
      var ship = $('[data-cart-shipping]', foot);
      var total = $('[data-cart-total]', foot);
      if (sub) { sub.textContent = cart.subtotal_display; }
      if (ship) { ship.textContent = cart.shipping_display; }
      if (total) { total.textContent = cart.total_display; }

      var freeBox = $('[data-cart-freeship]', foot);
      var bar = $('[data-cart-freeship-bar]', foot);
      var text = $('[data-cart-freeship-text]', foot);
      if (freeBox && bar && text) {
        if (cart.free_shipping_remaining > 0) {
          var threshold = cart.subtotal + cart.free_shipping_remaining;
          var pct = threshold ? Math.min(100, ((cart.subtotal - cart.discount) / threshold) * 100) : 0;
          freeBox.removeAttribute('hidden');
          bar.style.width = Math.max(4, pct).toFixed(1) + '%';
          text.textContent = 'Add ' + cart.free_shipping_remaining_display + ' more for free delivery.';
        } else {
          freeBox.setAttribute('hidden', '');
        }
      }
    }
  }

  function openCart() {
    var drawer = $('[data-cart-drawer]');
    var backdrop = $('[data-cart-backdrop]');
    if (!drawer) { return; }
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) { backdrop.removeAttribute('hidden'); requestAnimationFrame(function () { backdrop.classList.add('is-open'); }); }
    document.body.style.overflow = 'hidden';
    refreshCart();
  }

  function closeCart() {
    var drawer = $('[data-cart-drawer]');
    var backdrop = $('[data-cart-backdrop]');
    if (drawer) {
      drawer.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) {
      backdrop.classList.remove('is-open');
      setTimeout(function () { backdrop.setAttribute('hidden', ''); }, 220);
    }
    document.body.style.overflow = '';
  }

  function fetchCart() {
    return fetch('/shop/api/cart', { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (data) { return data.cart || data; });
  }

  function refreshCart() {
    return fetchCart().then(renderCart).catch(function () { /* leave server-rendered state */ });
  }

  function mutateCart(payload) {
    return fetch('/shop/api/cart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.cart) { renderCart(data.cart); }
        if (data.message) { toast(data.message, data.ok === false ? 'error' : 'success'); }
        return data;
      })
      .catch(function () { toast('Could not update the cart. Check your connection.', 'error'); });
  }

  function initCartDrawer() {
    $$('[data-cart-open]').forEach(function (el) {
      el.addEventListener('click', function (e) { e.preventDefault(); openCart(); });
    });
    $$('[data-cart-close]').forEach(function (el) { el.addEventListener('click', closeCart); });
    var backdrop = $('[data-cart-backdrop]');
    if (backdrop) { backdrop.addEventListener('click', closeCart); }

    refreshCart();
  }

  /* ---------- Add to cart (fetch upgrade for the plain form post) ---------- */

  function initAddToCart() {
    $$('[data-add-form]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) { return; }
        event.preventDefault();

        var submitter = event.submitter || null;
        var data = new FormData(form);
        var payload = {
          action: 'add',
          product_id: data.get('product_id'),
          qty: data.get('qty') || 1
        };
        var button = submitter || $('button[type="submit"]', form);
        if (button) { button.disabled = true; }

        mutateCart(payload).then(function () {
          if (button) { button.disabled = false; }
          var next = submitter && submitter.getAttribute('data-add-next');
          if (next) { window.location.href = next; return; }
          openCart();
        });
      });
    });
  }

  /* ---------- Wishlist ---------- */

  function initWishlist() {
    $$('[data-wishlist-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-product-id');
        if (!id) { return; }
        fetch('/shop/api/wishlist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ product_id: id })
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok) { toast(data.message || 'Could not save that.', 'error'); return; }
            $$('[data-wishlist-toggle][data-product-id="' + id + '"]').forEach(function (other) {
              other.setAttribute('aria-pressed', data.saved ? 'true' : 'false');
              var label = $('[data-wishlist-label]', other);
              if (label) { label.textContent = data.saved ? 'Saved' : 'Save'; }
            });
            toast(data.message);
          })
          .catch(function () { toast('Could not reach the wishlist.', 'error'); });
      });
    });
  }

  /* ---------- Live search suggestions ---------- */

  function initLiveSearch() {
    var form = $('[data-search-form]');
    var input = $('[data-search-input]');
    var panel = $('[data-suggest-panel]');
    if (!form || !input || !panel) { return; }

    var timer = null;
    var items = [];
    var active = -1;

    function hide() {
      panel.setAttribute('hidden', '');
      panel.textContent = '';
      items = [];
      active = -1;
    }

    function render(results, query) {
      panel.textContent = '';
      items = results;
      active = -1;

      if (!results.length) {
        var none = document.createElement('p');
        none.className = 'suggest-empty';
        none.textContent = 'No direct match. Ask the AI assistant instead.';
        panel.appendChild(none);
      }

      results.forEach(function (product) {
        var a = document.createElement('a');
        a.className = 'suggest-item';
        a.href = product.url;

        var img = document.createElement('img');
        img.src = product.image;
        img.alt = '';
        img.loading = 'lazy';

        var text = document.createElement('span');
        text.className = 'suggest-item-text';
        var strong = document.createElement('strong');
        strong.textContent = product.title;
        var sub = document.createElement('span');
        sub.textContent = product.brand + ' \u00b7 ' + product.category_label;
        text.appendChild(strong);
        text.appendChild(sub);

        var price = document.createElement('em');
        price.textContent = product.price_display;

        a.appendChild(img);
        a.appendChild(text);
        a.appendChild(price);
        panel.appendChild(a);
      });

      var askAi = document.createElement('button');
      askAi.type = 'button';
      askAi.className = 'suggest-ai';
      var spark = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      spark.setAttribute('class', 'ico');
      var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '#i-sparkles');
      spark.appendChild(use);
      askAi.appendChild(spark);
      var aiText = document.createElement('span');
      aiText.textContent = 'Ask Ama about \u201c' + query + '\u201d';
      askAi.appendChild(aiText);
      askAi.addEventListener('click', function () {
        hide();
        openAssistant(query);
      });
      panel.appendChild(askAi);

      panel.removeAttribute('hidden');
    }

    function highlight(next) {
      var links = $$('.suggest-item', panel);
      if (!links.length) { return; }
      active = (next + links.length) % links.length;
      links.forEach(function (el, i) { el.classList.toggle('is-active', i === active); });
      links[active].scrollIntoView({ block: 'nearest' });
    }

    input.addEventListener('input', function () {
      var query = input.value.trim();
      clearTimeout(timer);
      if (query.length < 2) { hide(); return; }
      timer = setTimeout(function () {
        fetch('/shop/api/search?q=' + encodeURIComponent(query) + '&limit=6', { headers: { 'Accept': 'application/json' } })
          .then(function (r) { return r.json(); })
          .then(function (data) { render(data.results || [], query); })
          .catch(function () { hide(); });
      }, 180);
    });

    input.addEventListener('keydown', function (event) {
      if (panel.hasAttribute('hidden')) { return; }
      if (event.key === 'ArrowDown') { event.preventDefault(); highlight(active + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); highlight(active - 1); }
      else if (event.key === 'Escape') { hide(); }
      else if (event.key === 'Enter' && active >= 0) {
        var link = $$('.suggest-item', panel)[active];
        if (link) { event.preventDefault(); window.location.href = link.href; }
      }
    });

    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) { hide(); }
    });
  }

  /* ---------- AI assistant ---------- */

  function iconEl(name) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ico');
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.appendChild(use);
    return svg;
  }

  function renderProducts(container, products) {
    var wrap = document.createElement('div');
    wrap.className = 'chat-products';
    products.forEach(function (product) {
      var a = document.createElement('a');
      a.className = 'chat-product';
      a.href = product.url;

      var img = document.createElement('img');
      img.src = product.image;
      img.alt = '';
      img.loading = 'lazy';

      var span = document.createElement('span');
      var strong = document.createElement('strong');
      strong.textContent = product.title;
      var em = document.createElement('em');
      em.textContent = product.price_display + '  \u00b7  ' + product.rating + '\u2605 (' + product.reviews + ')';
      span.appendChild(strong);
      span.appendChild(em);

      a.appendChild(img);
      a.appendChild(span);
      wrap.appendChild(a);
    });
    container.appendChild(wrap);
  }

  function renderComparison(container, comparison) {
    if (!comparison || !comparison.rows) { return; }
    var wrap = document.createElement('div');
    wrap.className = 'chat-compare';

    var table = document.createElement('table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    var corner = document.createElement('th');
    corner.textContent = '';
    headRow.appendChild(corner);
    comparison.columns.forEach(function (name) {
      var th = document.createElement('th');
      th.textContent = name;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    comparison.rows.forEach(function (row) {
      var tr = document.createElement('tr');
      var th = document.createElement('th');
      th.setAttribute('scope', 'row');
      th.textContent = row.label;
      tr.appendChild(th);
      [row.a, row.b].forEach(function (value) {
        var td = document.createElement('td');
        td.textContent = value == null ? '\u2014' : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    container.appendChild(wrap);
  }

  function addMessage(log, role, build) {
    var msg = document.createElement('div');
    msg.className = 'chat-msg chat-' + role;
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    build(bubble);
    msg.appendChild(bubble);
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  function initChat(root) {
    var log = $('[data-chat-log]', root);
    var form = $('[data-chat-form]', root);
    var input = $('[data-chat-input]', root);
    var chips = $('[data-chat-chips]', root);
    if (!log || !form || !input) { return null; }

    var busy = false;
    var contextProduct = $('[data-product]') ? $('[data-product]').getAttribute('data-product') : null;

    function setChips(list) {
      if (!chips) { return; }
      chips.textContent = '';
      (list || []).forEach(function (text) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chip';
        btn.textContent = text;
        btn.addEventListener('click', function () { send(text); });
        chips.appendChild(btn);
      });
    }

    function typing() {
      var bubble = addMessage(log, 'bot', function (el) {
        var dots = document.createElement('span');
        dots.className = 'chat-typing';
        dots.appendChild(document.createElement('span'));
        dots.appendChild(document.createElement('span'));
        dots.appendChild(document.createElement('span'));
        el.appendChild(dots);
      });
      return bubble.parentElement;
    }

    function send(text) {
      var message = (text || input.value || '').trim();
      if (!message || busy) { return; }
      busy = true;
      input.value = '';

      addMessage(log, 'user', function (el) {
        var p = document.createElement('p');
        p.textContent = message;
        el.appendChild(p);
      });

      var pending = typing();
      var sendBtn = $('.chat-send', form);
      if (sendBtn) { sendBtn.disabled = true; }

      fetch('/shop/api/assistant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ message: message, context_product: contextProduct })
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          pending.remove();
          addMessage(log, 'bot', function (el) {
            var p = document.createElement('p');
            p.textContent = data.reply || 'Sorry, I did not catch that.';
            el.appendChild(p);
            if (data.products && data.products.length) { renderProducts(el, data.products); }
            renderComparison(el, data.comparison);
            var tag = document.createElement('span');
            tag.className = 'ai-engine-tag';
            tag.textContent = data.engine === 'llm' ? 'AI answer' : 'Catalogue search';
            el.appendChild(tag);
          });
          setChips(data.chips);
        })
        .catch(function () {
          pending.remove();
          addMessage(log, 'bot', function (el) {
            var p = document.createElement('p');
            p.textContent = 'I could not reach the server just now. Please try again.';
            el.appendChild(p);
          });
        })
        .then(function () {
          busy = false;
          if (sendBtn) { sendBtn.disabled = false; }
          input.focus();
        });
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      send();
    });

    $$('[data-chat-chip]', root).forEach(function (chip) {
      chip.addEventListener('click', function () { send(chip.textContent.trim()); });
    });

    return { send: send, input: input, root: root };
  }

  var primaryChat = null;

  function openAssistant(prefill) {
    var drawer = $('[data-assistant-drawer]');
    var backdrop = $('[data-assistant-backdrop]');
    if (!drawer) { return; }
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) { backdrop.removeAttribute('hidden'); requestAnimationFrame(function () { backdrop.classList.add('is-open'); }); }
    document.body.style.overflow = 'hidden';

    var input = $('[data-chat-input]', drawer);
    if (input) { setTimeout(function () { input.focus(); }, 260); }

    if (prefill) {
      var chat = drawerChat;
      if (chat) { chat.send(prefill); }
    }
  }

  function closeAssistant() {
    var drawer = $('[data-assistant-drawer]');
    var backdrop = $('[data-assistant-backdrop]');
    if (drawer) {
      drawer.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
    }
    if (backdrop) {
      backdrop.classList.remove('is-open');
      setTimeout(function () { backdrop.setAttribute('hidden', ''); }, 220);
    }
    document.body.style.overflow = '';
  }

  var drawerChat = null;

  function initAssistant() {
    // Bind every chat surface independently: the drawer and the full page.
    $$('[data-chat-root]').forEach(function (root) {
      var chat = initChat(root);
      if (!chat) { return; }
      if (root.hasAttribute('data-chat-primary')) { primaryChat = chat; }
      if (root.hasAttribute('data-assistant-drawer')) { drawerChat = chat; }
    });

    $$('[data-assistant-open]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var prefill = btn.getAttribute('data-assistant-send') || '';
        // On the dedicated assistant page, keep the conversation inline.
        if (primaryChat) {
          if (prefill) { primaryChat.send(prefill); }
          var panel = primaryChat.root;
          if (panel && panel.scrollIntoView) { panel.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
          var inlineInput = $('[data-chat-input]', panel);
          if (inlineInput) { inlineInput.focus(); }
          return;
        }
        openAssistant(prefill);
      });
    });

    $$('[data-assistant-close]').forEach(function (el) { el.addEventListener('click', closeAssistant); });
    var backdrop = $('[data-assistant-backdrop]');
    if (backdrop) { backdrop.addEventListener('click', closeAssistant); }

    // Sidebar prompt chips on the assistant page sit outside the chat root.
    $$('[data-chat-chip]').forEach(function (chip) {
      if (chip.closest('[data-chat-root]')) { return; }
      chip.addEventListener('click', function () {
        var target = primaryChat || drawerChat;
        if (target) { target.send(chip.textContent.trim()); }
      });
    });

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') { return; }
      closeCart();
      closeAssistant();
    });
  }

  /* ---------- Countdown ---------- */

  function initCountdowns() {
    var nodes = $$('[data-countdown]');
    if (!nodes.length) { return; }

    var targets = nodes.map(function (node) {
      var ends = Date.parse(node.getAttribute('data-countdown'));
      return { node: node, ends: isNaN(ends) ? null : ends };
    });

    function pad(n) { return String(n).padStart(2, '0'); }

    function tick() {
      var now = Date.now();
      targets.forEach(function (target) {
        if (!target.ends) { return; }
        var left = Math.max(0, target.ends - now);
        var totalSeconds = Math.floor(left / 1000);
        var hours = Math.floor(totalSeconds / 3600);
        var minutes = Math.floor((totalSeconds % 3600) / 60);
        var seconds = totalSeconds % 60;
        var h = $('[data-cd-h]', target.node);
        var m = $('[data-cd-m]', target.node);
        var s = $('[data-cd-s]', target.node);
        if (h) { h.textContent = pad(hours); }
        if (m) { m.textContent = pad(minutes); }
        if (s) { s.textContent = pad(seconds); }
      });
    }

    tick();
    setInterval(tick, 1000);
  }

  /* ---------- Hero carousel ---------- */

  function initCarousel() {
    var root = $('[data-carousel]');
    if (!root) { return; }
    var track = $('[data-carousel-track]', root);
    var dotsBox = $('[data-carousel-dots]', root);
    if (!track || !dotsBox) { return; }
    var slides = $$('.hero-slide', track);
    if (slides.length < 2) { return; }

    var current = 0;
    slides.forEach(function (_, index) {
      var dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'hero-dot' + (index === 0 ? ' is-active' : '');
      dot.setAttribute('role', 'tab');
      dot.setAttribute('aria-label', 'Go to highlight ' + (index + 1));
      dot.addEventListener('click', function () { go(index); });
      dotsBox.appendChild(dot);
    });

    function go(index) {
      current = index;
      track.scrollTo({ left: track.clientWidth * index, behavior: 'smooth' });
      $$('.hero-dot', dotsBox).forEach(function (dot, i) {
        dot.classList.toggle('is-active', i === index);
      });
    }

    track.addEventListener('scroll', function () {
      var index = Math.round(track.scrollLeft / Math.max(track.clientWidth, 1));
      if (index !== current) {
        current = index;
        $$('.hero-dot', dotsBox).forEach(function (dot, i) {
          dot.classList.toggle('is-active', i === index);
        });
      }
    }, { passive: true });

    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setInterval(function () {
        go((current + 1) % slides.length);
      }, 8000);
    }
  }

  /* ---------- Product gallery ---------- */

  function initGallery() {
    var main = $('[data-gallery-main]');
    if (!main) { return; }
    $$('[data-gallery-thumb]').forEach(function (thumb) {
      thumb.addEventListener('click', function () {
        main.src = thumb.getAttribute('data-src');
        $$('[data-gallery-thumb]').forEach(function (other) {
          var on = other === thumb;
          other.classList.toggle('is-active', on);
          other.setAttribute('aria-selected', on ? 'true' : 'false');
        });
      });
    });
  }

  /* ---------- Tabs ---------- */

  function initTabs() {
    $$('[data-tabs]').forEach(function (group) {
      var tabs = $$('[data-tab]', group);
      var panels = $$('[data-panel]', group);
      tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
          var name = tab.getAttribute('data-tab');
          tabs.forEach(function (t) {
            var on = t === tab;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
          });
          panels.forEach(function (panel) {
            var on = panel.getAttribute('data-panel') === name;
            panel.classList.toggle('is-active', on);
            if (on) { panel.removeAttribute('hidden'); } else { panel.setAttribute('hidden', ''); }
          });
        });
      });
    });
  }

  /* ---------- Quantity steppers ---------- */

  function initQtySteppers() {
    $$('[data-qty-stepper]').forEach(function (stepper) {
      var input = $('[data-qty-input]', stepper);
      if (!input) { return; }
      var min = parseInt(input.getAttribute('min') || '1', 10);
      var max = parseInt(input.getAttribute('max') || '99', 10);

      function clamp(value) {
        if (isNaN(value)) { value = min; }
        return Math.min(Math.max(value, min), Math.max(max, min));
      }

      var up = $('[data-qty-up]', stepper);
      var down = $('[data-qty-down]', stepper);
      if (up) {
        up.addEventListener('click', function () {
          input.value = clamp(parseInt(input.value, 10) + 1);
          input.dispatchEvent(new Event('change', { bubbles: true }));
        });
      }
      if (down) {
        down.addEventListener('click', function () {
          input.value = clamp(parseInt(input.value, 10) - 1);
          input.dispatchEvent(new Event('change', { bubbles: true }));
        });
      }
      input.addEventListener('change', function () {
        input.value = clamp(parseInt(input.value, 10));
      });
    });
  }

  /* ---------- Variant chips ---------- */

  function initVariants() {
    $$('[data-variant-group]').forEach(function (group) {
      var options = $$('[data-variant-option]', group);
      options.forEach(function (option) {
        option.addEventListener('click', function () {
          options.forEach(function (other) {
            var on = other === option;
            other.classList.toggle('is-active', on);
            other.setAttribute('aria-pressed', on ? 'true' : 'false');
          });
        });
      });
    });
  }

  /* ---------- Listing filters ---------- */

  function initFilters() {
    $$('[data-filter-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var panel = $('[data-filter-panel]');
        if (!panel) { return; }
        var open = panel.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });

    $$('[data-autosubmit]').forEach(function (select) {
      select.addEventListener('change', function () { select.form.submit(); });
    });

    $$('[data-autosubmit-qty]').forEach(function (input) {
      input.addEventListener('change', function () { input.form.submit(); });
    });

    $$('[data-filter-clear]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var form = btn.closest('form');
        if (!form) { return; }
        $$('input[type="checkbox"], input[type="radio"]', form).forEach(function (input) {
          input.checked = false;
        });
        $$('input[type="number"]', form).forEach(function (input) { input.value = ''; });
        form.submit();
      });
    });

    $$('[data-price-max]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var form = btn.closest('form');
        if (!form) { return; }
        var max = $('input[name="max_price"]', form);
        if (max) { max.value = btn.getAttribute('data-price-max'); }
        form.submit();
      });
    });

    $$('[data-coupon-fill]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var input = $('#coupon-code');
        if (input) { input.value = btn.getAttribute('data-coupon-fill'); input.focus(); }
      });
    });
  }

  /* ---------- Checkout live totals ---------- */

  function initCheckoutTotals() {
    var form = $('[data-checkout]');
    if (!form) { return; }

    var net = parseFloat(form.getAttribute('data-net')) || 0;
    var threshold = parseFloat(form.getAttribute('data-free-threshold')) || 0;
    var standard = parseFloat(form.getAttribute('data-ship-standard')) || 0;
    var express = parseFloat(form.getAttribute('data-ship-express')) || 0;
    var vatRate = parseFloat(form.getAttribute('data-vat-rate')) || 0;

    function update() {
      var selected = $('input[name="delivery"]:checked', form);
      var isExpress = selected && selected.value === 'express';
      var shipping = net >= threshold ? 0 : (isExpress ? express : standard);
      var total = net + shipping;

      var shipEl = $('[data-checkout-shipping]', form);
      var totalEl = $('[data-checkout-total]', form);
      var vatEl = $('[data-checkout-vat]', form);

      if (shipEl) { shipEl.textContent = shipping === 0 ? 'Free' : naira(shipping); }
      if (totalEl) { totalEl.textContent = naira(total); }
      if (vatEl) { vatEl.textContent = naira(total * vatRate / (1 + vatRate)); }
    }

    $$('input[name="delivery"]', form).forEach(function (radio) {
      radio.addEventListener('change', update);
    });
    update();
  }

  /* ---------- Boot ---------- */

  function boot() {
    initTheme();
    initNav();
    initCartDrawer();
    initAddToCart();
    initWishlist();
    initLiveSearch();
    initAssistant();
    initCountdowns();
    initCarousel();
    initGallery();
    initTabs();
    initQtySteppers();
    initVariants();
    initFilters();
    initCheckoutTotals();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

/* Persistent waitlist CTA — shared across the homepage, the driver meter and lesson posts.
 * Any `<form class="wl-cta" data-goal="...">` inside a `.wl-cta-band` is wired to post to the
 * SAME Brevo waitlist list as the homepage #waitlist-form (a separate list from the newsletter),
 * and fires its own Plausible goal so each placement is measurable (WaitlistCTA_meter,
 * WaitlistCTA_post, …). No pop-ups, no overlay — a calm inline band. Styles are injected once
 * with CSS-var fallbacks so it matches every page and theme without duplicating CSS. */
(function () {
  var forms = document.querySelectorAll('form.wl-cta');
  if (!forms.length) return;

  // Brevo endpoint — the Live Driver Meter WAITLIST list (matches index.html #waitlist-form).
  var EP = 'https://95e1cb32.sibforms.com/serve/MUIFABvEl_xm-OfIzAty0_yziL-ngoTHkJbZ2SGOzlnkp9AwdzeceN0lDVr4C4RvQLiMKkIB3Kjy02Z0XWayVi7HslmQgGwt2reSQ2dxrOpIUiC63NP4v8bWa2gr-SPsmcifggD9uQYf8K5LOHojLfHj4w15wU-GSBjYa_kPVWJ744atOkASGv4GHNXbXiFgBfc8f_cH40pgHZXhnQ==';

  if (!document.getElementById('wl-cta-style')) {
    var s = document.createElement('style');
    s.id = 'wl-cta-style';
    s.textContent =
      '.wl-cta-band{max-width:640px;margin:28px auto;padding:20px 22px;background:var(--panel,#121826);' +
      'border:1px solid var(--line,#1e2740);border-radius:12px}' +
      '.wl-cta-title{margin:0 0 4px;font-size:16px;font-weight:700;color:var(--ink,#e7ecf5)}' +
      '.wl-cta-sub{margin:0 0 12px;font-size:13px;line-height:1.5;color:var(--muted,#8a97b1)}' +
      '.wl-cta{display:flex;gap:8px;flex-wrap:wrap}' +
      '.wl-cta input{flex:1 1 200px;min-width:0;background:var(--panel-2,#0f1420);' +
      'border:1px solid var(--line,#1e2740);color:var(--ink,#e7ecf5);border-radius:8px;padding:9px 12px;font-size:14px}' +
      '.wl-cta button{background:var(--accent,#f59e0b);color:#1a1200;border:0;border-radius:8px;' +
      'padding:9px 16px;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}' +
      '.wl-cta button:hover{filter:brightness(1.05)}' +
      '.wl-cta-note{margin:10px 0 0;font-size:11.5px;color:var(--muted,#8a97b1)}';
    document.head.appendChild(s);
  }

  function wire(form) {
    var band = form.closest ? form.closest('.wl-cta-band') : form.parentNode;
    var note = band ? band.querySelector('.wl-cta-note') : null;
    var goal = form.getAttribute('data-goal') || 'WaitlistCTA';
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var inp = form.querySelector('input[type=email]');
      var email = ((inp && inp.value) || '').trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { if (note) note.textContent = 'Please enter a valid email.'; return; }
      if (note) note.textContent = 'Adding you…';
      try {
        var fd = new FormData();
        fd.append('EMAIL', email);
        fd.append('email_address_check', '');   // Brevo honeypot — stays empty
        fd.append('locale', 'en');
        fetch(EP, { method: 'POST', mode: 'no-cors', body: fd });
      } catch (e) { /* opaque no-cors response; treat as sent */ }
      try { window.plausible && window.plausible(goal); } catch (e) { /* ignore */ }
      if (note) note.textContent = "You're on the waitlist — we'll email you when the live tool is ready.";
      form.reset();
    });
  }

  [].forEach.call(forms, wire);
})();

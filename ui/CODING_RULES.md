# FamilyVault UI — Coding Rules

CRITICAL rules learned from debugging. Follow these exactly.

## Rule 1: New screens use PURE DOM only

```js
// ✅ CORRECT — pure document.createElement
function buildMyScreen() {
  var wrap = document.createElement('div');
  wrap.className = 'page';
  var title = document.createElement('div');
  title.style.cssText = 'font-size:22px;font-weight:600;color:var(--fg)';
  title.textContent = 'My Screen';
  wrap.appendChild(title);
  return wrap;
}

// ❌ WRONG — mixing helpers with DOM elements crashes
function buildMyScreen() {
  var realDomEl = document.createElement('div');
  return div({class:'page'},
    realDomEl  // TypeError: div() cannot accept real DOM elements
  );
}
```

## Rule 2: No string onclick in el()

```js
// ✅ CORRECT — function reference
var btn = document.createElement('button');
btn.onclick = function() { doSomething(); };

// ❌ WRONG — string onclick crashes
el('button', {onclick: 'doSomething()'}, 'Click me');
// TypeError: Failed to execute 'addEventListener': parameter 2 is not of type 'Object'
```

## Rule 3: Never use req() in new screens

```js
// ✅ CORRECT — direct fetch with token
var token = (typeof S !== 'undefined' && S.token)
  ? S.token
  : localStorage.getItem('fv_token') || '';

fetch('https://1oj10740w0.execute-api.eu-west-1.amazonaws.com/my-route', {
  headers: { Authorization: 'Bearer ' + token }
})
.then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
.then(function(data) { /* render */ })
.catch(function(e) { console.error(e); });

// ❌ WRONG — req() uses await without async, silent failure
req('/my-route', {}, S.token).then(function(data) { ... });
```

## Rule 4: Use setTimeout for initial data load

```js
// ✅ CORRECT — gives S.token time to be set
function buildMyScreen() {
  var wrap = document.createElement('div');
  // ... build UI ...
  setTimeout(function() { loadData(); }, 300);
  return wrap;
}

// ❌ WRONG — S.token might not be set yet
function buildMyScreen() {
  var wrap = document.createElement('div');
  loadData(); // token might be empty!
  return wrap;
}
```

## Rule 5: Always patch from index-backup.html

```powershell
# ✅ CORRECT
$html = Get-Content "index-backup.html" -Raw -Encoding UTF8
# ... patch ...
$html | Out-File "index-new.html" -Encoding UTF8 -NoNewline

# ❌ WRONG — chaining patches accumulates bugs
$html = Get-Content "index-final-v3.html" -Raw -Encoding UTF8
```

## Rule 6: Inject before </script>, not between functions

```powershell
# ✅ CORRECT — works even if new function is the last one
$ip = $html.LastIndexOf("</script>")
$html = $html.Substring(0,$ip) + $newFn + $html.Substring($ip)

# ❌ WRONG — fails if function is last (IndexOf returns -1)
$fnEnd = $html.IndexOf("`nfunction ", $fnStart + 10)  # returns -1 if last!
```

## Rule 7: Verify before every deploy

```powershell
Write-Host "Nav:" ($html -match "s:'newscreen'")
Write-Host "Case:" ($html -match "case 'newscreen'")
Write-Host "Function:" ($html -match "function buildNewScreen")
Write-Host "No el() errors:" (-not ($html -match "el\('(span|button)',\{onclick:"))
Write-Host "Pure DOM:" ($html -match "document\.createElement")
# All must be True before deploying
```

## Rule 8: Chart.js loading

```js
// ✅ CORRECT — lazy load Chart.js, cache it
function loadChartJs(cb) {
  if (window.Chart) { cb(); return; }
  var s = document.createElement('script');
  s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js';
  s.onload = cb;
  document.head.appendChild(s);
}

// Always destroy before re-creating
if (ctx._ch) ctx._ch.destroy();
ctx._ch = new Chart(ctx, { ... });
```

## CSS Variables available

```css
var(--fg)    /* primary text */
var(--fg3)   /* muted text */
var(--bg)    /* page background */
var(--card)  /* card background */
var(--wire)  /* border color */
var(--ac)    /* accent color (primary action) */
var(--ok)    /* success green */
var(--vi)    /* violet */
```

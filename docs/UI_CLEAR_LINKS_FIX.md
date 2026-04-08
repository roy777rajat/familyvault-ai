# UI WebSocket Handler — Required Changes for v15.3

## The Problem (BUG-A)
Download link cards from previous turns kept re-appearing on every new message.
Root cause: the frontend was accumulating `{"type":"links"}` events in state
and never clearing them at the start of a new turn.

## The Fix
The backend (v15.3) now sends `{"type":"clear_links"}` as the very first
WebSocket message of every new turn, before any tokens or links are pushed.

Your WebSocket `onmessage` handler MUST handle this event to wipe the link state.

---

## Code Change Required in your UI (index.html / app JS)

### Find your onmessage handler — it will look roughly like this:

```js
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "token") {
    appendToken(msg.content);
  } else if (msg.type === "links") {
    renderLinkCards(msg.links);   // ← THIS is what was accumulating
  } else if (msg.type === "html") {
    renderHTML(msg.content);
  } else if (msg.type === "final") {
    finaliseMessage(msg);
  }
  // ... etc
};
```

### Add the clear_links handler — ONE line:

```js
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  // ✅ NEW: wipe link cards at the start of every new turn
  if (msg.type === "clear_links") {
    clearLinkCards();   // set your links state to []
    return;
  }

  if (msg.type === "token") {
    appendToken(msg.content);
  } else if (msg.type === "links") {
    renderLinkCards(msg.links);
  } else if (msg.type === "html") {
    renderHTML(msg.content);
  } else if (msg.type === "final") {
    finaliseMessage(msg);
  }
};
```

### If you use React state, the clear looks like:

```js
if (msg.type === "clear_links") {
  setCurrentLinks([]);   // or whatever your state setter is
  return;
}
```

### If you accumulate links in a plain array:

```js
if (msg.type === "clear_links") {
  currentLinks = [];
  renderLinkCards([]);   // re-render with empty array to remove cards from DOM
  return;
}
```

---

## Summary of all 4 bugs fixed across v15.2 and v15.3

| Bug | Location | Fix |
|-----|----------|-----|
| BUG-A | Frontend `onmessage` | Handle `clear_links` event → wipe link card state |
| BUG-B | `DECOMPOSER_SYSTEM` | "do you have / know about / tell me about" → `content_question` |
| BUG-D | `run_list_documents()` stop-list | Personal names excluded so filter doesn't match everything |
| BUG 1 | `run_list_documents()` | Category name included in keyword filter string |
| BUG 2 | `DECOMPOSER_SYSTEM` | No download intent without explicit download keyword |
| BUG 3 | `run_content_question()` | Strip `**bold**` / `- bullets` from streamed tokens |
| BUG 4 | `load_long_term_memory()` | Strip markdown from LTM before injecting into context |

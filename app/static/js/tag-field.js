/*
 * tag-field.js — one shared, progressively enhanced tag picker for every
 * `tag_text` field in the admin UI (create test, edit test, public results).
 * It replaces the three inline copies of attachTagMenu() it supersedes.
 *
 * SERVER CONTRACT (unchanged, deliberately)
 *   The enhanced element is still the very same `<input data-tag-input="true">`
 *   that WTForms renders for the `tag_text` StringField (`id="tag_text"
 *   name="tag_text"`), and its value is always the comma-separated string
 *   routes.parse_tag_names() consumes. No extra form fields are added, so every
 *   route keeps working untouched. parseNames() below is a faithful port of
 *   parse_tag_names(): split on commas and newlines, trim, drop empties,
 *   de-duplicate case-insensitively keeping the FIRST spelling, re-join with ", ".
 *
 * GRACEFUL DEGRADATION
 *   With JavaScript disabled none of this runs: the server-rendered
 *   <select data-tag-menu="true"> + <button data-tag-add="true"> stay visible and
 *   behave exactly as before, and the input keeps its comma-separated value for
 *   hand-typing. Those fallback controls are hidden (d-none, never removed) only
 *   at the very END of a successful enhancement, so a script error leaves a field
 *   on its working no-JS flow. The hidden <select> also doubles as the
 *   server-rendered tag list this script reads whenever the page did not publish
 *   window.tagFieldSuggestions.
 *
 * IDS / CLASSES / DISCOVERY (explicit choice)
 *   Discovery uses only the data-attributes the templates already render
 *   (data-tag-input / data-tag-menu / data-tag-add) plus new data-tag-field,
 *   data-tag-chips, data-tag-list, data-tag-chip-* hooks on generated nodes.
 *   Generated nodes are looked up through those attributes, never through
 *   hard-coded ids: `id="tag_text"` is already taken and would collide if a page
 *   ever carried two tag fields. The few ids ARIA really needs are derived from
 *   the field's own id (`tag_text` -> `tag_text-tag-list`, `tag_text-tag-opt-3`)
 *   or from a `tag-text-N` counter when the field has none, and are assigned once
 *   so aria-controls / aria-activedescendant stay resolvable across re-renders.
 *
 * STYLING
 *   Bootstrap 5.3 classes only (list-group, list-group-item-action, badge,
 *   btn-close, position-relative/absolute, top-100, start-0, end-0, overflow-auto,
 *   shadow, d-none, flex-wrap, gap-1...). The only raw CSS is what 5.3.3 utilities
 *   cannot express for the floating suggestion list: a z-index (it ships
 *   .z-0/.z-1/.z-2/.z-3 but no z-1000 helper) and a scroll height. Both are inline
 *   styles on that one element.
 *
 * SAFETY
 *   Tag names are free text typed by other admins. They only ever reach the DOM
 *   through textContent or setAttribute; this file never builds markup from string
 *   concatenation and never touches innerHTML.
 *
 * Plain ES2020, no dependencies, no build step, no extra CDN requests.
 */
(function (global) {
  'use strict';

  var LIST_ID_SUFFIX = '-tag-list';
  var OPTION_ID_SUFFIX = '-tag-opt-';
  var MAX_VISIBLE_OPTIONS = 60;
  var fieldCounter = 0;

  /* ------------------------------------------------------------------ *
   * Comma-separated value helpers
   * ------------------------------------------------------------------ */

  // Port of routes.parse_tag_names(): returns display names, first spelling wins.
  function parseNames(value) {
    var text = value === null || value === undefined ? '' : String(value);
    var names = [];
    var chunks = text.replace(/[\r\n]+/g, ',').split(',');
    for (var i = 0; i < chunks.length; i += 1) {
      var name = chunks[i].trim();
      if (!name) continue;
      if (indexOfLower(names, name) !== -1) continue;
      names.push(name);
    }
    return names;
  }

  function indexOfLower(list, name) {
    var key = String(name).toLowerCase();
    for (var i = 0; i < list.length; i += 1) {
      if (String(list[i]).toLowerCase() === key) return i;
    }
    return -1;
  }

  function toKeys(names) {
    var keys = [];
    for (var i = 0; i < names.length; i += 1) {
      var key = String(names[i]).toLowerCase();
      if (keys.indexOf(key) === -1) keys.push(key);
    }
    return keys;
  }

  function withoutKey(list, key) {
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i] !== key) out.push(list[i]);
    }
    return out;
  }

  function withoutKeys(list, drop) {
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      if (drop.indexOf(list[i]) === -1) out.push(list[i]);
    }
    return out;
  }

  function findIn(scope, selector) {
    if (!scope || !scope.querySelector) return null;
    if (scope.matches && scope.matches(selector)) return scope;
    return scope.querySelector(selector);
  }

  // The tag list the server already rendered into the no-JS <select>, skipping
  // its empty "Choose an existing tag" placeholder option.
  function readMenuOptions(menu) {
    var out = [];
    if (!menu || !menu.options) return out;
    for (var i = 0; i < menu.options.length; i += 1) {
      var name = (menu.options[i].value || '').trim();
      if (!name) continue;
      if (indexOfLower(out, name) !== -1) continue;
      out.push(name);
    }
    return out;
  }

  // The page-level list published as
  // `window.tagFieldSuggestions = {{ tag_suggestions | tojson }};`.
  function readGlobalSuggestions() {
    var published = global.tagFieldSuggestions;
    if (!published || typeof published.length !== 'number') return null;
    var out = [];
    for (var i = 0; i < published.length; i += 1) {
      var raw = published[i];
      var name = raw === null || raw === undefined ? '' : String(raw).trim();
      if (!name) continue;
      if (indexOfLower(out, name) !== -1) continue;
      out.push(name);
    }
    return out;
  }

  function el(tagName, className, text) {
    var node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /* ------------------------------------------------------------------ *
   * One field instance.
   *
   * State: `tokens` holds the selected tags as case-folded keys in order,
   * `query` is the raw text of the single token the caret currently sits in
   * (that token doubles as the search box), and `queryIndex` is that token's
   * slot so an edit made in the middle of the list keeps its position. The
   * input's value is always those pieces joined with ", ", which is what makes
   * the widget and the server-side string impossible to disagree.
   * ------------------------------------------------------------------ */
  function enhanceField(input, suggestions) {
    // Look the no-JS fallback up BEFORE the input is moved into a wrapper.
    var menu = input.nextElementSibling
      ? findIn(input.nextElementSibling, '[data-tag-menu="true"]')
      : null;
    if (!menu) menu = findIn(input.parentNode, '[data-tag-menu="true"]');
    if (!menu) return; // not the markup this widget was written for
    var group = menu.parentNode;
    var button = findIn(group, '[data-tag-add="true"]');
    if (!button) return;

    if (!input.id) {
      fieldCounter += 1;
      input.id = 'tag-text-' + fieldCounter;
    }
    var listId = input.id + LIST_ID_SUFFIX;
    var optionIdPrefix = input.id + OPTION_ID_SUFFIX;

    var spellings = {}; // case-folded key -> display name
    var tokens = [];
    var query = '';
    var queryIndex = 0;

    var rows = []; // [{kind: 'create'|'suggestion', name}]
    var rowEls = [];
    var highlighted = -1;
    var dismissed = false; // Escape keeps the list shut until the text changes

    /* ---------- scaffolding ---------- */

    var wrap = el('div', 'position-relative');
    wrap.setAttribute('data-tag-field', 'true');
    input.parentNode.insertBefore(wrap, input);
    // The template's `mb-2` spaced the input from the fallback row, which is now
    // hidden; the wrapper owns the bottom spacing instead.
    input.classList.remove('mb-2');

    var chips = el('div', 'd-flex flex-wrap gap-1 mb-1 align-items-center d-none');
    chips.setAttribute('data-tag-chips', 'true');
    wrap.appendChild(chips);
    wrap.appendChild(input);

    var list = el('ul', 'list-group position-absolute start-0 end-0 top-100 overflow-auto shadow d-none');
    list.id = listId;
    list.setAttribute('role', 'listbox');
    list.setAttribute('data-tag-list', 'true');
    list.setAttribute('aria-label', 'Existing tags');
    list.style.zIndex = '1000'; // no Bootstrap utility reaches this high
    list.style.maxHeight = '16rem'; // scroll a long tag table, do not push the page
    wrap.appendChild(list);

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', listId);
    input.setAttribute('autocomplete', 'off');
    input.spellcheck = false;

    /* ---------- state <-> value ---------- */

    function nameOf(key) {
      return Object.prototype.hasOwnProperty.call(spellings, key) ? spellings[key] : key;
    }

    function namesOf(keys) {
      var out = [];
      for (var i = 0; i < keys.length; i += 1) out.push(nameOf(keys[i]));
      return out;
    }

    // The active token always keeps a slot, so at rest (empty query) the value
    // ends with ", ". That trailing separator is what lets the next keystroke
    // start a fresh tag and makes Enter or a comma commit it.
    function compose() {
      var before = namesOf(tokens.slice(0, queryIndex));
      var after = namesOf(tokens.slice(queryIndex));
      return {
        value: before.concat([query], after).join(', '),
        caret: before.concat([query]).join(', ').length
      };
    }

    function caretOf(node) {
      var raw = node.value;
      try {
        if (typeof node.selectionStart === 'number') {
          var start = node.selectionStart;
          var end = typeof node.selectionEnd === 'number' ? node.selectionEnd : start;
          return { start: start, end: end < start ? start : end };
        }
      } catch (error) {
        // A selection-less input behaves as if the caret were at the end.
      }
      return { start: raw.length, end: raw.length };
    }

    // Splits the value on the comma-delimited token holding the caret. The
    // active text is kept verbatim (tag names contain spaces) and only trimmed
    // where a comparison or a commit needs it, so rebuilding the value from the
    // pieces gives back exactly what the admin typed and the caret can stay put.
    function readValue() {
      var raw = input.value;
      var caret = caretOf(input).end;
      var left = caret > 0 ? raw.lastIndexOf(',', caret - 1) + 1 : 0;
      var right = raw.indexOf(',', caret);
      if (right === -1) right = raw.length;
      var afterFrom = raw.charAt(right) === ',' ? right + 1 : right;
      // The slot opens with the ", " separator; it belongs to the previous tag,
      // not to the text being typed.
      var start = left;
      while (start < right && /\s/.test(raw.charAt(start))) start += 1;
      return {
        before: toKeys(parseNames(raw.slice(0, left))),
        active: raw.slice(start, right),
        after: toKeys(parseNames(raw.slice(afterFrom))),
        beforeRaw: raw.slice(0, left),
        afterRaw: raw.slice(afterFrom)
      };
    }

    function rememberSpelling(chunk) {
      var names = parseNames(chunk);
      for (var i = 0; i < names.length; i += 1) {
        var key = names[i].toLowerCase();
        if (!Object.prototype.hasOwnProperty.call(spellings, key)) spellings[key] = names[i];
      }
    }

    // Prefer the casing the server already knows, so a differently typed match
    // cannot grow a second spelling of the same tag.
    function preferredSpelling(name) {
      var hit = indexOfLower(suggestions, name);
      if (hit !== -1) return suggestions[hit];
      return name;
    }

    /* ---------- rendering ---------- */

    function renderChips() {
      while (chips.firstChild) chips.removeChild(chips.firstChild);
      if (!tokens.length) {
        chips.classList.add('d-none');
        return;
      }
      chips.classList.remove('d-none');
      for (var i = 0; i < tokens.length; i += 1) {
        var name = nameOf(tokens[i]);
        var chip = el('span', 'badge rounded-pill text-bg-light border text-dark d-inline-flex align-items-center');
        chip.setAttribute('data-tag-chip-row', 'true');
        chip.setAttribute('data-tag-chip', tokens[i]);
        chip.appendChild(el('span', null, name));
        var remove = el('button', 'btn-close ms-1 small');
        remove.type = 'button';
        remove.setAttribute('data-tag-chip-remove', 'true');
        remove.setAttribute('aria-label', 'Remove tag ' + name);
        chip.appendChild(remove);
        chips.appendChild(chip);
      }
    }

    function visibleSuggestions(typed) {
      var key = typed.toLowerCase();
      var hits = [];
      for (var i = 0; i < suggestions.length; i += 1) {
        var name = suggestions[i];
        if (key && name.toLowerCase().indexOf(key) === -1) continue;
        if (tokens.indexOf(name.toLowerCase()) !== -1) continue; // already selected
        if (indexOfLower(hits, name) !== -1) continue;
        hits.push(name);
      }
      hits.sort(function (left, right) {
        var a = left.toLowerCase();
        var b = right.toLowerCase();
        if (a < b) return -1;
        if (a > b) return 1;
        return 0;
      });
      return hits.slice(0, MAX_VISIBLE_OPTIONS);
    }

    function buildRow(match, index) {
      var row = el('li', 'list-group-item list-group-item-action d-block small py-1 px-2 text-truncate');
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', 'false');
      row.id = optionIdPrefix + index;
      if (match.kind === 'create') {
        row.appendChild(el('span', 'text-primary fw-semibold', 'Create new tag: '));
        row.appendChild(el('span', null, match.name));
      } else {
        row.appendChild(el('span', null, match.name));
      }
      return row;
    }

    function buildList() {
      while (list.firstChild) list.removeChild(list.firstChild);
      rows = [];
      rowEls = [];
      highlighted = -1;

      var typed = query.trim();
      if (typed) {
        // An explicit "create" row shows whenever nothing matches exactly, so a
        // brand-new tag stays a deliberate act instead of an accident.
        var exact = indexOfLower(suggestions, typed) !== -1 || tokens.indexOf(typed.toLowerCase()) !== -1;
        if (!exact) rows.push({ kind: 'create', name: typed });
      }
      var names = visibleSuggestions(typed);
      for (var i = 0; i < names.length; i += 1) rows.push({ kind: 'suggestion', name: names[i] });

      if (!rows.length) {
        if (typed) {
          var empty = el('li', 'list-group-item text-muted small');
          empty.setAttribute('role', 'presentation');
          empty.appendChild(document.createTextNode('No existing tag matches '));
          empty.appendChild(el('strong', null, typed));
          list.appendChild(empty);
        }
        return false;
      }

      for (var r = 0; r < rows.length; r += 1) {
        var node = buildRow(rows[r], r);
        list.appendChild(node);
        rowEls.push(node);
      }
      return true;
    }

    function openList() {
      if (!rowEls.length) return;
      list.classList.remove('d-none');
      input.setAttribute('aria-expanded', 'true');
    }

    function closeList() {
      list.classList.add('d-none');
      input.setAttribute('aria-expanded', 'false');
      highlight(-1);
    }

    function highlight(index) {
      if (highlighted >= 0 && highlighted < rowEls.length) {
        rowEls[highlighted].classList.remove('active');
        rowEls[highlighted].setAttribute('aria-selected', 'false');
      }
      highlighted = index;
      if (index >= 0 && index < rowEls.length) {
        var row = rowEls[index];
        row.classList.add('active');
        row.setAttribute('aria-selected', 'true');
        input.setAttribute('aria-activedescendant', row.id);
        if (row.scrollIntoView) row.scrollIntoView(false);
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    }

    function move(delta) {
      if (!rowEls.length) return;
      var next = highlighted < 0 ? (delta > 0 ? 0 : rowEls.length - 1) : highlighted + delta;
      if (next < 0) next = 0;
      if (next > rowEls.length - 1) next = rowEls.length - 1;
      highlight(next);
    }

    // The single mutation point: every add, remove and keystroke funnels through
    // here, so the chips, the value and the list can never disagree. The value is
    // only rewritten when it actually differs, which leaves the caret and the
    // admin's own typing untouched while they type.
    function render(showList) {
      var composed = compose();
      if (input.value !== composed.value) {
        input.value = composed.value;
        try {
          input.setSelectionRange(composed.caret, composed.caret);
        } catch (error) {
          // Nothing selectable: the value is still correct.
        }
      }
      renderChips();
      var hasRows = buildList();
      if (hasRows && showList && !dismissed) openList(); else closeList();
    }

    /* ---------- mutations ---------- */

    function addTag(candidate) {
      var name = String(candidate === null || candidate === undefined ? '' : candidate)
        .replace(/,/g, ' ').trim();
      if (!name) {
        query = '';
        render(true);
        return false;
      }
      var key = name.toLowerCase();
      if (tokens.indexOf(key) !== -1) {
        // Already selected: clear the search text instead of duplicating it.
        query = '';
        render(true);
        return false;
      }
      if (!Object.prototype.hasOwnProperty.call(spellings, key)) {
        spellings[key] = preferredSpelling(name);
      }
      tokens = tokens.slice(0, queryIndex).concat([key], tokens.slice(queryIndex));
      queryIndex += 1;
      query = '';
      render(true);
      return true;
    }

    function removeTag(key) {
      var index = tokens.indexOf(key);
      if (index === -1) return;
      tokens = withoutKey(tokens, key);
      if (index < queryIndex) queryIndex -= 1;
      if (queryIndex > tokens.length) queryIndex = tokens.length;
      render(true);
    }

    /* ---------- events ---------- */

    function onInput() {
      var read = readValue();
      rememberSpelling(read.beforeRaw);
      rememberSpelling(read.afterRaw);
      // tokens must stay unique per case-folded key or the chips would double up.
      tokens = read.before.concat(withoutKeys(read.after, read.before));
      queryIndex = read.before.length;
      query = read.active;
      dismissed = false;
      // Nothing is being typed: fold case-insensitive duplicates the way the
      // server does, so the value sits in canonical form at rest.
      if (!query.trim() && tokens.length > 1) tokens = toKeys(parseNames(input.value));
      render(true);
    }

    function onKeyDown(event) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      var key = event.key;

      if (key === 'ArrowDown' || key === 'ArrowUp') {
        event.preventDefault();
        var downward = key === 'ArrowDown';
        if (list.classList.contains('d-none')) {
          dismissed = false;
          if (buildList()) {
            openList();
            highlight(downward ? 0 : rowEls.length - 1);
          }
        } else {
          move(downward ? 1 : -1);
        }
        return;
      }
      if (key === 'Enter') {
        if (highlighted >= 0 && rows[highlighted]) {
          event.preventDefault(); // pick the tag instead of submitting the form
          addTag(rows[highlighted].name);
          return;
        }
        if (query.trim()) {
          event.preventDefault(); // commit the typed name instead of submitting
          addTag(query);
        }
        return;
      }
      if (key === 'Escape') {
        if (!list.classList.contains('d-none')) {
          dismissed = true;
          closeList();
        }
        return;
      }
      if (key === 'Backspace' && !query.trim() && tokens.length) {
        var caret = caretOf(input);
        if (caret.start !== caret.end) return; // a real selection: let it delete
        var target = queryIndex > 0 ? tokens[queryIndex - 1] : tokens[tokens.length - 1];
        event.preventDefault();
        removeTag(target);
        input.focus();
      }
    }

    function onListMouseDown(event) {
      var target = event.target;
      var row = target && target.closest ? target.closest('[role="option"]') : null;
      if (!row || !list.contains(row)) return;
      // Keep focus in the input: a blur would close the list first and drop the
      // caret, so the pick is handled here rather than on click.
      event.preventDefault();
      var index = rowEls.indexOf(row);
      if (index !== -1) addTag(rows[index].name);
    }

    function onChipsClick(event) {
      var target = event.target;
      var remove = target && target.closest
        ? target.closest('[data-tag-chip-remove="true"]')
        : null;
      if (!remove) return;
      var chip = remove.closest('[data-tag-chip-row="true"]');
      if (!chip) return;
      removeTag(chip.getAttribute('data-tag-chip'));
      input.focus();
    }

    function onFocus() {
      dismissed = false;
      if (buildList()) openList(); else closeList();
    }

    function onBlur() {
      closeList();
    }

    function onFormSubmit() {
      // Whatever the caret was doing, the server gets the canonical ", " list,
      // and a half-typed trailing token is kept instead of silently dropped.
      var pending = query.trim();
      if (pending) {
        var key = pending.toLowerCase();
        if (!Object.prototype.hasOwnProperty.call(spellings, key)) {
          spellings[key] = preferredSpelling(pending);
        }
        if (tokens.indexOf(key) === -1) tokens.push(key);
      }
      query = '';
      queryIndex = tokens.length;
      input.value = joinNames(tokens);
      renderChips();
      closeList();
    }

    // The no-JS controls stay wired up, so anything still driving them lands in
    // the same comma-separated value.
    function onFallbackPick() {
      var picked = (menu.value || '').trim();
      if (!picked) return;
      dismissed = false;
      addTag(picked);
      menu.value = '';
      input.focus();
    }

    function joinNames(keys) {
      return namesOf(keys).join(', ');
    }

    /* ---------- first paint ---------- */

    var initial = parseNames(input.value);
    tokens = toKeys(initial);
    for (var i = 0; i < initial.length; i += 1) spellings[initial[i].toLowerCase()] = initial[i];
    queryIndex = tokens.length;
    query = '';

    input.addEventListener('input', onInput);
    input.addEventListener('keydown', onKeyDown);
    input.addEventListener('focus', onFocus);
    input.addEventListener('blur', onBlur);
    list.addEventListener('mousedown', onListMouseDown);
    chips.addEventListener('click', onChipsClick);
    menu.addEventListener('change', onFallbackPick);
    button.addEventListener('click', onFallbackPick);
    if (input.form) input.form.addEventListener('submit', onFormSubmit);

    render(false); // painted shut: nothing opens until the field takes focus

    // Hidden last, and only from here on: with JavaScript off this file never
    // runs, and if anything above threw the fallback row stays as it was.
    group.classList.add('d-none');
    input.setAttribute('data-tag-field-ready', 'true');
  }

  /* ------------------------------------------------------------------ *
   * Bootstrapping
   * ------------------------------------------------------------------ */

  function initTagFields(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var fields = scope.querySelectorAll('[data-tag-input="true"]:not([data-tag-field-ready])');
    var published = readGlobalSuggestions();
    for (var i = 0; i < fields.length; i += 1) {
      var names = published && published.length
        ? published
        : readMenuOptions(findMenuFor(fields[i]));
      try {
        enhanceField(fields[i], names);
      } catch (error) {
        // Leave that field on its no-JS dropdown rather than half-enhancing it.
        if (global.console && global.console.warn) {
          global.console.warn('tag-field: skipped enhancing a field', error);
        }
      }
    }
  }

  function findMenuFor(input) {
    var menu = input.nextElementSibling
      ? findIn(input.nextElementSibling, '[data-tag-menu="true"]')
      : null;
    return menu || findIn(input.parentNode, '[data-tag-menu="true"]');
  }

  // Exposed so anything that injects a form after page load can wire it up.
  global.initTagFields = initTagFields;

  function boot() {
    initTagFields(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}(window));

/* Read-only API discovery. Requests can only run through Lacry's human review. */
(function () {
  'use strict';
  var panel = document.getElementById('hamilton-api-catalog');
  if (!panel) { return; }
  var search = document.getElementById('hamilton-api-search');
  var count = document.getElementById('hamilton-api-count');
  var list = document.getElementById('hamilton-api-results');
  var next = document.getElementById('hamilton-api-next');
  var offset = 0, generation = 0;
  function read(query) {
    return fetch('/researcher/api/lacry/hamilton/api-catalog?' + query)
      .then(function (response) { if (!response.ok) { throw new Error('API catalog unavailable.'); } return response.json(); });
  }
  function load(append) {
    var token = ++generation;
    if (!append) { offset = 0; list.replaceChildren(); }
    next.hidden = true;
    read('q=' + encodeURIComponent(search.value) + '&offset=' + offset).then(function (page) {
      if (token !== generation) { return; }
      count.textContent = page.matched + ' matching operations of ' + page.total_operations + ' documented.';
      page.operations.forEach(function (operation) {
        var item = document.createElement('li'), detail = document.createElement('details');
        var title = document.createElement('summary');
        title.textContent = operation.summary + ' — ' + operation.operation;
        var access = document.createElement('p'); access.textContent = 'Access: ' + operation.access.replaceAll('_', ' ');
        detail.appendChild(title); detail.appendChild(access);
        detail.addEventListener('toggle', function () {
          if (!detail.open || detail.dataset.loaded) { return; }
          detail.dataset.loaded = 'true';
          read('operation=' + encodeURIComponent(operation.operation)).then(function (data) {
            var code = document.createElement('pre'); code.style.whiteSpace = 'pre-wrap';
            code.textContent = JSON.stringify(data, null, 2); detail.appendChild(code);
          }).catch(function (error) { access.textContent = error.message; delete detail.dataset.loaded; });
        });
        item.appendChild(detail); list.appendChild(item);
      });
      offset = page.next_offset; next.hidden = offset === null;
    }).catch(function (error) { count.textContent = error.message; });
  }
  document.getElementById('hamilton-api-find').onclick = function () { load(false); };
  search.addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); load(false); } });
  next.onclick = function () { load(true); };
  panel.addEventListener('toggle', function () { if (panel.open && !list.children.length) { load(false); } });
}());

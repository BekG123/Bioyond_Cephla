/* Files stay local until Send includes their IDs in a chat message. */
(function () {
  'use strict';
  var pending = [], uploading = false;
  var input = document.getElementById('document-input');
  var attach = document.getElementById('document-attach');
  var list = document.getElementById('document-list');
  var status = document.getElementById('document-status');
  function render() {
    list.replaceChildren();
    pending.forEach(function (doc) {
      var chip = document.createElement('div'), label = document.createElement('span'), remove = document.createElement('button');
      chip.className = 'document-chip'; label.textContent = doc.name;
      chip.title = doc.notice; remove.type = 'button'; remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove ' + doc.name + ' from message');
      remove.disabled = uploading;
      remove.onclick = function () { pending = pending.filter(function (d) { return d.id !== doc.id; }); render(); };
      chip.appendChild(label); chip.appendChild(remove); list.appendChild(chip);
    });
    list.hidden = !pending.length; attach.disabled = uploading;
  }
  attach.onclick = function () { input.click(); };
  input.onchange = async function () {
    var files = Array.from(input.files); input.value = '';
    if (!files.length) { return; }
    if (pending.length + files.length > 5) { status.textContent = 'Attach up to five files per message.'; return; }
    uploading = true; render();
    try {
      for (var file of files) {
        if (file.size > 10 * 1024 * 1024) { throw new Error(file.name + ': limit is 10 MB per file.'); }
        status.textContent = 'Reading ' + file.name + '…';
        var form = new FormData(); form.append('file', file);
        var response = await fetch('/researcher/api/lacry/documents', {method: 'POST', body: form});
        var result = await response.json().catch(function () { return {message: 'Upload failed. Check the file size and format.'}; });
        if (!response.ok || !result.ok) { throw new Error(result.message || result.error || 'Upload failed.'); }
        pending.push(result.document);
      }
      status.textContent = 'Ready to send. ' + pending[pending.length - 1].notice;
    } catch (error) { status.textContent = error.message; }
    finally { uploading = false; render(); }
  };
  window.LacryAttachments = {
    busy: function () { return uploading; },
    ids: function () { return pending.map(function (d) { return d.id; }); },
    sent: function (ids) { pending = pending.filter(function (d) { return ids.indexOf(d.id) < 0; }); status.textContent = ''; render(); }
  };
}());

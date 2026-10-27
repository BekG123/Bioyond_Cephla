(function () {
  'use strict';
  var host=document.getElementById('lacry-memory');
  if (!host) { return; }
  var el=function(id){return document.getElementById(id);}, editing=null;
  var base='/developer/api/lacry-memory';
  function request(path,body) {
    return fetch(base+path,body ? {method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'developer'},body:JSON.stringify(body)} : {})
      .then(function(r){return r.json().then(function(data){if(!r.ok || !data.ok){throw new Error(data.message || 'Memory request failed.');}return data;});});
  }
  function failed(error){el('memory-status').textContent=error.message;}
  function button(label,handler){var b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',handler);return b;}
  function review(row,status){request('/'+row.id,{revision:row.revision,status:status}).then(load).catch(failed);}
  function clear(){editing=null;el('memory-form').reset();el('memory-save').textContent='Save approved note';}
  function load(){return request('?q='+encodeURIComponent(el('memory-search').value)).then(function(data){
    var c=data.counts;
    el('memory-status').textContent=(c.approved||0)+' approved · '+(c.observed||0)+' observations · '+(c.pending||0)+' awaiting review · '+(c.archived||0)+' archived'+(data.error?' · Recording issue: '+data.error:'');
    var list=el('memory-items');list.textContent='';
    data.items.forEach(function(row){
      var item=document.createElement('details');item.style.cssText='border-top:1px solid #b8c4ce55;padding:10px 0';
      var heading=document.createElement('summary');heading.textContent=row.title+' — '+row.status;item.appendChild(heading);
      var note=document.createElement('p');note.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';note.textContent=row.body;item.appendChild(note);
      var source=document.createElement('p');source.className='lbl';source.textContent=row.source+' · '+row.kind+' · revision '+row.revision;item.appendChild(source);
      var controls=document.createElement('div');controls.className='row';
      controls.appendChild(button('Edit',function(){editing=row;el('memory-title').value=row.title;el('memory-body').value=row.body;el('memory-form').closest('details').open=true;el('memory-save').textContent='Save approved revision';el('memory-title').focus();}));
      if(row.status==='pending'||row.status==='observed'){controls.appendChild(button('Approve note',function(){review(row,'approved');}));}
      if(row.status!=='archived'){controls.appendChild(button('Archive',function(){review(row,'archived');}));}
      item.appendChild(controls);list.appendChild(item);
    });
    if(!data.items.length){list.textContent='No matching memories.';}
  }).catch(failed);}
  el('memory-refresh').addEventListener('click',load);
  el('memory-search').addEventListener('keydown',function(event){if(event.key==='Enter'){event.preventDefault();load();}});
  el('memory-new').addEventListener('click',clear);
  el('memory-form').addEventListener('submit',function(event){event.preventDefault();
    var body={title:el('memory-title').value,body:el('memory-body').value};
    if(editing){body.revision=editing.revision;body.status='approved';}
    el('memory-save').disabled=true;
    request(editing?'/'+editing.id:'',body).then(function(){clear();return load();}).catch(failed)
      .finally(function(){el('memory-save').disabled=false;});
  });
  load();
}());

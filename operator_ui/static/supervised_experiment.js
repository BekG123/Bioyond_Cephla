/* Approved workflow review and execution status. */
(function () {
  'use strict';
  window.renderSupervisedExperiment = function (state) {
    var card = document.getElementById('supervised-experiment');
    if (!card) {
      card = document.createElement('section');
      card.id = 'supervised-experiment'; card.className = 'supervised-experiment';
      document.getElementById('chat-log').before(card);
    }
    var plan = state.pending, run = state.supervised_experiment || {};
    var authoringReview = plan && plan.protocol_review && (plan.protocol_review.kind === 'dilution_authoring' ? plan.protocol_review : plan.protocol_review.hamilton);
    var authoring = authoringReview && authoringReview.kind === 'dilution_authoring';
    var nativeApi = plan && plan.protocol_review && plan.protocol_review.kind === 'hamilton_api';
    var composition = plan && (plan.steps || []).some(function (step) { return step.kind === 'workflow'; });
    card.hidden = !(plan && plan.timeline) && !authoring && !nativeApi && !composition && !run.run_folder;
    if (card.hidden) { return; }
    card.replaceChildren();
    var heading = document.createElement('strong');
    heading.textContent = composition ? (plan.executable === false ? 'Workflow needs preparation' : 'Complete workflow to review') : authoring ? 'Hamilton dilution to review' : plan && plan.timeline ? 'Experiment to review' : 'Experiment · ' + (run.status || 'ready');
    card.appendChild(heading);
    if (nativeApi) {
      heading.textContent = 'Hamilton API request to review';
      var request = document.createElement('pre');
      request.textContent = JSON.stringify(plan.protocol_review, null, 2);
      card.appendChild(request);
    }
    if (composition) {
      var chain = document.createElement('ol');
      (plan.steps || []).forEach(function (step) {
        var item = document.createElement('li'); item.textContent = step.label; chain.appendChild(item);
      });
      card.appendChild(chain);
      (plan.blockers || []).forEach(function (reason) {
        var blocked = document.createElement('p'); blocked.textContent = reason; card.appendChild(blocked);
      });
      if (plan.protocol_review) {
        var selections = document.createElement('details'), selectionsTitle = document.createElement('summary'), selectionsText = document.createElement('pre');
        selectionsTitle.textContent = 'Protocol, inventory and imaging settings';
        selectionsText.textContent = JSON.stringify(plan.protocol_review, null, 2);
        selections.appendChild(selectionsTitle); selections.appendChild(selectionsText); card.appendChild(selections);
      }
    }
    if (authoring) {
      var info = authoringReview;
      if (!composition) { heading.textContent = 'Hamilton liquid transfers to review'; }
      var intro = document.createElement('p');
      intro.textContent = plan.summary + (info.physical_execution_authorized ? '. Your approval covers native simulation and automatic live pipetting if that exact simulation passes.' : '. No physical pipetting is authorized by this step.');
      card.appendChild(intro);
      var table = document.createElement('table');
      var header = document.createElement('tr');
      var addition = info.transfer_kind === 'addition';
      (addition ? ['Source', 'Destination', 'Initial µL', 'Added µL', 'Final µL', 'Mix after'] : ['Stock source', 'Diluent source', 'Destination', 'Dilution', 'Stock µL', 'Diluent µL', 'Final µL']).forEach(function (name) {
        var cell = document.createElement('th'); cell.textContent = name; header.appendChild(cell);
      });
      var head = document.createElement('thead'); head.appendChild(header); table.appendChild(head);
      var body = document.createElement('tbody');
      function well(a) { return 'Site ' + a.site + ' / ' + a.well; }
      (info.dilution_table || []).forEach(function (r) {
        var row = document.createElement('tr');
        (addition ? [well(r.source), well(r.destination), r.initial_volume_ul, r.added_volume_ul, r.final_volume_ul, r.mix_after ? 'Yes' : 'No'] : [well(r.source), well(r.diluent), well(r.destination), '1:' + r.dilution_factor, r.sample_ul, r.diluent_ul, r.final_volume_ul]).forEach(function (v) {
          var cell = document.createElement('td'); cell.textContent = v; row.appendChild(cell);
        });
        body.appendChild(row);
      });
      table.appendChild(body);
      var scroll = document.createElement('div'); scroll.style.overflowX = 'auto'; scroll.appendChild(table); card.appendChild(scroll);
      var details = document.createElement('details'), title = document.createElement('summary'), json = document.createElement('pre');
      title.textContent = 'Exact settings, inventory and simulation evidence'; json.textContent = JSON.stringify(info, null, 2);
      details.appendChild(title); details.appendChild(json); card.appendChild(details);
    }
    if (plan && plan.timeline) {
      var rows = plan.timeline.rows, total = plan.timeline.p95_total_s;
      var list = document.createElement('ol'); list.className = 'experiment-timeline';
      rows.forEach(function (row) {
        var item = document.createElement('li'), label = document.createElement('span');
        label.textContent = row.label + (row.estimate ? ' · about ' + Math.ceil(row.estimate.p95_s) + ' s' : ' · timing not measured yet');
        item.appendChild(label);
        if (total && row.estimate) {
          var track = document.createElement('div'), bar = document.createElement('div');
          track.className = 'experiment-track'; bar.className = 'experiment-bar';
          bar.style.marginLeft = (100 * row.start_s / total) + '%';
          bar.style.width = Math.max(1, 100 * row.estimate.p95_s / total) + '%';
          track.appendChild(bar); item.appendChild(track);
        }
        list.appendChild(item);
      });
      card.appendChild(list);
      var review = document.createElement('details'), summary = document.createElement('summary'), text = document.createElement('pre');
      summary.textContent = 'Reviewed protocol and imaging selections';
      text.textContent = JSON.stringify(plan.protocol_review, null, 2);
      review.appendChild(summary); review.appendChild(text); card.appendChild(review);
    }
    if (run.active) {
      var execution = document.createElement('p');
      execution.textContent = 'Running the approved workflow autonomously. Stop remains available.';
      card.appendChild(execution);
    }
    if (run.error) { var error = document.createElement('p'); error.textContent = run.error + ' Nothing was retried.'; card.appendChild(error); }
  };
}());

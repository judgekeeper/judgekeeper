/* judgekeeper: the free check in your browser (check.html).
 *
 * judgekeeper's step 1 for promptfoo and DeepEval results and your own CSV, TSV or JSONL
 * file, as the tool does it (readers/promptfoo.py, readers/deepeval.py, table.py,
 * start.read_results_table, start.build_pool, normalise.py, judge_check.py and the wording in
 * front.py); tests/test_freecheck_parity.py compares the two. The file is read on this
 * computer with the File API; nothing is sent anywhere, and the page's Content-Security-Policy
 * blocks every connection.
 *
 * `JKFreeCheck.check(text, fileName)` is pure: text in, plain data out. The page code at the
 * bottom only runs in a browser. Where the tool would ask a question, the page can't: a grade
 * it can't read as Pass or Fail is left out and said.
 */
(function (root) {
  'use strict';

  var MAX_BYTES = 50 * 1024 * 1024;
  var MAX_NESTING = 500;
  var RULE_SHOWN = 58;
  var ROUGH = 15, MIN_POOL = 30;

  // Assertion types graded by a model, and judges that are not one model call
  var MODEL_GRADED = ['llm-rubric', 'g-eval', 'factuality', 'model-graded-closedqa', 'model-graded-factuality',
    'answer-relevance', 'context-faithfulness', 'context-recall', 'context-relevance',
    'conversation-relevance', 'search-rubric'];
  var AGENT_GRADED = ['agent-rubric', 'trajectory:goal-success'];

  var UNREADABLE_REASONS = ['Could not extract JSON from ', 'Error parsing output:'];
  var ERROR_REASONS = ['Could not perform remote grading:', 'API error:'];
  var NO_OUTPUT = 'No output';
  var MALFORMED = /^(\S+ |Model grader )?produced (a )?malformed response/;

  var STRIP = {
    output: ['answers', 'PROMPTFOO_STRIP_RESPONSE_OUTPUT'],
    vars: ['inputs', 'PROMPTFOO_STRIP_TEST_VARS'],
    grading: ["judge's decisions", 'PROMPTFOO_STRIP_GRADING_RESULT']
  };

  var NOT_RECOGNISED = "This doesn't look like results judgekeeper can read in the browser. The tool also reads Inspect AI and MLflow: run uvx judgekeeper in your project.";
  var IN_PROJECT = ' This page does not read it: run uvx judgekeeper in your project for this file.';
  var RECORDS = 'This is a judgekeeper.record() file.' + IN_PROJECT;
  var SETTINGS = "This is judgekeeper's settings file (judgekeeper.toml)." + IN_PROJECT;
  var TABLE_OUTPUT = "This is promptfoo's table output, which doesn't keep the judge's own decisions. Save the full results with promptfoo eval -o results.json.";
  // start._no_judge: a file with no LLM judge's decisions
  var NO_JUDGE = ' holds no decisions from an LLM judge.';
  var RULES = { promptfoo: 'checks', deepeval: 'metrics' };
  var RULES_IN_CODE = ' are rules in code, not an LLM judge. judgekeeper checks LLM judges.';
  var TOO_BIG = 'This file is bigger than 50 MB, so this page does not read it. Run uvx judgekeeper in your project instead: it reads big files too.';
  var NOT_UTF8 = 'This file is not saved as UTF-8 text, so it cannot be read.';
  var NOT_JSON = "This file isn't valid JSON that judgekeeper can read.";
  var EVERY_ANSWER = 'your judge gave every answer a clear Pass or Fail.';
  var FREE_CHECK = 'Checked: ';
  var MODEL_NOT_WRITTEN = "Your judge's model isn't written in your config. promptfoo picks it from whichever API key is set, so it can change without any file changing. Write it in your config (defaultTest.options.provider).";
  var NO_CLEAR = 'No answer has a clear Pass or Fail from your judge, so there is nothing to mark.';
  var ALL_FAILED = "Your judge's calls failed on every answer, so there is nothing to mark.";
  var LIMIT = 'This shows whether your judge is really judging, not whether it agrees with you. To see that, run uvx judgekeeper in your project and mark some answers.';
  var PRIVACY = 'Your file never leaves this page: it is read on your computer. Turn off Wi-Fi and it still works.';

  /* ---------- small helpers, each the Python behaviour it stands for ---------- */

  function isObj(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
  function isStr(v) { return typeof v === 'string'; }
  // Python truthiness: None, False, 0, "", [] and {} are false
  function truthy(v) {
    if (v === null || v === undefined || v === false || v === 0 || v === '') return false;
    if (Array.isArray(v)) return v.length > 0;
    if (isObj(v)) return Object.keys(v).length > 0;
    return true;
  }
  function or() { for (var i = 0; i < arguments.length; i++) if (truthy(arguments[i])) return arguments[i]; return arguments[arguments.length - 1]; }
  function get(o, k) { return isObj(o) ? o[k] : undefined; }
  function n(count, one, many) { return count + ' ' + (count === 1 ? one : (many || one + 's')); }
  function startsWithAny(s, list) { return list.some(function (p) { return s.indexOf(p) === 0; }); }

  // json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  function canonical(v) {
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    if (isObj(v)) {
      return '{' + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ':' + canonical(v[k]); }).join(',') + '}';
    }
    return v === undefined ? 'null' : JSON.stringify(v);
  }
  function text(v) { return v === null || v === undefined ? null : (isStr(v) ? v : canonical(v)); }

  // JSON.parse, noting each whole number written as a decimal (1.0): Python reads it as a
  // float, which is no Pass or Fail (str(1.0) is "1.0"), where 1 is Pass. A browser that
  // can't say how a number was written leaves every number grade out (FLOATS_SEEN false).
  var FLOATS = new WeakMap();
  var FLOATS_SEEN = (function () {
    var seen = false;
    try { JSON.parse('1', function (k, v, ctx) { seen = !!(ctx && isStr(ctx.source)); return v; }); } catch (e) { seen = false; }
    return seen;
  })();
  function parseJSON(t) {
    return JSON.parse(t, function (k, v, ctx) {
      if (typeof v === 'number' && Number.isInteger(v) && ctx && isStr(ctx.source) && /[.eE]/.test(ctx.source)) {
        if (!FLOATS.has(this)) FLOATS.set(this, {});
        FLOATS.get(this)[k] = true;
      }
      return v;
    });
  }
  // How `obj[key]` was written: 'float', 'int', or null when this browser can't tell
  function numberKind(obj, key) {
    if (!FLOATS_SEEN) return null;
    var f = isObj(obj) ? FLOATS.get(obj) : null;
    return f && f[key] ? 'float' : 'int';
  }

  function tooDeep(data) {
    var stack = [[data, 1]];
    while (stack.length) {
      var top = stack.pop(), v = top[0], d = top[1];
      if (v === null || typeof v !== 'object') continue;
      if (d > MAX_NESTING) return true;
      var kids = Array.isArray(v) ? v : Object.keys(v).map(function (k) { return v[k]; });
      for (var i = 0; i < kids.length; i++) if (kids[i] !== null && typeof kids[i] === 'object') stack.push([kids[i], d + 1]);
    }
    return false;
  }

  // Shown names: no bidi controls, no zero-width characters, no control characters
  function clean(s, max) {
    s = String(s === null || s === undefined ? '' : s)
      .replace(/[‪-‮⁦-⁩‎‏؜​-‍⁠﻿­]/g, '')
      .replace(/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g, '');
    if (max && s.length > max) s = s.slice(0, max - 1) + '…';
    return s;
  }
  function oneLine(s) { return clean(s).split(/\s+/).filter(Boolean).join(' '); }

  /* ---------- readers/promptfoo.py ---------- */

  function judgeType(kind) {
    if (!isStr(kind)) return null;
    var base = kind.indexOf('not-') === 0 ? kind.slice(4) : kind;
    return MODEL_GRADED.indexOf(base) >= 0 || AGENT_GRADED.indexOf(base) >= 0 ? base : null;
  }

  function graderProblem(c, metadata) {
    var reason = isStr(c.reason) ? c.reason : '';
    var flagged = metadata.graderError === true;
    if (startsWithAny(reason, UNREADABLE_REASONS) || (flagged && MALFORMED.test(reason))) return 'unreadable';
    if (flagged || startsWithAny(reason, ERROR_REASONS) || reason === NO_OUTPUT) return 'error';
    return null;
  }

  function isSet(c) {
    var marker = isObj(c.metadata) ? c.metadata.assertionSet : undefined;
    return get(or(c.assertion, {}), 'type') === 'assert-set' || (isObj(marker) && marker.type === 'assert-set');
  }

  function components(grading) {
    var out = [];
    var comps = (or(get(or(grading, {}), 'componentResults'), []) || []);
    comps = Array.isArray(comps) ? comps.filter(isObj) : [];
    var i = 0;
    while (i < comps.length) {
      var c = comps[i]; i += 1;
      var nested = Array.isArray(c.componentResults) ? c.componentResults.filter(isObj) : [];
      if (!(nested.length && isSet(c))) { out.push(c); continue; }
      out = out.concat(components(c));
      var again = comps.slice(i, i + nested.length);
      if (again.map(canonical).join('\n') === nested.map(canonical).join('\n') && again.length === nested.length) i += nested.length;
    }
    return out;
  }

  function options(obj) { var o = get(obj, 'options'); return isObj(o) ? o : {}; }

  function isSetGrader(v) { return isObj(v) && !('id' in v) && isStr(v.modelName) && v.modelName.length > 0; }

  // The model a grader names: its id, or a --grader's modelName; null when the file has none
  function modelOf(value) {
    if (isObj(value) && !('id' in value) && (isObj(value.text) || isStr(value.text))) value = value.text;
    var id = null;
    if (isStr(value)) id = value;
    else if (isObj(value) && isStr(value.id)) id = value.id;
    else if (isSetGrader(value)) return value.modelName;
    if (id !== null && id.indexOf('file://') === 0) {  // the person's own provider: never its path
      return 'your own provider (' + id.slice(7).split(/[\\/]/).pop().split(':')[0] + ')';
    }
    return id;
  }

  function stripped(rows) {
    var lacks = {
      output: function (r) { var o = get(or(r.response, {}), 'output'); return o === null || o === undefined; },
      vars: function (r) { var tv = get(or(r.testCase, {}), 'vars'); return (r.vars === null || r.vars === undefined) && (tv === null || tv === undefined); },
      grading: function (r) { return !truthy(r.gradingResult); }
    };
    return ['output', 'vars', 'grading'].filter(function (part) {
      return rows.length && rows.filter(lacks[part]).length * 2 > rows.length;
    });
  }
  function strippedMessage(part) {
    return 'The ' + STRIP[part][0] + ' are missing from this file. promptfoo leaves them out when ' + STRIP[part][1] +
      " is on, in your environment or in the config's env: block. Turn it off and write the file again.";
  }

  // Every judge record in the file, as the reader makes them (the code checks are skipped)
  function readPromptfoo(data) {
    var summary = data.results;
    var rows = summary.results.filter(isObj);
    var defaultTest = get(or(data.config, {}), 'defaultTest');
    defaultTest = isObj(defaultTest) ? defaultTest : {};
    var gone = stripped(rows);
    if (gone.length) return { error: 'stripped', message: strippedMessage(gone.indexOf('grading') >= 0 ? 'grading' : gone[0]) };
    var judged = [], nHuman = 0, nCode = 0;
    for (var ri = 0; ri < rows.length; ri++) {
      var r = rows[ri];
      var testOpts = options(r.testCase);
      var output = text(get(or(r.response, {}), 'output'));
      var input = r.vars === undefined ? null : r.vars;
      var perRow = {};
      var comps = components(r.gradingResult);
      for (var ci = 0; ci < comps.length; ci++) {
        var c = comps[ci];
        var a = isObj(c.assertion) ? c.assertion : {};
        var kind = a.type;
        var label = typeof c.pass === 'boolean' ? (c.pass ? 'pass' : 'fail') : null;
        if (kind === 'human') { nHuman += 1; continue; }
        if (judgeType(kind) === null) { nCode += 1; continue; }
        var name = String(or(a.metric, kind, 'unknown'));
        perRow[name] = (perRow[name] || 0) + 1;
        if (perRow[name] > 1) {
          var idx = r.testIdx;
          var test = typeof idx === 'number' && Math.floor(idx) === idx ? idx + 1 : idx;
          return { error: 'two-judges', message: 'Test ' + clean(test, 20) + ' has more than one ' + JSON.stringify(clean(name, 80)) +
            ' judge. Give each one a name with metric: in its assertion, then run your eval again (that makes model calls).' };
        }
        var grader = or(a.provider, testOpts.provider, options(defaultTest).provider, defaultTest.provider, null);
        if (!truthy(grader)) grader = null;
        var model = grader === null ? null : modelOf(grader);
        var metadata = isObj(c.metadata) ? c.metadata : {};
        var rubricPrompt = or(a.rubricPrompt, testOpts.rubricPrompt, options(defaultTest).rubricPrompt);
        var prompt = text(a.value);
        if (truthy(rubricPrompt)) prompt = (prompt || '') + '\n\n' + text(rubricPrompt);
        var problem = graderProblem(c, metadata);
        judged.push({
          name: name, input: input, output: output, label: label,
          score: c.score === undefined ? null : c.score, scoreKind: numberKind(c, 'score'),
          reason: isStr(c.reason) ? c.reason : (truthy(c.reason) ? text(c.reason) : ''),
          model: model, prompt: prompt, problem: problem,
          countedAs: problem ? label : null
        });
      }
    }
    return { judged: judged, nHuman: nHuman, rulesInCode: nCode > 0 };
  }

  /* ---------- readers/deepeval.py ---------- */

  var DE_SEPARATOR = ' \n \n';
  var DE_PROMPT_PARTS = ['Criteria:', 'Evaluation Steps:', 'Rubric:'];
  var NO_VERDICTS = 'Verdicts:\n[]';
  var EMPTY_REFUSED = "'actual_output' cannot be empty";
  var LINK_ONLY = "This file only links to Confident AI; your results aren't saved on this computer.";

  function isLinkOnly(data) {
    return isObj(data) && 'testRunLink' in data && !['testCases', 'conversationalTestCases', 'testRunData'].some(function (k) { return k in data; });
  }
  function deepevalData(data) {
    if (isObj(data) && isObj(data.testRunData)) data = data.testRunData;
    return isObj(data) && ('testCases' in data || 'conversationalTestCases' in data) ? data : null;
  }
  function rubricFromLogs(logs) {
    if (!truthy(logs) || !isStr(logs)) return null;
    var parts = logs.split(DE_SEPARATOR).filter(function (p) { return startsWithAny(p, DE_PROMPT_PARTS); });
    return parts.join(DE_SEPARATOR) || null;
  }
  function checkedNothing(md) {
    var logs = md.verboseLogs;
    return md.score === 1 && isStr(logs) && logs.split(DE_SEPARATOR).some(function (p) { return p.trim() === NO_VERDICTS; });
  }
  function deFailed(md) { return truthy(md.error) || ((md.score === null || md.score === undefined) && md.success === false); }

  function readDeepeval(data) {
    var judged = [], thresholds = {}, strict = {};
    var cases = [];
    (truthy(data.testCases) && Array.isArray(data.testCases) ? data.testCases : []).forEach(function (c) { cases.push([c, false]); });
    (truthy(data.conversationalTestCases) && Array.isArray(data.conversationalTestCases) ? data.conversationalTestCases : []).forEach(function (c) { cases.push([c, true]); });
    cases.forEach(function (pair) {
      var c = pair[0], conversational = pair[1];
      if (!isObj(c)) return;
      var input, output;
      if (conversational) { input = truthy(c.scenario) ? c.scenario : canonical(truthy(c.turns) ? c.turns : []); output = ''; }
      else { input = c.input === undefined ? null : c.input; output = c.actualOutput === undefined ? null : c.actualOutput; }
      (Array.isArray(c.metricsData) ? c.metricsData : []).forEach(function (md) {
        if (!isObj(md)) return;
        var name = String(md.name);
        if (md.threshold !== null && md.threshold !== undefined) {
          thresholds[name] = thresholds[name] || [];
          if (!thresholds[name].some(function (t) { return t === md.threshold; })) thresholds[name].push(md.threshold);
        }
        if (md.strictMode === true) strict[name] = true;
        var label = typeof md.success === 'boolean' ? (md.success ? 'pass' : 'fail') : null;
        var problem = null;
        if (deFailed(md)) problem = String(md.error || '').indexOf(EMPTY_REFUSED) === 0 ? 'empty_answer_refused' : 'error';
        else if (checkedNothing(md)) problem = 'nothing_checked';
        judged.push({
          name: name, input: input, output: output, label: label,
          score: md.score === undefined ? null : md.score, scoreKind: numberKind(md, 'score'),
          reason: pyText(or(md.reason, md.error, null)),
          model: truthy(md.evaluationModel) ? String(md.evaluationModel) : null,
          prompt: rubricFromLogs(md.verboseLogs), problem: problem,
          countedAs: problem ? label : null, outputElsewhere: conversational
        });
      });
    });
    var perMetric = {};
    Object.keys(thresholds).forEach(function (k) {
      var ts = thresholds[k];
      perMetric[k] = { threshold: ts.length === 1 ? ts[0] : ts.slice().sort() };
    });
    Object.keys(strict).forEach(function (k) { perMetric[k] = perMetric[k] || {}; perMetric[k].strict = true; });
    // a metric with no model (Exact Match, a check written in Python) is a rule in code
    var withModel = {};
    judged.forEach(function (r) { if (r.model) withModel[r.name] = true; });
    return { tool: 'deepeval', judged: judged.filter(function (r) { return withModel[r.name]; }),
      nHuman: 0, perMetric: perMetric, scoreJudge: true, rulesInCode: judged.length > 0 };
  }

  /* ---------- your own table: table.py, start.read_results_table, find.is_table ---------- */

  var KNOWN_COLUMNS = ['id', 'run', 'input', 'output', 'output_a', 'output_b', 'verdict', 'judge_verdict',
    'judge', 'label', 'human_label', 'reason', 'notes', 'score', 'model', 'judge_model', 'app_version'];
  var VERDICT_COLUMNS = ['verdict', 'judge_verdict', 'judge'];
  var HUMAN_COLUMNS = ['human_label', 'label'];
  var PAIRWISE = 'These are A/B comparisons (output_a and output_b). judgekeeper handles answers with a Pass or Fail for now.';

  function columnName(name) {
    if (isStr(name)) { var plain = name.trim().toLowerCase(); if (KNOWN_COLUMNS.indexOf(plain) >= 0) return plain; }
    return name;
  }
  // table._known_names: judgekeeper's own column names written as it knows them
  function knownNames(row) {
    var keys = Object.keys(row);
    if (keys.every(function (k) { return columnName(k) === k; })) return row;
    var out = {};
    keys.forEach(function (k) {
      var nm = columnName(k), v = row[k];
      if (Object.prototype.hasOwnProperty.call(out, nm) && nm !== k) { if (!Object.prototype.hasOwnProperty.call(out, k)) out[k] = v; }
      else if (nm !== k && Object.prototype.hasOwnProperty.call(row, nm)) out[k] = v;
      else out[nm] = v;
    });
    return out;
  }
  function isTable(columns) {
    var has = function (c) { return columns.indexOf(c) >= 0; };
    return has('input') && (has('output') || (has('output_a') && has('output_b'))) && VERDICT_COLUMNS.some(has);
  }
  function isRecordsFile(columns) { return columns.indexOf('annotator_kind') >= 0 || columns.indexOf('schema_version') >= 0; }
  function blank(v) { return v === null || v === undefined || (isStr(v) && !v.trim()); }

  // table._delimiter: a header with no comma but semicolons or tabs uses those
  function delimiterOf(text, tsv) {
    if (tsv) return '\t';
    var header = text.split('\n', 1)[0];
    if (header.indexOf(',') < 0) { if (header.indexOf(';') >= 0) return ';'; if (header.indexOf('\t') >= 0) return '\t'; }
    return ',';
  }

  // Python's csv reader (excel dialect, not strict): quotes only at the start of a field
  function parseCsv(text, d) {
    var rows = [], row = [], field = '', state = 'record', i = 0, c;
    function save() { row.push(field); field = ''; }
    function end() { rows.push(row); row = []; state = 'record'; if (c === '\r' && text[i] === '\n') i++; }
    while (i < text.length) {
      c = text[i++];
      if (state === 'record') {
        if (c === '\n' || c === '\r') { end(); continue; }  // an empty line: []
        state = 'field';
      }
      if (state === 'field') {
        if (c === '"') state = 'quoted';
        else if (c === d) save();
        else if (c === '\n' || c === '\r') { save(); end(); }
        else { field += c; state = 'in'; }
      } else if (state === 'in') {
        if (c === d) { save(); state = 'field'; }
        else if (c === '\n' || c === '\r') { save(); end(); }
        else field += c;
      } else if (state === 'quoted') {
        if (c === '"') state = 'quote2'; else field += c;
      } else if (state === 'quote2') {
        if (c === '"') { field += c; state = 'quoted'; }
        else if (c === d) { save(); state = 'field'; }
        else if (c === '\n' || c === '\r') { save(); end(); }
        else { field += c; state = 'in'; }
      }
    }
    if (state !== 'record' && (field.length || state === 'quoted' || state === 'field' || state === 'in' || state === 'quote2')) { save(); rows.push(row); }
    return rows;
  }
  // csv.DictReader: the first row names the columns, empty lines are skipped
  function csvRows(text, d) {
    var all = parseCsv(text, d);
    if (!all.length) return { header: [], rows: [] };
    var header = all[0], rows = [];
    for (var r = 1; r < all.length; r++) {
      var vals = all[r];
      if (!vals.length) continue;
      var o = {};
      header.forEach(function (h, k) { o[h] = k < vals.length ? vals[k] : null; });
      rows.push(knownNames(o));
    }
    return { header: header, rows: rows };
  }

  var TABLE_FAIL = {};
  function jsonlRows(text) {
    var lines = text.split('\n').map(function (l) { return l.replace(/\r$/, ''); });
    var rows = [];
    for (var k = 0; k < lines.length; k++) {
      if (!lines[k].trim()) continue;
      var row;
      try { row = parseJSON(lines[k]); } catch (e) { TABLE_FAIL.message = 'Line ' + (k + 1) + " of this file isn't valid JSON."; return null; }
      if (!isObj(row)) { TABLE_FAIL.message = 'Line ' + (k + 1) + ' of this file is not a JSON object: each line must be one.'; return null; }
      rows.push(knownNames(row));
    }
    return rows;
  }

  function readTable(rows, firstColumns, kindWord) {
    if (!rows.length) return { error: 'no-rows', message: 'This file has no rows.' };
    var columns = [];
    rows.forEach(function (r) { Object.keys(r).forEach(function (k) { if (columns.indexOf(k) < 0) columns.push(k); }); });
    if (columns.indexOf('output_a') >= 0 && columns.indexOf('output_b') >= 0) return { error: 'pairwise', message: PAIRWISE };
    var verdict = VERDICT_COLUMNS.find(function (c) { return columns.indexOf(c) >= 0; });
    if (!verdict || columns.indexOf('input') < 0 || columns.indexOf('output') < 0) {
      return { error: 'columns', message: 'This file needs input, output and verdict columns.' };
    }
    var human = HUMAN_COLUMNS.find(function (c) { return columns.indexOf(c) >= 0; });
    var judged = [], nHuman = 0;
    rows.forEach(function (row) {
      var model = !blank(row.model) ? row.model : row.judge_model;
      judged.push({
        name: verdict, input: row.input === undefined ? null : row.input, output: row.output === undefined ? null : row.output,
        label: blank(row[verdict]) ? null : row[verdict], labelKind: numberKind(row, verdict), score: null,
        reason: blank(row.reason) ? '' : pyText(row.reason),
        model: blank(model) ? null : pyText(model), prompt: null, problem: null, countedAs: null, outputElsewhere: false
      });
      if (human && !blank(row[human])) nHuman += 1;
    });
    // front._columns_line: which columns were read (never the rows)
    var headVerdict = VERDICT_COLUMNS.find(function (c) { return firstColumns.indexOf(c) >= 0; });
    var readCols = ['input', 'output', headVerdict, 'reason', 'model', 'judge_model', 'app_version'].concat(HUMAN_COLUMNS);
    var used = firstColumns.filter(function (c) { return readCols.indexOf(c) >= 0; });
    return { tool: 'table', kindWord: kindWord, judged: judged, nHuman: nHuman, perMetric: {}, scoreJudge: false,
      columnsLine: used.length ? 'Read the columns ' + andList(used.map(function (c) { return clean(c, 40); })) + '.' : null };
  }
  function andList(items) { return items.length === 1 ? items[0] : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1]; }

  /* ---------- normalise.py: whatever a judge returned, as a decision ---------- */

  var LABEL_MAP = { pass: 'pass', fail: 'fail', 'true': 'pass', 'false': 'fail', yes: 'pass', no: 'fail',
    correct: 'pass', incorrect: 'fail', right: 'pass', wrong: 'fail', '1': 'pass', '0': 'fail' };
  var VERDICT_KEYS = ['verdict', 'pass', 'passed', 'label', 'score'];
  var REASON_KEYS = ['reason', 'rationale', 'explanation', 'comment'];

  // Python's str() of a JSON value, as far as a reason needs it
  function pyText(v) {
    if (v === null || v === undefined) return '';
    if (isStr(v)) return v;
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (typeof v === 'number') return String(v);
    return canonical(v);
  }
  // `kind`: how a number was written (numberKind); only a whole number written as one maps
  function nValue(x, kind) {
    if (x === null || x === undefined) return { verdict: 'error', rationale: '' };
    if (typeof x === 'boolean') return { verdict: x ? 'pass' : 'fail', rationale: '' };
    if (typeof x === 'number') {
      if (isNaN(x)) return { verdict: 'error', rationale: '' };
      var l = kind === 'int' ? LABEL_MAP[String(x)] : null;
      return l ? { verdict: l, rationale: '' } : { unmapped: kind === 'float' && Number.isInteger(x) ? x.toFixed(1) : x };
    }
    if (!isStr(x)) return { verdict: 'error', rationale: '' };
    var t = x.trim();
    if (!t) return { verdict: 'error', rationale: '' };
    var m = LABEL_MAP[t.toLowerCase()];
    if (m) return { verdict: m, rationale: '' };
    var lead = /^\s*(pass|fail)\b/i.exec(t);
    if (lead) return { verdict: lead[1].toLowerCase(), rationale: x };
    return { unmapped: t };
  }
  function normalise(raw, kind) {
    if (Array.isArray(raw)) {
      if (raw.length !== 2) return { verdict: 'error', rationale: '' };
      var res = nValue(raw[0]);
      if (res.unmapped !== undefined) return res;
      var reason = raw[1] === null ? '' : pyText(raw[1]);
      return { verdict: res.verdict, rationale: reason || res.rationale };
    }
    if (isObj(raw)) {
      var rk = REASON_KEYS.find(function (k) { return raw[k] !== null && raw[k] !== undefined; });
      var why = rk ? pyText(raw[rk]) : '';
      var key = VERDICT_KEYS.find(function (k) { return k in raw; });
      if (!key) return { verdict: 'error', rationale: why };
      var r2 = nValue(raw[key]);
      if (r2.unmapped !== undefined) return r2;
      return { verdict: r2.verdict, rationale: why || r2.rationale };
    }
    return nValue(raw, kind);
  }
  // records._verdict_value: the label, else the score
  function verdictOf(r) {
    var label = r.label !== null && r.label !== undefined;
    return normalise(label ? r.label : r.score, label ? r.labelKind : r.scoreKind);
  }

  function pyNumber(v) { return typeof v === 'number' && !isNaN(v) ? v : null; }

  /* ---------- start.build_pool: one answer per input and output ---------- */

  function buildPool(records, metric, extra) {
    extra = extra || {};
    var threshold = extra.strict ? null : extra.threshold;
    var groups = new Map(), unmapped = 0, unread = [];
    records.forEach(function (r) {
      if (r.name !== metric) return;
      var kind = r.problem, v = null;
      if (kind === null) {
        v = verdictOf(r);
        if (v.unmapped !== undefined) {
          unmapped += 1;
          if (unread.indexOf(String(v.unmapped)) < 0) unread.push(String(v.unmapped));
          return;
        }
        if (v.verdict === 'error') kind = 'empty';
      }
      var key = canonical({ input: r.input === null ? '' : r.input, output: r.output === null ? '' : r.output });
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ r: r, v: v, kind: kind });
    });
    var pool = { answers: [], left: [], merged: 0, unmapped: unmapped, unread: unread };
    groups.forEach(function (seen) {
      var judged = seen.filter(function (s) { return s.kind === null; });
      if (!judged.length) { pool.left.push({ kind: seen[0].kind, r: seen[0].r }); return; }
      pool.merged += judged.length - 1;
      var passes = judged.filter(function (s) { return s.v.verdict === 'pass'; }).length;
      var verdict = passes * 2 > judged.length ? 'pass' : 'fail';
      var chosen = judged.slice().reverse().find(function (s) { return s.v.verdict === verdict; });
      pool.answers.push({ verdict: verdict, output: chosen.r.output, outputElsewhere: !!chosen.r.outputElsewhere,
        reason: chosen.v.rationale || chosen.r.reason || '', score: pyNumber(chosen.r.score), passMark: pyNumber(threshold) });
    });
    pool.nPass = pool.answers.filter(function (a) { return a.verdict === 'pass'; }).length;
    pool.nFail = pool.answers.length - pool.nPass;
    return pool;
  }

  // start.pass_mark_of, for a DeepEval threshold: its direction comes from the decisions
  function passMarkOf(pool) {
    var a = pool.answers;
    if (!a.length || a.some(function (x) { return x.score === null || x.passMark === null; })) return null;
    var mark = a[0].passMark;
    if (a.some(function (x) { return x.passMark !== mark; })) return null;
    var fits = ['>=', '<='].filter(function (op) {
      return a.every(function (x) { return ((op === '>=' ? x.score >= mark : x.score <= mark) ? 'pass' : 'fail') === x.verdict; });
    });
    if (fits.length > 1) return null;
    return { mark: mark, op: fits.length ? fits[0] : null };
  }
  // Python's f"{x:g}"
  function fmtG(x) {
    if (x === 0) return '0';
    var e = Math.floor(Math.log10(Math.abs(x)));
    if (e < -4 || e >= 6) {
      var s = x.toExponential(5).replace(/\.?0+e/, 'e');
      return s.replace(/e([+-])(\d)$/, 'e$10$2');
    }
    return String(Number(x.toPrecision(6)));
  }
  function passMarkWords(pm) {
    var m = fmtG(pm.mark);
    var words = { '>=': m + ' or more', '>': 'more than ' + m, '<=': m + ' or less', '<': 'less than ' + m };
    return words[pm.op] ? 'score ' + words[pm.op] : 'score ' + m;
  }

  /* ---------- judge_check.py ---------- */

  var WORDS = { pass: 'pass', passed: 'pass', correct: 'pass', c: 'pass', fail: 'fail', failed: 'fail', incorrect: 'fail', i: 'fail' };
  var NOT_WORD = '(?![\\p{L}\\p{N}_])';
  var FIRST = new RegExp('^[\\s*"\'`#\\[(]*(pass(?:ed)?|fail(?:ed)?)' + NOT_WORD, 'iu');
  var MARKER = new RegExp('(?<![\\p{L}\\p{N}_])(?:final verdict|final answer|grade|verdict|result|decision)\\s*[:=]\\s*[*"\'`]*\\s*(pass(?:ed)?|fail(?:ed)?|correct|incorrect)' + NOT_WORD, 'giu');
  var GRADE = /GRADE\s*:\s*([CI])[ \t.*]*$/gm;

  function statedDecisions(reason) {
    if (!isStr(reason)) return [];
    var stated = [], m = FIRST.exec(reason);
    if (m) stated.push(WORDS[m[1].toLowerCase()]);
    var best = null;
    [MARKER, GRADE].forEach(function (re) {
      re.lastIndex = 0;
      var x;
      while ((x = re.exec(reason)) !== null) {
        if (!best || x.index > best[0] || (x.index === best[0] && x[1] > best[1])) best = [x.index, x[1]];
        if (x[0] === '') re.lastIndex += 1;
      }
    });
    if (best) stated.push(WORDS[best[1].toLowerCase()]);
    return stated;
  }
  function saysOpposite(reason, decision) { return statedDecisions(reason).some(function (s) { return s !== decision; }); }

  function isEmptyAnswer(output, elsewhere) {
    if (elsewhere) return false;
    if (isStr(output)) return !output.trim();
    if (Array.isArray(output)) return !output.length;
    if (isObj(output)) return !Object.keys(output).length;
    return false;
  }

  var NO_DECISION = ['error', 'unreadable', 'empty_answer_refused', 'empty'];
  var COUNTING_TOOLS = { promptfoo: 'promptfoo', deepeval: 'DeepEval' };  // tools that count decisions themselves
  var NO_DECISION_WORDS = {
    error: ['call failed', 'calls failed'], unreadable: ['reply could not be read', 'replies could not be read'],
    empty_answer_refused: ['empty answer it could not judge', 'empty answers it could not judge'],
    empty: ['empty decision', 'empty decisions']
  };
  var COUNTED = {
    pass: ['counted it as a pass', 'counted them as passes'], fail: ['counted it as a fail', 'counted them as fails'],
    'pass and fail': ['counted it as a pass or a fail', 'counted them as some passes and some fails'],
    'left out': ['left it out', 'left them out']
  };
  var SAME = {
    pass: 'Your judge passed every answer. It may not be checking anything: your marks will show it.',
    fail: 'Your judge failed every answer. It may be too strict, or not checking anything: your marks will show it.'
  };

  function judgeCheck(pool, tool, scoreJudge) {
    var counts = { error: 0, unreadable: 0, empty_answer_refused: 0, empty: 0, nothing_checked: 0, empty_answer_passed: 0, reason_says_opposite: 0 };
    var said = new Set();
    pool.left.forEach(function (l) { counts[l.kind] += 1; if (NO_DECISION.indexOf(l.kind) >= 0) said.add(l.r.countedAs); });
    pool.answers.forEach(function (a) {
      if (a.verdict === 'pass' && isEmptyAnswer(a.output, a.outputElsewhere)) counts.empty_answer_passed += 1;
      if (!scoreJudge && saysOpposite(a.reason, a.verdict)) counts.reason_says_opposite += 1;
    });
    var same = null;
    if (pool.answers.length >= 2 && !(pool.nPass && pool.nFail)) same = pool.nPass ? 'pass' : 'fail';
    var countedAs = null;
    if (COUNTING_TOOLS[tool] && said.size && !said.has(null)) {
      if (said.size === 2 && said.has('pass') && said.has('fail')) countedAs = 'pass and fail';
      else if (said.size === 1) countedAs = said.values().next().value;
    }
    return Object.assign({ answers: pool.answers.length + pool.left.length, same_decision: same, tool_counted_as: countedAs, tool: tool }, counts);
  }

  // judge_check.lines: one entry per finding, [] when nothing was found
  function findingLines(b) {
    var out = [];
    var name = COUNTING_TOOLS[b.tool] || null;
    var noDecision = NO_DECISION.reduce(function (s, k) { return s + b[k]; }, 0);
    if (noDecision) {
      var one = noDecision === 1;
      var parts = NO_DECISION.filter(function (k) { return b[k]; }).map(function (k) { return n(b[k], NO_DECISION_WORDS[k][0], NO_DECISION_WORDS[k][1]); });
      var counted = COUNTED[b.tool_counted_as];
      var said = name && counted ? name + ' ' + counted[one ? 0 : 1] + '. ' : '';
      out.push('Your judge made no real decision on ' + noDecision + ' of ' + b.answers + ' answers: ' + parts.join(', ') + '. ' +
        said + (one ? 'It is' : 'They are') + ' left out here.');
    }
    if (b.nothing_checked) {
      var one2 = b.nothing_checked === 1;
      out.push('On ' + n(b.nothing_checked, 'answer', 'answers') + ' your judge checked nothing, and ' + (name || 'your eval tool') +
        ' gave ' + (one2 ? 'it' : 'them') + ' full marks. ' + (one2 ? 'It is' : 'They are') + ' left out here.');
    }
    if (b.empty_answer_passed) out.push('Your judge passed ' + n(b.empty_answer_passed, 'empty answer', 'empty answers') + '.');
    if (b.reason_says_opposite) out.push('On ' + n(b.reason_says_opposite, 'answer', 'answers') + ", your judge's reason says the opposite of its decision.");
    if (SAME[b.same_decision]) out.push(SAME[b.same_decision]);
    return out;
  }

  /* ---------- start.rule_of / rule_text ---------- */

  // start._geval_rule: a GEval's criteria, else its evaluation steps
  function gevalRule(t) {
    var parts = {};
    t.split(DE_SEPARATOR).forEach(function (part) {
      DE_PROMPT_PARTS.forEach(function (nm) { if (part.indexOf(nm) === 0) parts[nm] = part.slice(nm.length).trim(); });
    });
    var criteria = parts['Criteria:'];
    if (criteria && criteria !== 'None') return t.slice('Criteria:'.length).trim();
    var steps = parts['Evaluation Steps:'];
    if (!steps || steps === 'None') return null;
    var listed;
    try { listed = JSON.parse(steps); } catch (e) { return steps; }
    if (!Array.isArray(listed)) return steps;
    listed = listed.map(pyText).filter(function (s) { return s.trim(); }).map(function (s) { return s.split(/\s+/).filter(Boolean).join(' '); });
    return listed.map(function (s, k) { return (k + 1) + '. ' + s; }).join('\n') || null;
  }

  function ruleText(prompt) {
    if (!isStr(prompt) || !prompt.trim()) return null;
    var data, parsed = true;
    try { data = JSON.parse(prompt); } catch (e) { parsed = false; }
    if (parsed && isObj(data)) {
      var texts = [data.instructions, data.template].filter(function (t) { return isStr(t) && t.indexOf('inspect_ai default for ') !== 0; });
      if (!texts.length) return null;
      prompt = texts[0];
    } else if (parsed) {
      return null;
    }
    var t = prompt.trim();
    if (t.indexOf('Criteria:') === 0) return gevalRule(t);
    return t || null;
  }

  /* ---------- which file is it: from its content, the name only for a .tsv ---------- */

  function fail(kind, message) { return { ok: false, kind: kind, message: message }; }

  function firstLine(t) { return t.split('\n', 1)[0].replace(/\r$/, ''); }

  function read(fileText, fileName) {
    var lower = String(fileName || '').toLowerCase();
    if (lower.split(/[\\/]/).pop() === 'judgekeeper.toml' || /^\s*\[start(\.map)?\]/m.test(fileText)) {
      return fail('settings', SETTINGS);
    }
    var data, parsed = true;
    try { data = parseJSON(fileText); } catch (e) { parsed = false; }
    if (parsed) {
      if (tooDeep(data)) return fail('not-json', NOT_JSON);
      // find.sniff_json: promptfoo's table output keeps each test's overall pass only
      if (isObj(data) && isObj(data.head) && Array.isArray(data.body)) return fail('table-output', TABLE_OUTPUT);
      if (isObj(data) && isObj(data.results) && Array.isArray(data.results.results)) {
        var pf = readPromptfoo(data);
        if (pf.error) return fail(pf.error, pf.message);
        pf.tool = 'promptfoo'; pf.perMetric = {}; pf.scoreJudge = false;
        return pf;
      }
      if (isLinkOnly(data)) return fail('link-only', LINK_ONLY);
      var de = deepevalData(data);
      if (de) return readDeepeval(de);
    }
    // JSONL: the first line is a JSON object
    var head = firstLine(fileText);
    var first = null;
    try { first = JSON.parse(head); } catch (e) { first = null; }
    if (isObj(first)) {
      var cols = Object.keys(first).map(columnName);
      if (isRecordsFile(cols)) return fail('records', RECORDS);
      if (isTable(cols)) {
        var rows = jsonlRows(fileText);
        if (!rows) return fail('bad-line', TABLE_FAIL.message);
        return readTable(rows, cols, /\.ndjson$/.test(lower) ? 'NDJSON' : 'JSONL');
      }
      return fail('not-recognised', NOT_RECOGNISED);
    }
    if (!parsed) {
      // CSV or TSV: the header names input, output and a verdict column
      var d = delimiterOf(fileText, /\.tsv$/.test(lower));
      var header = (parseCsv(head, d)[0] || []).map(columnName);
      if (isTable(header)) {
        var t = csvRows(fileText, d);
        return readTable(t.rows, header, d === '\t' && !/\.csv$/.test(lower) ? 'TSV' : 'CSV');
      }
      if (/^\s*[\[{]/.test(fileText)) return fail('not-json', NOT_JSON);
    }
    return fail('not-recognised', NOT_RECOGNISED);
  }

  /* ---------- the check: text in, report data out ---------- */

  function check(fileText, fileName) {
    if (!isStr(fileText)) fileText = '';
    if (fileText.charCodeAt(0) === 0xFEFF) fileText = fileText.slice(1);
    var r = read(fileText, fileName);
    if (r.ok === false) return r;
    if (r.error) return fail(r.error, r.message);
    var metrics = Array.from(new Set(r.judged.map(function (x) { return x.name; }))).sort(pyOrder);
    if (!metrics.length) {
      var said = oneLine(clean(fileName || 'This file', 80)) + NO_JUDGE;
      if (r.rulesInCode) said += ' These ' + RULES[r.tool] + RULES_IN_CODE;
      return fail('no-judge', said);
    }
    var judges = metrics.map(function (m) { return judgeReport(r, m, metrics.length); });
    // two names that look the same once hidden characters are taken out stay apart
    var shown = {};
    judges.forEach(function (j) { shown[j.name] = (shown[j.name] || 0) + 1; if (shown[j.name] > 1) j.name += ' (' + shown[j.name] + ')'; });
    var toolName = r.tool === 'table' ? 'your own ' + r.kindWord + ' file' : COUNTING_TOOLS[r.tool];
    return { ok: true, tool: r.tool, toolName: toolName, columnsLine: r.columnsLine || null,
      file: oneLine(clean(fileName || 'your file', 80)), judges: judges };
  }

  // Python sorts strings by code point; so does this
  function pyOrder(a, b) {
    var x = Array.from(a), y = Array.from(b);
    for (var i = 0; i < Math.min(x.length, y.length); i++) {
      var d = x[i].codePointAt(0) - y[i].codePointAt(0);
      if (d) return d;
    }
    return x.length - y.length;
  }

  function judgeReport(r, metric, nMetrics) {
    var records = r.judged.filter(function (x) { return x.name === metric; });
    var pool = buildPool(records, metric, r.perMetric[metric]);
    var block = judgeCheck(pool, r.tool, r.scoreJudge);
    var models = Array.from(new Set(records.map(function (x) { return x.model; }).filter(truthy).map(String))).sort(pyOrder);
    var promptRec = records.find(function (x) { return truthy(x.prompt); });
    var rule = ruleText(promptRec ? promptRec.prompt : null);
    return {
      key: metric,  // as the file has it; never shown
      name: oneLine(clean(metric, 80)) || 'unnamed judge',
      showName: nMetrics > 1 || r.tool === 'deepeval',
      answers: block.answers,
      pass: pool.nPass, fail: pool.nFail,
      merged: pool.merged, human: r.nHuman, unmapped: pool.unmapped,
      unread: pool.unread.slice(0, 3).map(function (v) { return oneLine(clean(v, 30)); }),
      moreUnread: pool.unread.length > 3,
      counts: block,
      allFailed: !pool.answers.length && pool.left.length > 0 && pool.left.every(function (l) { return l.kind === 'error'; }),
      passMark: r.tool === 'deepeval' ? passMarkOf(pool) : null,
      modelNotWritten: r.tool === 'promptfoo' && !models.length,
      models: models.map(function (m) { return oneLine(clean(m, 120)); }),
      rule: rule === null ? null : oneLine(clean(rule)),
      findings: findingLines(block)
    };
  }

  /* ---------- what it says (front.py's Find block and free check) ---------- */

  // [{k, text, tone}] lines: tone is '', 'dim', 'g' (all clear) or 'y' (a finding)
  function reportLines(result, j) {
    var L = [];
    var pad = '             ';
    L.push({ k: 'Eval tool:   ', text: result.toolName, tone: 'g' });
    L.push({ k: 'Answers:     ', text: n(j.answers, 'answer') + ', each graded by your judge' });
    L.push({ k: pad, text: '(read from ' + result.file + ')', tone: 'dim' });
    var model = j.models.length ? j.models.join(', ') : 'model not found in your file';
    L.push({ k: 'Judge:       ', text: (j.showName ? j.name + ', ' : '') + model });
    if (!j.rule) {
      L.push({ k: 'Judge rule:  ', text: 'not in your results' });
    } else if (j.rule.length <= RULE_SHOWN) {
      L.push({ k: 'Judge rule:  ', text: '"' + j.rule + '"' });
    } else {
      L.push({ k: 'Judge rule:  ', text: '"' + j.rule.slice(0, RULE_SHOWN - 1).replace(/\s+$/, '') + '…"' });
      L.push({ k: pad, text: '(shortened)', tone: 'dim' });
    }
    if (j.passMark) L.push({ k: 'Pass mark:   ', text: passMarkWords(j.passMark) });
    if (result.columnsLine) { L.push({ text: '' }); L.push({ text: result.columnsLine, tone: 'dim' }); }
    L.push({ text: '' });
    if (j.pass + j.fail) L.push({ text: "Your judge's grades: " + j.pass + ' Pass, ' + j.fail + ' Fail.' });
    var notes = [];
    if (j.merged) notes.push(n(j.merged, 'repeat') + ' of the same answer ' + (j.merged === 1 ? 'was' : 'were') + ' merged.');
    if (j.human) notes.push('Your results also hold ' + n(j.human, 'human label') + '. judgekeeper does not use them: you mark the answers yourself.');
    var total = j.pass + j.fail;
    [[j.fail, 'failed', 'passes too much'], [j.pass, 'passed', 'fails too much']].forEach(function (x) {
      if (x[0] > 0 && x[0] < ROUGH && total >= MIN_POOL) notes.push('Your judge ' + x[1] + ' only ' + x[0] + ' of ' + total + ' answers. That may mean it ' + x[2] + ': your marks will show it.');
    });
    if (j.unmapped) {
      notes.push(n(j.unmapped, 'grade') + ' could not be read as Pass or Fail (' + j.unread.map(function (v) { return '"' + v + '"'; }).join(', ') +
        (j.moreUnread ? ' and more' : '') + '). ' + (j.unmapped === 1 ? 'It is' : 'They are') +
        ' left out here; judgekeeper in your project asks what ' + (j.unmapped === 1 ? 'it means' : 'they mean') + '.');
    }
    notes.forEach(function (t) { L.push({ text: t }); });
    if (!j.findings.length) {
      L.push({ text: FREE_CHECK + EVERY_ANSWER, tone: 'g' });
    } else {
      j.findings.forEach(function (f, i) {
        L.push({ text: i === 0 ? FREE_CHECK + f.charAt(0).toLowerCase() + f.slice(1) : f, tone: 'y' });
      });
    }
    if (j.modelNotWritten) L.push({ text: MODEL_NOT_WRITTEN, tone: 'y' });
    if (!total) L.push({ text: j.allFailed ? ALL_FAILED : NO_CLEAR, tone: 'y' });
    return L;
  }

  var api = { check: check, reportLines: reportLines, MAX_BYTES: MAX_BYTES, LIMIT: LIMIT, PRIVACY: PRIVACY,
    TOO_BIG: TOO_BIG, NOT_UTF8: NOT_UTF8, NOT_RECOGNISED: NOT_RECOGNISED, clean: clean,
    _internal: { statedDecisions: statedDecisions, graderProblem: graderProblem, ruleText: ruleText, passMarkWords: passMarkWords } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.JKFreeCheck = api;

  /* ---------- the page ---------- */
  if (typeof document === 'undefined') return;

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined) e.textContent = txt;
    return e;
  }

  function setup() {
    var zone = document.getElementById('fc-drop');
    var input = document.getElementById('fc-file');
    var out = document.getElementById('fc-result');
    var next = document.getElementById('fc-next');
    if (!zone || !input || !out || !next) return;

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { if (input.files && input.files[0]) take(input.files[0], input.files.length); input.value = ''; });

    // a file dropped anywhere on the page goes to the check, never opens in the tab
    ['dragenter', 'dragover'].forEach(function (t) {
      document.addEventListener(t, function (e) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; zone.classList.add('over'); });
    });
    document.addEventListener('dragleave', function (e) { if (!e.relatedTarget) zone.classList.remove('over'); });
    document.addEventListener('drop', function (e) {
      e.preventDefault(); zone.classList.remove('over');
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) take(files[0], files.length);
    });

    function take(file, count) {
      zone.classList.add('busy');
      if (file.size > MAX_BYTES) { done(); return showError(TOO_BIG); }
      var reader = new FileReader();
      reader.onerror = function () { done(); showError('This file could not be read. Try picking it again.'); };
      reader.onload = function () {
        done();
        var textOut;
        try { textOut = new TextDecoder('utf-8', { fatal: true }).decode(reader.result); } catch (e) { return showError(NOT_UTF8); }
        show(check(textOut, file.name), count);
      };
      reader.readAsArrayBuffer(file);
    }
    function done() { zone.classList.remove('busy'); }

    function showError(message) {
      out.replaceChildren();
      next.hidden = true;
      var card = el('div', 'card fc-problem');
      card.appendChild(el('p', 'fc-problem-h', message));
      card.appendChild(el('p', 'small', 'Pick another file, or run uvx judgekeeper in your project: it finds your results by itself.'));
      out.appendChild(card);
    }

    function show(result, count) {
      if (!result.ok) return showError(result.message);
      out.replaceChildren();
      if (count > 1) out.appendChild(el('p', 'small', 'You gave ' + count + ' files. This page reads one at a time: it read ' + result.file + '.'));
      var current = 0;
      var pre = el('pre', 'output fc-term');

      if (result.judges.length > 1) {
        var pick = el('div', 'fc-pick');
        var id = 'fc-pick-label';
        pick.appendChild(el('p', 'fc-pick-h', 'Your file has ' + result.judges.length + ' judges. Pick one to check:')).id = id;
        var group = el('div', 'fc-pick-list');
        group.setAttribute('role', 'radiogroup');
        group.setAttribute('aria-labelledby', id);
        var buttons = result.judges.map(function (j, i) {
          var b = el('button', 'btn secondary', j.name);
          b.type = 'button';
          b.setAttribute('role', 'radio');
          b.addEventListener('click', function () { select(i, false); });
          b.addEventListener('keydown', function (e) {
            var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
            if (!step) return;
            e.preventDefault();
            select((i + step + buttons.length) % buttons.length, true);
          });
          group.appendChild(b);
          return b;
        });
        pick.appendChild(group);
        out.appendChild(pick);
        var select = function (i, focus) {
          current = i;
          buttons.forEach(function (b, k) {
            b.setAttribute('aria-checked', k === i ? 'true' : 'false');
            b.tabIndex = k === i ? 0 : -1;
          });
          if (focus) buttons[i].focus();
          paint();
        };
        out.appendChild(pre);
        select(0, false);
      } else {
        out.appendChild(pre);
        paint();
      }
      next.hidden = false;

      function paint() {
        pre.replaceChildren();
        reportLines(result, result.judges[current]).forEach(function (line) {
          var row = el('span', 'ln');
          if (line.k) row.appendChild(el('span', 'dim', line.k));
          row.appendChild(el('span', { g: 'ok', y: 'care', dim: 'dim' }[line.tone] || null, line.text));
          pre.appendChild(row);
        });
      }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})(typeof globalThis !== 'undefined' ? globalThis : this);

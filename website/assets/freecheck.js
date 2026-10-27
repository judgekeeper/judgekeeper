/* judgekeeper: the check in your browser (check.html).
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
  var FIRST_SHOWN = 140;  // the page's first answer: question and answer cut to this many characters
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
    grading: ["LLM-as-a-judge's decisions", 'PROMPTFOO_STRIP_GRADING_RESULT']
  };

  var NOT_RECOGNISED = "This doesn't look like results judgekeeper can read in the browser. The tool also reads Inspect AI and MLflow: run uvx judgekeeper in your project.";
  var IN_PROJECT = ' This page does not read it: run uvx judgekeeper in your project for this file.';
  var RECORDS = 'This is a judgekeeper.record() file.' + IN_PROJECT;
  var SETTINGS = "This is judgekeeper's settings file (judgekeeper.toml)." + IN_PROJECT;
  var TABLE_OUTPUT = "This is promptfoo's table output, which doesn't keep the LLM-as-a-judge's own decisions. Save the full results with promptfoo eval -o results.json.";
  // start._no_judge: a file with no LLM judge's decisions
  var NO_JUDGE = ' holds no decisions from an LLM-as-a-judge.';
  var RULES = { promptfoo: 'checks', deepeval: 'metrics' };
  var RULES_IN_CODE = ' are rules in code, not an LLM-as-a-judge. judgekeeper checks an LLM-as-a-judge.';
  var TOO_BIG = 'This file is bigger than 50 MB, so this page does not read it. Run uvx judgekeeper in your project instead: it reads big files too.';
  var NOT_UTF8 = 'This file is not saved as UTF-8 text, so it cannot be read.';
  var EMPTY = 'This file is empty.';
  var FULL_TOOL = 'Inspect AI and MLflow results are read by the full tool: run uvx judgekeeper in your project.';
  var EXCEL_FILE = "Excel files aren't read. Save it as CSV UTF-8.";
  var SPREADSHEET_FILE = "Spreadsheet files aren't read. Save it as CSV UTF-8.";
  // first bytes: a zip (Inspect's .eval log, or an Excel or OpenDocument spreadsheet) and an
  // SQLite file (an MLflow store)
  var ZIP_START = [0x50, 0x4B, 0x03, 0x04];
  var BINARY_STARTS = [ZIP_START, Array.from('SQLite format 3\0', function (c) { return c.charCodeAt(0); })];
  var EXCEL_ENTRIES = ['[Content_Types].xml', 'xl/', '_rels/', 'docProps/'];
  var OPENDOCUMENT = 'application/vnd.oasis.opendocument.';  // the text of an OpenDocument's first entry, mimetype
  var NOT_JSON = "This file isn't valid JSON that judgekeeper can read.";
  var EVERY_ANSWER = 'your LLM-as-a-judge gave every answer a clear Pass or Fail.';
  var FREE_CHECK = 'Checked: ';
  var MODEL_NOT_WRITTEN = "Your LLM-as-a-judge's model isn't written in your config. promptfoo picks it from whichever API key is set, so it can change without any file changing. Write it in your config (defaultTest.options.provider).";
  var NO_CLEAR = 'No answer has a clear Pass or Fail from your LLM-as-a-judge, so there is nothing to mark.';
  // judge_check.MODEL_FAILED_LINE, ALL_MODEL_FAILED and MODEL_FAILED_NEXT: the same words
  var MODEL_FAILED_LINE = ' no answer: the call to the model you test failed, so your LLM-as-a-judge never ran.';
  var ALL_MODEL_FAILED = 'The call to the model you test failed on every answer, so your LLM-as-a-judge never ran and there is nothing to mark.';
  var MODEL_FAILED_NEXT = 're-run your eval once the model you test answers, then run judgekeeper in your project folder.';
  var ALL_FAILED = "Your LLM-as-a-judge's calls failed on every answer, so there is nothing to mark.";
  var PRIVACY = 'Your file never leaves this page: it is read on your computer. Once the page has loaded, it works with Wi-Fi turned off.';

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

  /* ---------- records.read_rows: a row with a field of the wrong type is left out ---------- */

  // Thrown where the tool's reading of a row raises (a string where an object should be, a
  // list for a name...): the row adds nothing and is counted. When every row is left out, the
  // file is damaged (records.all_damaged).
  var DAMAGED = { damaged: true };
  var ROW_NESTING = 100;
  function damagedIf(bad) { if (bad) throw DAMAGED; }
  // json.dumps(allow_nan=False) of an answer: no number too big, nested at most ROW_NESTING deep
  function badAnswer(value) {
    var stack = [[value, 0]];
    while (stack.length) {
      var top = stack.pop(), v = top[0], d = top[1];
      if (typeof v === 'number' && !isFinite(v)) return true;
      if (v === null || typeof v !== 'object') continue;
      if (d + 1 > ROW_NESTING) return true;
      (Array.isArray(v) ? v : Object.keys(v).map(function (k) { return v[k]; })).forEach(function (x) { stack.push([x, d + 1]); });
    }
    return false;
  }
  function plainValue(v) {
    return v === null || v === undefined || isStr(v) || typeof v === 'boolean' || (typeof v === 'number' && isFinite(v));
  }
  // records.check_record: a value judgekeeper can't use further on damages the row
  function checkRecord(rec) {
    damagedIf(!isStr(rec.name) || !plainValue(rec.label) || !plainValue(rec.score));
    damagedIf(rec.explanation !== null && rec.explanation !== undefined && !isStr(rec.explanation));
    damagedIf(badAnswer(rec.input) || badAnswer(rec.output));
    damagedIf(rec.model !== null && rec.model !== undefined && !isStr(rec.model));
  }
  function damagedFile(rows, tool) {
    return { error: 'damaged', message: 'This file is damaged: ' + (rows === 1 ? 'its only row' : 'each of its ' + rows + ' rows') +
      ' has a damaged field. Save it again from ' + tool + '.' };
  }

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

  // promptfoo.py _one_rubric: the one model-graded assertion of a row saved with no
  // gradingResult, when it is the test's only assertion (the row's success is its decision)
  function oneRubric(r) {
    if (truthy(r.gradingResult) || typeof r.success !== 'boolean') return null;
    var asserts = get(or(r.testCase, {}), 'assert');
    if (!Array.isArray(asserts) || asserts.length !== 1 || !isObj(asserts[0])) return null;
    return judgeType(asserts[0].type) ? asserts[0] : null;
  }
  // promptfoo.py _provider_failed: the model under test never answered, so the judge never ran
  function providerFailed(r) {
    return r.failureReason === 2 || truthy(r.error) || truthy(get(or(r.response, {}), 'error'));
  }

  function components(grading) {
    var out = [];
    var comps = (or(get(or(grading, {}), 'componentResults'), []) || []);
    comps = Array.isArray(comps) ? comps.filter(isObj) : [];
    var i = 0;
    while (i < comps.length) {
      var c = comps[i]; i += 1;
      var inner = c.componentResults;
      damagedIf(truthy(inner) && (typeof inner === 'number' || typeof inner === 'boolean'));  // can't be walked
      var nested = Array.isArray(inner) ? inner.filter(isObj) : [];
      if (nested.length) damagedIf(truthy(c.assertion) && !isObj(c.assertion));
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
    if (id !== null && id.indexOf('exec:') === 0) {  // the person's own script: its command, never a path
      return 'your own script (' + id.slice(5).trim().split(/\s+/).map(function (w) { return w.split(/[\\/]/).pop(); }).join(' ') + ')';
    }
    return id;
  }

  // promptfoo._shaped: each part an object or missing, so the row can be read
  function shaped(r) {
    if (!isObj(r)) return false;
    var parts = [r.response, r.testCase, r.vars, r.gradingResult];
    if (!parts.every(function (p) { return p === null || p === undefined || isObj(p); })) return false;
    var comps = get(or(r.gradingResult, {}), 'componentResults');
    if (!(comps === null || comps === undefined || Array.isArray(comps))) return false;
    var testVars = get(or(r.testCase, {}), 'vars');
    var description = or(get(or(r.testCase, {}), 'description'), r.description === undefined ? null : r.description);
    return (testVars === null || testVars === undefined || isObj(testVars)) && (description === null || isStr(description));
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
    var rows = summary.results.filter(shaped);  // each other row is left out
    var leftOut = summary.results.length - rows.length, kept = 0;
    var defaultTest = get(or(data.config, {}), 'defaultTest');
    defaultTest = isObj(defaultTest) ? defaultTest : {};
    var gone = stripped(rows.filter(function (r) { return oneRubric(r) === null; }));
    if (gone.length) return { error: 'stripped', message: strippedMessage(gone.indexOf('grading') >= 0 ? 'grading' : gone[0]) };
    var judged = [], nHuman = 0, nCode = 0;
    var readRow = function (r) {
      damagedIf(Array.isArray(r.promptIdx) || isObj(r.promptIdx));  // a key the tool counts repeats by
      var testOpts = options(r.testCase);
      var output = text(get(or(r.response, {}), 'output'));
      var input = r.vars === undefined ? null : r.vars;
      var perRow = {};
      var comps = components(r.gradingResult);
      var only = oneRubric(r), failed = only !== null && providerFailed(r);
      if (only !== null) comps = [{ pass: failed ? null : r.success, score: null, reason: '', assertion: only }];
      for (var ci = 0; ci < comps.length; ci++) {
        var c = comps[ci];
        damagedIf(truthy(c.assertion) && !isObj(c.assertion));
        var a = isObj(c.assertion) ? c.assertion : {};
        var kind = a.type;
        var label = typeof c.pass === 'boolean' ? (c.pass ? 'pass' : 'fail') : null;
        var score = c.score === undefined ? null : c.score;
        if (kind === 'human') {
          checkRecord({ name: 'human', label: label, score: score, explanation: or(c.comment, null), input: input, output: output });
          nHuman += 1; continue;
        }
        var name = or(a.metric, kind, 'unknown');
        if (judgeType(kind) === null) {
          checkRecord({ name: name, label: label, score: score, input: input, output: output });
          nCode += 1; continue;
        }
        perRow[name] = (perRow[name] || 0) + 1;
        if (perRow[name] > 1) {
          var idx = r.testIdx;
          var test = typeof idx === 'number' && Math.floor(idx) === idx ? idx + 1 : idx;
          return { error: 'two-judges', message: 'Test ' + clean(test, 20) + ' has more than one ' + JSON.stringify(clean(name, 80)) +
            ' assertion. Give each one a name with metric: in its assertion, then run your eval again (that makes model calls).' };
        }
        var grader = or(a.provider, testOpts.provider, options(defaultTest).provider, defaultTest.provider, null);
        if (!truthy(grader)) grader = null;
        var model = grader === null ? null : modelOf(grader);
        var metadata = isObj(c.metadata) ? c.metadata : {};
        var rubricPrompt = or(a.rubricPrompt, testOpts.rubricPrompt, options(defaultTest).rubricPrompt);
        var prompt = text(a.value);
        if (truthy(rubricPrompt)) prompt = (prompt || '') + '\n\n' + text(rubricPrompt);
        var problem = failed ? 'model_failed' : graderProblem(c, metadata);
        checkRecord({ name: name, label: label, score: score, explanation: or(c.reason, null), input: input, output: output, model: model });
        judged.push({
          name: name, input: input, output: output, label: label,
          score: score, scoreKind: numberKind(c, 'score'),
          reason: isStr(c.reason) ? c.reason : '',
          model: model, prompt: prompt, problem: problem,
          countedAs: failed ? 'fail' : problem ? label : null
        });
      }
    };
    for (var ri = 0; ri < rows.length; ri++) {
      var before = [judged.length, nHuman, nCode];
      try {
        var stop = readRow(rows[ri]);
        if (stop) return stop;
        kept += judged.length - before[0] + nHuman - before[1] + nCode - before[2];
      } catch (e) {
        if (e !== DAMAGED) throw e;
        judged.length = before[0]; nHuman = before[1]; nCode = before[2];
        leftOut += 1;
      }
    }
    if (leftOut && !kept) return damagedFile(leftOut, 'promptfoo');
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
    var readCase = function (c, conversational) {
      damagedIf(!isObj(c));
      var input, output;
      if (conversational) { input = truthy(c.scenario) ? c.scenario : canonical(truthy(c.turns) ? c.turns : []); output = ''; }
      else { input = c.input === undefined ? null : c.input; output = c.actualOutput === undefined ? null : c.actualOutput; }
      var caseName = c.name;  // text or a whole number, when there is one
      damagedIf(!(caseName === null || caseName === undefined || isStr(caseName) ||
        (typeof caseName === 'number' && Number.isInteger(caseName) && numberKind(c, 'name') !== 'float')));
      damagedIf(truthy(c.metricsData) && !Array.isArray(c.metricsData));
      var read = [];
      (truthy(c.metricsData) ? c.metricsData : []).forEach(function (md) {
        damagedIf(!isObj(md));
        damagedIf(truthy(md.verboseLogs) && !isStr(md.verboseLogs));
        var named = Object.prototype.hasOwnProperty.call(md, 'name'), name = md.name;
        if (typeof md.threshold === 'number') {
          damagedIf(!named);
          if (isStr(name)) {
            thresholds[name] = thresholds[name] || [];
            if (!thresholds[name].some(function (t) { return t === md.threshold; })) thresholds[name].push(md.threshold);
          }
        }
        if (md.strictMode === true) { damagedIf(!named); if (isStr(name)) strict[name] = true; }
        damagedIf(!named);
        var label = typeof md.success === 'boolean' ? (md.success ? 'pass' : 'fail') : null;
        var problem = null;
        if (deFailed(md)) problem = String(md.error || '').indexOf(EMPTY_REFUSED) === 0 ? 'empty_answer_refused' : 'error';
        else if (checkedNothing(md)) problem = 'nothing_checked';
        var model = truthy(md.evaluationModel) ? md.evaluationModel : null;
        read.push({ name: name, label: label, score: md.score === undefined ? null : md.score, explanation: or(md.reason, null),
          input: input, output: output, model: model });
        judged.push({
          name: name, input: input, output: output, label: label,
          score: md.score === undefined ? null : md.score, scoreKind: numberKind(md, 'score'),
          reason: pyText(or(md.reason, md.error, null)),
          model: model, prompt: rubricFromLogs(md.verboseLogs), problem: problem,
          countedAs: problem ? label : null, outputElsewhere: conversational
        });
      });
      read.forEach(checkRecord);
    };
    var leftOut = 0;
    cases.forEach(function (pair) {
      var before = judged.length;
      try { readCase(pair[0], pair[1]); } catch (e) {
        if (e !== DAMAGED) throw e;
        judged.length = before;
        leftOut += 1;
      }
    });
    if (leftOut && !judged.length) return damagedFile(leftOut, 'DeepEval');
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
  // mapper.py: a column named for the judge is listed first; a 0/1 column named for one is a verdict
  var JUDGE_NAMED = ['judge', 'llm'];
  var JUDGE_WORDS = ['judge', 'judgment', 'judgement', 'eval', 'evaluation', 'grader', 'grading'];
  var RULE_VALUES = ['0', '1', 'true', 'false'];
  var NONE_WORDS = ['error', 'n/a', 'null', 'none', 'nan'];  // normalise.NO_DECISION
  var VERDICT_VALUES = ['pass', 'passed', 'fail', 'failed', 'true', 'false', 'yes', 'no', 'y', 'n', 'correct',
    'incorrect', 'right', 'wrong', 'good', 'bad', 'ok', 'accept', 'accepted', 'reject',
    'rejected', 'success', 'failure', 'partial', 'partially correct', 'c', 'i', 'p'];
  // Words a model's name holds: a model column whose values have none of them (and no digit,
  // slash or colon) names a rule, not a model
  var MODEL_WORDS = ['gpt', 'claude', 'gemini', 'llama', 'mistral', 'mixtral', 'qwen', 'deepseek',
    'sonnet', 'haiku', 'opus', 'openai', 'anthropic', 'azure', 'bedrock', 'ollama',
    'groq', 'cohere', 'command', 'phi', 'gemma', 'grok', 'openrouter', 'vertex',
    'together', 'fireworks', 'nova', 'titan', 'palm', 'codex'];
  var WORD = /[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+/g;
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

  function words(key) { return (String(key).match(WORD) || []).map(function (w) { return w.toLowerCase(); }); }
  function namedFor(key, list) { return words(key).some(function (w) { return list.indexOf(w) >= 0; }); }
  // mapper.blank: no score at all (an empty cell, or a word for none)
  function noScore(v) { return v === null || v === undefined || (isStr(v) && (!v.trim() || NONE_WORDS.indexOf(v.trim().toLowerCase()) >= 0)); }
  // mapper._judge_column: a column named for a judge (llm_judge) holding only 0/1 or true/false
  function judgeColumn(col, rows) {
    if (!namedFor(col, JUDGE_WORDS)) return false;
    var seen = rows.filter(function (row) { return !noScore(row[col]); });
    return seen.length > 0 && seen.every(function (row) {
      var v = row[col];
      if (typeof v === 'boolean') return true;
      if (typeof v === 'number') return (v === 0 || v === 1) && numberKind(row, col) !== 'float';  // str(1.0) is "1.0"
      return isStr(v) && RULE_VALUES.indexOf(v.trim().toLowerCase()) >= 0;
    });
  }
  // mapper._judge_first: the judges named for a judge (judge_verdict, llm_judge) first
  function judgeFirst(judges) {
    var named = judges.filter(function (j) { return namedFor(j, JUDGE_NAMED); });
    return named.concat(judges.filter(function (j) { return named.indexOf(j) < 0; }));
  }
  // mapper._model_like: a value that reads as a model's name (gpt-4.1, ollama/qwen2.5:3b)
  function modelLike(v) {
    if (!isStr(v) || !v.trim()) return false;
    var t = v.trim().toLowerCase();
    return /[0-9\/:]/.test(t) || namedFor(t, MODEL_WORDS);
  }
  // mapper._verdict_value, for a cell's text: a verdict word, or a number from 0 to 100
  function verdictValue(v) {
    if (/^\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*$/.test(v)) { var x = parseFloat(v); return x >= 0 && x <= 100; }
    return VERDICT_VALUES.indexOf(v.trim().toLowerCase()) >= 0;
  }

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
  // table.open_quote: the line where a quoted cell starts that swallows the rows after it (its
  // quote never closes, or closes only rows later), or null. Read as Python's csv reader reads
  // with strict on: a line at a time, and a quote out of place elsewhere ends the look.
  function openQuote(text, d) {
    var lines = text.match(/[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$/g) || [];
    var header = null, verdict = null, start = 1, k = 0, EOL = null;
    for (;;) {
      var fields = [], field = '', state = 'record';
      do {
        if (k >= lines.length) return state === 'quoted' || field.length ? start : null;
        var line = lines[k++];
        for (var i = 0; i <= line.length; i++) {
          var c = i < line.length ? line[i] : EOL, newline = c === '\n' || c === '\r' || c === EOL;
          if (state === 'record') {
            if (c === EOL) break;  // an empty line: []
            if (newline) { state = 'eat'; continue; }
            state = 'field';
          }
          if (state === 'field' || state === 'in') {
            if (newline) { fields.push(field); field = ''; state = c === EOL ? 'record' : 'eat'; }
            else if (c === '"' && state === 'field') state = 'quoted';
            else if (c === d) { fields.push(field); field = ''; state = 'field'; }
            else { field += c; state = 'in'; }
          } else if (state === 'quoted') {
            if (c === '"') state = 'quote2'; else if (c !== EOL) field += c;
          } else if (state === 'quote2') {
            if (c === '"') { field += c; state = 'quoted'; }
            else if (c === d) { fields.push(field); field = ''; state = 'field'; }
            else if (newline) { fields.push(field); field = ''; state = c === EOL ? 'record' : 'eat'; }
            else return null;  // a quote out of place, not one that never closes
          } else if (state === 'eat') {
            if (c === EOL) state = 'record'; else if (!newline) return null;
          }
        }
      } while (state !== 'record');
      if (header === null) {
        header = fields;
        verdict = header.findIndex(function (h) { return VERDICT_COLUMNS.indexOf(columnName(h)) >= 0; });
        if (verdict < 0) verdict = null;
      } else if (header.length >= 3 && fields.some(function (cell) { return cell.indexOf('\n') >= 0 && rowsInside(cell, d, header.length, verdict) >= 2; })) {
        return start;
      }
      start = k + 1;
    }
  }
  // table._rows_inside: how many lines of a cell read as a whole row, with a grade at `verdict`
  function rowsInside(cell, d, columns, verdict) {
    return cell.split('\n').filter(function (line) {
      var r = parseCsv(line, d)[0] || [];
      return r.length === columns && (verdict === null || verdictValue(r[verdict]));
    }).length;
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
    var verdicts = VERDICT_COLUMNS.filter(function (c) { return columns.indexOf(c) >= 0; });  // each one is a judge
    if (verdicts.length) {  // and a 0/1 column named for a judge (llm_judge), the judge-named first
      verdicts = judgeFirst(verdicts.concat(columns.filter(function (c) {
        return verdicts.indexOf(c) < 0 && KNOWN_COLUMNS.indexOf(c) < 0 && judgeColumn(c, rows);
      })));
    }
    if (!verdicts.length || columns.indexOf('input') < 0 || columns.indexOf('output') < 0) {
      return { error: 'columns', message: 'This file needs input, output and verdict columns.' };
    }
    var human = HUMAN_COLUMNS.find(function (c) { return columns.indexOf(c) >= 0; });
    var judged = [], nHuman = 0;
    rows.forEach(function (row) {
      var model = !blank(row.model) ? row.model : row.judge_model;
      if (!modelLike(model)) model = null;  // "string_match": a rule's name, not a model's
      verdicts.forEach(function (verdict) {
        judged.push({
          name: verdict, input: row.input === undefined ? null : row.input, output: row.output === undefined ? null : row.output,
          label: blank(row[verdict]) ? null : row[verdict], labelKind: numberKind(row, verdict), score: null,
          reason: blank(row.reason) ? '' : pyText(row.reason),
          model: model, prompt: null, problem: null, countedAs: null, outputElsewhere: false
        });
      });
      if (human && !blank(row[human])) nHuman += 1;
    });
    // front.read_rows: which columns were read (never the rows); the grade from the judge's own
    var headVerdict = VERDICT_COLUMNS.find(function (c) { return firstColumns.indexOf(c) >= 0; });
    var modelCol = ['judge_model', 'model'].find(function (c) { return firstColumns.indexOf(c) >= 0; });
    var labelCol = HUMAN_COLUMNS.find(function (c) { return firstColumns.indexOf(c) >= 0; });
    var readRows = {};
    verdicts.forEach(function (verdict) {
      var grade = firstColumns.indexOf(verdict) >= 0 ? verdict : headVerdict;
      var said = [['question', 'the input column'], ['answer', 'the output column'], ['grade', 'the ' + clean(grade, 40) + ' column']];
      [['reason', firstColumns.indexOf('reason') >= 0 ? 'reason' : null], ['model', modelCol || null],
       ['version', firstColumns.indexOf('app_version') >= 0 ? 'app_version' : null], ['your labels', labelCol || null]]
        .forEach(function (x) { if (x[1]) said.push([x[0], 'the ' + x[1] + ' column']); });
      readRows[verdict] = said;
    });
    return { tool: 'table', kindWord: kindWord, judged: judged, nHuman: nHuman, humanFor: verdicts[0], perMetric: {},
      scoreJudge: false, order: verdicts, readRows: readRows };
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
    var pool = { answers: [], left: [], merged: 0, repeatSizes: [], split: [], unmapped: unmapped, unread: unread };
    groups.forEach(function (seen) {
      var judged = seen.filter(function (s) { return s.kind === null; });
      if (!judged.length) { pool.left.push({ kind: seen[0].kind, r: seen[0].r }); return; }
      var passes = judged.filter(function (s) { return s.v.verdict === 'pass'; }).length;
      if (pool.repeatSizes.indexOf(judged.length) < 0) pool.repeatSizes.push(judged.length);
      if (passes === 0 || passes === judged.length) {  // the same grade every time: one answer
        pool.merged += judged.length - 1;
        judged = judged.slice(-1);
      } else {  // different grades: each repeat is its own answer, never merged in silence
        pool.split.push([judged.length, passes, judged.length - passes]);
      }
      judged.forEach(function (chosen) {
        pool.answers.push({ verdict: chosen.v.verdict, input: chosen.r.input, output: chosen.r.output, outputElsewhere: !!chosen.r.outputElsewhere,
          reason: chosen.v.rationale || chosen.r.reason || '', score: pyNumber(chosen.r.score), passMark: pyNumber(threshold) });
      });
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
    pass: 'Your LLM-as-a-judge passed every answer. It may not be checking anything: your marks will show it.',
    fail: 'Your LLM-as-a-judge failed every answer. It may be too strict, or not checking anything: your marks will show it.'
  };

  function judgeCheck(pool, tool, scoreJudge) {
    var counts = { error: 0, unreadable: 0, empty_answer_refused: 0, empty: 0, nothing_checked: 0, model_failed: 0, empty_answer_passed: 0, reason_says_opposite: 0 };
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
      out.push('Your LLM-as-a-judge made no real decision on ' + noDecision + ' of ' + b.answers + ' answers: ' + parts.join(', ') + '. ' +
        said + (one ? 'It is' : 'They are') + ' left out here.');
    }
    if (b.model_failed) {
      out.push(n(b.model_failed, 'answer has', 'answers have') + MODEL_FAILED_LINE + ' ' +
        (b.model_failed === 1 ? 'It is' : 'They are') + ' left out here.');
    }
    if (b.nothing_checked) {
      var one2 = b.nothing_checked === 1;
      out.push('On ' + n(b.nothing_checked, 'answer', 'answers') + ' your LLM-as-a-judge found nothing to check, but ' + (name || 'your eval tool') +
        ' still gave ' + (one2 ? 'it' : 'them') + ' full marks, so ' + (one2 ? 'it is' : 'they are') + ' left out.');
    }
    if (b.empty_answer_passed) out.push('Your LLM-as-a-judge passed ' + n(b.empty_answer_passed, 'empty answer', 'empty answers') + '.');
    if (b.reason_says_opposite) out.push('On ' + n(b.reason_says_opposite, 'answer', 'answers') + ", your LLM-as-a-judge's reason says the opposite of its decision.");
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
        var open = openQuote(fileText, d);
        if (open !== null) return fail('open-quote', 'Line ' + open + " of this file has a quote that never closes, so the rows after it can't be read.");
        var t = csvRows(fileText, d);
        return readTable(t.rows, header, d === '\t' && !/\.csv$/.test(lower) ? 'TSV' : 'CSV');
      }
      if (/^\s*[\[{]/.test(fileText)) return fail('not-json', NOT_JSON);
    }
    return fail('not-recognised', NOT_RECOGNISED);
  }

  /* ---------- the check: text in, report data out ---------- */

  // an Excel file is a zip whose first entry is [Content_Types].xml, xl/, _rels/ or docProps/;
  // an OpenDocument file's first entry is mimetype, its text the kind of document. The
  // entry's name starts at byte 30 of a zip, its length is at bytes 26-27 and the length of
  // the extra field after it at bytes 28-29. 'excel', 'spreadsheet', 'opendocument' or null.
  function zipKind(bytes) {
    if (!ZIP_START.every(function (b, i) { return bytes[i] === b; }) || bytes.length < 30) return null;
    var length = bytes[26] + 256 * bytes[27], extra = bytes[28] + 256 * bytes[29];
    var ascii = function (from, to) {
      var s = '';
      for (var i = from; i < to && i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
      return s;
    };
    var name = ascii(30, 30 + length);
    if (EXCEL_ENTRIES.some(function (entry) { return name.indexOf(entry) === 0; })) return 'excel';
    if (name !== 'mimetype') return null;
    var kind = ascii(30 + length + extra, 30 + length + extra + 80);
    if (kind.indexOf(OPENDOCUMENT) !== 0) return null;
    return kind.indexOf(OPENDOCUMENT + 'spreadsheet') === 0 ? 'spreadsheet' : 'opendocument';
  }

  // the file's bytes, as the page reads them: the kinds told by their first bytes, then UTF-8
  function checkBytes(bytes, fileName) {
    bytes = new Uint8Array(bytes);
    if (BINARY_STARTS.some(function (start) { return start.every(function (b, i) { return bytes[i] === b; }); })) {
      var zip = zipKind(bytes);
      if (zip === 'excel') return fail('excel', EXCEL_FILE);
      if (zip === 'spreadsheet') return fail('excel', SPREADSHEET_FILE);
      if (zip === 'opendocument') return fail('not-recognised', NOT_RECOGNISED);
      return fail('full-tool', FULL_TOOL);
    }
    var fileText;
    try { fileText = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch (e) { return fail('not-utf8', NOT_UTF8); }
    return check(fileText, fileName);
  }

  function check(fileText, fileName) {
    if (!isStr(fileText)) fileText = '';
    if (fileText.charCodeAt(0) === 0xFEFF) fileText = fileText.slice(1);
    if (!fileText) return fail('empty', EMPTY);
    var r = read(fileText, fileName);
    if (r.ok === false) return r;
    if (r.error) return fail(r.error, r.message);
    var metrics = r.order || Array.from(new Set(r.judged.map(function (x) { return x.name; }))).sort(pyOrder);
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
    return { ok: true, tool: r.tool, toolName: toolName,
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
      name: oneLine(clean(metric, 80)) || 'unnamed',
      showName: nMetrics > 1 || r.tool === 'deepeval',
      answers: block.answers,
      pass: pool.nPass, fail: pool.nFail,
      merged: pool.merged, repeatSizes: pool.repeatSizes, split: pool.split,
      human: r.humanFor === undefined || r.humanFor === metric ? r.nHuman : 0, unmapped: pool.unmapped,
      readRows: r.readRows ? r.readRows[metric] : null,
      unread: pool.unread.slice(0, 3).map(function (v) { return oneLine(clean(v, 30)); }),
      moreUnread: pool.unread.length > 3,
      counts: block,
      allFailed: !pool.answers.length && pool.left.length > 0 && pool.left.every(function (l) { return l.kind === 'error'; }),
      allModelFailed: !pool.answers.length && pool.left.length > 0 && pool.left.every(function (l) { return l.kind === 'model_failed'; }),
      passMark: r.tool === 'deepeval' ? passMarkOf(pool) : null,
      modelNotWritten: r.tool === 'promptfoo' && !models.length,
      models: models.map(function (m) { return oneLine(clean(m, 120)); }),
      rule: rule === null ? null : oneLine(clean(rule)),
      findings: findingLines(block),
      first: pool.answers.length ? { input: pool.answers[0].input, output: pool.answers[0].output, verdict: pool.answers[0].verdict } : null
    };
  }

  /* ---------- what it says (front.py's Find block and free check) ---------- */

  // The note under Answers when answers are in the file more than once: repeats with the same
  // grade count once, repeats with different grades each count (front.repeats_note).
  function repeatsNote(j) {
    var times = j.repeatSizes.length === 1 && j.repeatSizes[0] > 1 ? j.repeatSizes[0] : null;
    var split = j.split.reduce(function (sum, s) { return sum + s[0]; }, 0);
    var head = '(your file has ' + (j.answers + j.merged) + ' results: ' +
      (times ? n(j.answers - split + j.split.length, 'answer') + ', each run ' + times + ' times' : 'some answers are in it more than once');
    if (!j.split.length) return head + ', so each counts once.)';
    var which = j.split.length === 1 ? '1 answer got different grades, so its' : j.split.length + ' answers got different grades, so their';
    return head + '. Repeats with the same grade count once. ' + which + ' ' + split + ' repeats each count.)';
  }

  // [{k, text, tone}] lines: tone is '', 'dim', 'g' (all clear) or 'y' (a finding)
  function reportLines(result, j) {
    var L = [];
    var pad = '                 ';
    L.push({ k: 'Eval tool:       ', text: result.toolName, tone: 'g' });
    L.push({ k: 'File:            ', text: result.file });
    L.push({ k: 'Answers:         ', text: n(j.answers, 'answer') });
    if (j.pass + j.fail && (j.merged || j.split.length)) L.push({ k: pad, text: repeatsNote(j), tone: 'dim' });
    var model = j.models.length ? j.models.join(', ') : 'model not found in your file';
    L.push({ k: 'LLM-as-a-judge:  ', text: (j.showName ? j.name + ', ' : '') + model });
    if (!j.rule) {
      L.push({ k: 'Rule:            ', text: 'not in your results' });
    } else if (j.rule.length <= RULE_SHOWN) {
      L.push({ k: 'Rule:            ', text: '"' + j.rule + '"' });
    } else {
      L.push({ k: 'Rule:            ', text: '"' + j.rule.slice(0, RULE_SHOWN - 1).replace(/\s+$/, '') + '…"' });
      L.push({ k: pad, text: '(shortened)', tone: 'dim' });
    }
    var mark = j.passMark ? ': Pass at ' + passMarkWords(j.passMark).replace(/^score /, '') : '';
    var rows = j.readRows ? j.readRows.slice() : [];
    if (result.tool === 'promptfoo') rows = [['question', "each test's vars"], ['answer', "each test's output"], ['grade', "your LLM-as-a-judge's Pass or Fail" + mark]];
    if (result.tool === 'deepeval') rows = [['question', "each test case's input"], ['answer', "each test case's actual_output"], ['grade', 'the ' + j.name + ' score' + mark], ['reason', "your LLM-as-a-judge's reason"]];
    if (rows.length) {
      var width = rows.reduce(function (w, r) { return Math.max(w, r[0].length); }, 0) + 3;
      L.push({ text: 'judgekeeper has read from your file:' });
      rows.forEach(function (r) { L.push({ text: '  ' + r[0] + new Array(width - r[0].length + 1).join(' ') + r[1] }); });
    }
    L.push({ text: '' });
    if (j.pass + j.fail) L.push({ text: 'Your LLM-as-a-judge passed ' + n(j.pass, 'answer') + ' and failed ' + j.fail + '.' });
    var notes = [];
    if (j.human) notes.push('Your results also hold ' + n(j.human, 'human label') + '. judgekeeper does not use them: you mark the answers yourself.');
    var total = j.pass + j.fail;
    [[j.fail, 'failed', 'passes too much'], [j.pass, 'passed', 'fails too much']].forEach(function (x) {
      if (x[0] > 0 && x[0] < ROUGH && total >= MIN_POOL) notes.push('Your LLM-as-a-judge ' + x[1] + ' only ' + x[0] + ' of ' + total + ' answers. That may mean it ' + x[2] + ': your marks will show it.');
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
    if (!total) L.push({ text: j.allModelFailed ? ALL_MODEL_FAILED : j.allFailed ? ALL_FAILED : NO_CLEAR, tone: 'y' });
    return L;
  }

  /* ---------- the page's own lines: the first answer it read ---------- */

  // A question or answer on one line, cut short. For promptfoo's vars, the question's var,
  // else the longest text in them.
  function shortText(v) {
    if (v === null || v === undefined) return '';
    if (isObj(v)) {
      var key = ['question', 'input', 'prompt', 'query'].find(function (k) { return isStr(v[k]); });
      var texts = Object.keys(v).map(function (k) { return v[k]; }).filter(isStr)
        .sort(function (a, b) { return b.length - a.length; });
      v = key ? v[key] : (texts.length ? texts[0] : canonical(v));
    }
    var s = oneLine(isStr(v) ? v : canonical(v));
    return s.length > FIRST_SHOWN ? s.slice(0, FIRST_SHOWN - 1).replace(/\s+$/, '') + '…' : s;
  }

  function firstAnswerLines(j) {
    if (!j.first) return [];
    return [{ text: '' }, { text: 'First answer in your file:' },
      { k: '  Question:        ', text: shortText(j.first.input) || '(none)' },
      { k: '  Answer:          ', text: shortText(j.first.output) || '(none)' },
      { k: '  LLM-as-a-judge:  ', text: j.first.verdict === 'pass' ? 'Pass' : 'Fail' }];
  }

  var api = { check: check, checkBytes: checkBytes, reportLines: reportLines, firstAnswerLines: firstAnswerLines, MAX_BYTES: MAX_BYTES, PRIVACY: PRIVACY,
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

  var NEXT = 'to see how often your LLM-as-a-judge agrees with you, run judgekeeper in your project folder and mark some answers.';
  var NEXT_AFTER_ERROR = 'pick another file, or run uvx judgekeeper in your project: it finds your results by itself.';

  // A line of the terminal: [class, text] parts; the class is one of Home's terminal colours
  function termLine(parts) {
    var row = el('span', 'ln');
    parts.forEach(function (p) { row.appendChild(el('span', p[0], p[1])); });
    return row;
  }
  function termTop(pre) {
    pre.appendChild(termLine([['t-prompt', '$ '], ['t-cmd', 'judgekeeper']]));
    pre.appendChild(termLine([['t-step', 'Step 1 of 5: Find']]));
    pre.appendChild(termLine([[null, '']]));
  }
  function termNext(pre, text) {
    pre.appendChild(termLine([[null, '']]));
    var row = termLine([['t-next', 'Next:'], [null, ' ' + text]]);
    row.classList.add('ln-next');
    pre.appendChild(row);
  }

  function setup() {
    var zone = document.getElementById('fc-drop');
    var input = document.getElementById('fc-file');
    var out = document.getElementById('fc-result');
    var wait = document.getElementById('ck-wait');
    var title = document.getElementById('ck-title');
    var clear = document.getElementById('fc-clear');
    var empty = zone && zone.querySelector('.fc-empty');
    var loaded = zone && zone.querySelector('.fc-loaded');
    var name = document.getElementById('fc-name');
    var examples = document.querySelector('.fc-try');
    if (!zone || !input || !out || !wait || !title || !clear || !empty || !loaded || !name || !examples) return;
    var waitTitle = title.textContent;

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { if (input.files && input.files[0]) take(input.files[0], input.files.length); input.value = ''; });
    // The drop box shows the file being checked, with Clear under its name; the examples hide
    // until Clear
    function boxShows(fileName) {
      var on = !!fileName;
      empty.hidden = on;
      loaded.hidden = !on;
      name.textContent = on ? oneLine(clean(fileName, 80)) : '';
      clear.hidden = !on;
      examples.hidden = on;
      zone.classList.toggle('has-file', on);
    }
    // Clear: back to the empty box, the examples and the waiting screen, ready for the next file
    clear.addEventListener('click', function () {
      boxShows('');
      out.replaceChildren();
      wait.hidden = false;
      title.textContent = waitTitle;
      zone.focus();
    });

    // a file dropped anywhere on the page goes to the check, never opens in the tab
    ['dragenter', 'dragover'].forEach(function (t) {
      document.addEventListener(t, function (e) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; zone.classList.add('over'); });
    });
    document.addEventListener('dragleave', function (e) { if (!e.relatedTarget) zone.classList.remove('over'); });
    document.addEventListener('drop', function (e) {
      e.preventDefault(); zone.classList.remove('over');
      var example = e.dataTransfer && e.dataTransfer.getData(EXAMPLE_TYPE);
      if (example) return knownExamples.indexOf(example) >= 0 && runExample(example);
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) take(files[0], files.length);
    });

    function take(file, count) {
      zone.classList.add('busy');
      if (file.size > MAX_BYTES) { done(); return showError(TOO_BIG, file.name); }
      var reader = new FileReader();
      reader.onerror = function () { done(); showError('This file could not be read. Try picking it again.', file.name); };
      reader.onload = function () {
        done();
        show(checkBytes(reader.result, file.name), count, file.name);
      };
      reader.readAsArrayBuffer(file);
    }
    function done() { zone.classList.remove('busy'); }

    // The example files: each a script from this site that sets JK_EXAMPLES[file], added on
    // the first click (connect-src stays 'none'), then read as a dropped file is. Click one, or
    // drag it into the box. Only the cards' names load: a drag can carry any text.
    var EXAMPLE_TYPE = 'application/x-judgekeeper-example';
    var knownExamples = Array.prototype.map.call(document.querySelectorAll('[data-example-file]'),
      function (card) { return card.getAttribute('data-example-file'); });
    function runExample(file) {
      if (knownExamples.indexOf(file) < 0) return;
      var shown = 'made-up example · ' + file;
      function ready() {
        done();
        var text = (root.JK_EXAMPLES || {})[file];
        if (!isStr(text)) return showError('The example file could not be loaded. Try again.', shown);
        show(checkBytes(new TextEncoder().encode(text).buffer, shown), 1, shown);
      }
      zone.classList.add('busy');
      if (root.JK_EXAMPLES && isStr(root.JK_EXAMPLES[file])) return ready();
      var tag = document.createElement('script');
      tag.src = 'assets/examples/' + file + '.js';
      tag.onload = ready;
      tag.onerror = ready;
      document.head.appendChild(tag);
    }
    Array.prototype.forEach.call(document.querySelectorAll('[data-example-file]'), function (card) {
      var file = card.getAttribute('data-example-file');
      card.addEventListener('click', function () { runExample(file); });
      card.addEventListener('dragstart', function (e) {
        e.dataTransfer.setData(EXAMPLE_TYPE, file);
        e.dataTransfer.effectAllowed = 'copy';
      });
    });

    function begin(fileName) {
      out.replaceChildren();
      wait.hidden = true;
      title.textContent = oneLine(clean(fileName || 'your file', 80));
      boxShows(fileName || 'your file');
    }

    function showError(message, fileName) {
      begin(fileName);
      var pre = el('pre', 'fc-term');
      termTop(pre);
      pre.appendChild(termLine([['t-warn', message]]));
      termNext(pre, NEXT_AFTER_ERROR);
      out.appendChild(pre);
    }

    function show(result, count, fileName) {
      if (!result.ok) return showError(result.message, fileName);
      begin(result.file);
      if (count > 1) out.appendChild(el('p', 'fc-many', 'You gave ' + count + ' files. This page reads one at a time: it read ' + result.file + '.'));
      var current = 0;
      var pre = el('pre', 'output fc-term');

      if (result.judges.length > 1) {
        var pick = el('div', 'fc-pick');
        var id = 'fc-pick-label';
        pick.appendChild(el('p', 'fc-pick-h', 'Your file has ' + result.judges.length + ' LLM-as-a-judge metrics. Pick one to check:')).id = id;
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

      // Labels dim, headings ("...:" on a line of their own) as Home's step lines, the all-clear
      // line green, findings amber.
      function paint() {
        pre.replaceChildren();
        termTop(pre);
        var j = result.judges[current];
        reportLines(result, j).concat(firstAnswerLines(j)).forEach(function (line) {
          var row = el('span', 'ln');
          if (line.k) row.appendChild(el('span', line.k.trim() ? 'k t-label' : 'k t-label pad', line.k));
          var tone = line.tone === 'y' ? 't-warn' : line.tone === 'dim' ? 't-label'
            : line.tone === 'g' && line.text.indexOf(FREE_CHECK) === 0 ? 't-good'
              : !line.k && /:$/.test(line.text) ? 't-step' : null;
          row.appendChild(el('span', tone, line.text));
          pre.appendChild(row);
        });
        termNext(pre, j.allModelFailed ? MODEL_FAILED_NEXT : NEXT);
      }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})(typeof globalThis !== 'undefined' ? globalThis : this);
